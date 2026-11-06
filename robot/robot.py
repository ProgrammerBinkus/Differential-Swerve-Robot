"""The robot's main control loop."""

from __future__ import annotations

import enum
import logging
import math
import queue
import threading
import time
from pathlib import Path
from typing import Any

from common.config import MAPPING_SECTIONS, ConfigError, merge_config, validate_config
from common.protocol import TCP_PORT, TELEMETRY_RATE_HZ, UDP_PORT, DriveCommand, MsgType
from robot.config_store import ConfigStore
from robot.hardware import HardwareError, open_hardware
from robot.net import BroadcastLogHandler, CommandReceiver, ControlEvent, ControlServer
from robot.swerve.drivetrain import Drivetrain
from robot.swerve.mixing import RateLimiter

log = logging.getLogger(__name__)


class Mode(enum.Enum):
    DISABLED = "disabled"   # motors coast
    DRIVE = "drive"         # following the driver's sticks
    HOMING = "homing"       # "Return to Zero": steering every wheel to 0 degrees


class Robot:
    """Ties hardware, drivetrain and network together in a fixed-rate loop.

    Safety rules:

    * Motors only run while the station says "enabled" **and** commands are
      fresh. No command for ``watchdog_s`` (250 ms) disables the robot.
    * After start-up or a watchdog trip, the robot will not enable until the
      station has sent "disabled" at least once, so a station that was left
      enabled cannot start the robot moving the moment the link comes back.
    * Mapping changes and Swerve Set Zero are only accepted while disabled.
    * Field-relative drive needs a calibrated IMU. Without one (missing,
      calibrating, or failed) the robot drives robot-relative and says so.
    * On shutdown the wheels are steered back to zero, as the BOM requires.
    """

    HOMING_TIMEOUT_S = 4.0
    SHUTDOWN_HOMING_S = 2.5

    def __init__(self, config_path: Path, simulate: bool, udp_port: int = UDP_PORT,
                 tcp_port: int = TCP_PORT) -> None:
        self._store = ConfigStore(config_path)
        self.config = self._store.load()
        self._hardware = open_hardware(self.config, simulate)
        self._receiver: CommandReceiver | None = None
        try:
            self._drivetrain = Drivetrain.from_config(self._hardware, self.config)
            self._receiver = CommandReceiver(udp_port)
            self._control = ControlServer(tcp_port)
        except Exception:
            if self._receiver is not None:
                self._receiver.close()
            self._hardware.close()
            raise
        self._log_handler = BroadcastLogHandler(self._control)
        logging.getLogger().addHandler(self._log_handler)

        self._period_s = 1.0 / self.config["loop_hz"]
        self._telemetry_every = max(1, round(self.config["loop_hz"] / TELEMETRY_RATE_HZ))
        accel = self.config["tuning"]["accel_limit"]
        self._limiters = [RateLimiter(accel) for _ in range(3)]  # vx, vy, omega

        if self.config["field_relative"] and self._hardware.imu.status == "absent":
            log.warning("Field-relative drive is on but no IMU was found; driving robot-relative")

        self._stop = threading.Event()
        self._mode = Mode.DISABLED
        self._needs_disabled_command = True  # see the class docstring
        self._field_heading_ok = True         # for logging changes in field-relative availability
        self._command = DriveCommand()
        self._command_time = -math.inf
        self._zero_presses: int | None = None
        self._home_presses: int | None = None
        self._homing_started = 0.0
        self._telemetry_seq = 0
        self._loop_ms = 0.0
        self._loop_ms_max = 0.0

    # ------------------------------------------------------------------ loop

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        log.info("Robot running at %d Hz%s", self.config["loop_hz"],
                 " (simulated hardware)" if self._hardware.simulated else "")
        next_tick = last = time.perf_counter()
        tick = 0
        try:
            while not self._stop.is_set():
                started = time.perf_counter()
                self._step(started, started - last)
                last = started
                self._record_loop_time(time.perf_counter() - started)
                tick += 1
                if tick % self._telemetry_every == 0:
                    self._send_telemetry()

                next_tick += self._period_s
                delay = next_tick - time.perf_counter()
                if delay > 0:
                    self._stop.wait(delay)
                elif delay < -5 * self._period_s:
                    next_tick = time.perf_counter()  # fell far behind: restart the schedule
        finally:
            self._shutdown()

    def _step(self, now: float, dt: float) -> None:
        self._hardware.step(dt)
        self._drivetrain.read_sensors()
        self._hardware.imu.update(dt)
        self._handle_control_messages()

        command = self._receiver.poll(now)
        if command is not None:
            self._command, self._command_time = command, now
        fresh = now - self._command_time < self.config["watchdog_s"]
        if fresh:
            if not self._command.enabled:
                self._needs_disabled_command = False
            self._handle_buttons(self._command, now)
        else:
            # The station may restart and reset its counters; resync on its next command.
            self._zero_presses = self._home_presses = None

        self._update_mode(fresh and self._command.enabled and not self._needs_disabled_command, fresh)

        if self._mode is Mode.DISABLED:
            self._drivetrain.stop()
        elif self._mode is Mode.HOMING:
            self._run_homing(now)
        else:
            vx, vy, omega = (limiter.calculate(target, dt) for limiter, target in
                             zip(self._limiters, (self._command.vx, self._command.vy, self._command.omega)))
            self._drivetrain.drive(vx, vy, omega, self._field_heading())

    def _field_heading(self) -> float | None:
        """The heading to drive field-relative with, or None for robot-relative."""
        if not self.config["field_relative"]:
            return None
        heading = self._hardware.imu.heading_deg
        if (heading is not None) != self._field_heading_ok:
            self._field_heading_ok = heading is not None
            if heading is None:
                log.warning("Field-relative drive unavailable (IMU %s); driving robot-relative",
                            self._hardware.imu.status)
            else:
                log.info("Field-relative drive active")
        return heading

    def _update_mode(self, want_enabled: bool, fresh: bool) -> None:
        if not want_enabled:
            if self._mode is not Mode.DISABLED:
                if fresh:
                    log.info("Disabled by the driver station")
                else:
                    log.warning("Disabled: no commands for %.0f ms (watchdog). Enable again from the "
                                "driver station.", self.config["watchdog_s"] * 1000)
                    self._needs_disabled_command = True
                self._mode = Mode.DISABLED
                self._drivetrain.stop()
        elif self._mode is Mode.DISABLED:
            log.info("Enabled")
            self._drivetrain.hold_current_angles()
            for limiter in self._limiters:
                limiter.reset()
            self._mode = Mode.DRIVE

    def _run_homing(self, now: float) -> None:
        if self._drivetrain.home():
            log.info("Return to Zero: all wheels at zero")
            self._mode = Mode.DRIVE
        elif now - self._homing_started > self.HOMING_TIMEOUT_S:
            log.warning("Return to Zero timed out after %.0f s", self.HOMING_TIMEOUT_S)
            self._mode = Mode.DRIVE
        if self._mode is Mode.DRIVE:
            for limiter in self._limiters:
                limiter.reset()

    # --------------------------------------------------------------- buttons

    def _handle_buttons(self, command: DriveCommand, now: float) -> None:
        if self._zero_presses is not None:
            if command.zero_presses != self._zero_presses:
                self._set_zero()
            if command.home_presses != self._home_presses:
                self._start_homing(now)
        self._zero_presses, self._home_presses = command.zero_presses, command.home_presses

    def _set_zero(self) -> None:
        if self._mode is not Mode.DISABLED:
            log.warning("Swerve Set Zero ignored: disable the robot and line the wheels up by hand first")
            return
        offsets = self._drivetrain.rezero()
        if not offsets:
            log.error("Swerve Set Zero ignored: no working encoders")
            return
        for name, offset in offsets.items():
            self.config["modules"][name]["offset"] = offset
        self._save_config()
        log.info("Swerve Set Zero: offsets %s", ", ".join(f"{n}={o}" for n, o in offsets.items()))
        self._control.broadcast(self._config_message())

    def _start_homing(self, now: float) -> None:
        if self._mode is Mode.DISABLED:
            log.warning("Return to Zero needs the robot enabled")
            return
        if not self._drivetrain.any_ready:
            log.error("Return to Zero ignored: no working encoders")
            return
        log.info("Return to Zero")
        self._mode = Mode.HOMING
        self._homing_started = now

    # --------------------------------------------------------- control link

    def _handle_control_messages(self) -> None:
        while True:
            try:
                event: ControlEvent = self._control.inbox.get_nowait()
            except queue.Empty:
                return
            kind = event.msg.get("type")
            if kind in (ControlServer.CONNECTED, MsgType.GET_CONFIG):
                event.client.send(self._config_message())
            elif kind == MsgType.SET_CONFIG:
                event.client.send(self._apply_config_update(event.msg))
            elif kind == MsgType.SET_FIELD_FORWARD:
                event.client.send(self._set_field_forward(event.msg))
            else:
                log.debug("Ignoring control message of type %r", kind)

    def _apply_config_update(self, msg: dict[str, Any]) -> dict[str, Any]:
        def result(ok: bool, message: str, errors: list[str] | None = None) -> dict[str, Any]:
            return {"type": MsgType.RESULT, "request": MsgType.SET_CONFIG, "tag": msg.get("tag"),
                    "ok": ok, "message": message, "errors": errors or []}

        update = msg.get("config")
        if not isinstance(update, dict) or not update:
            return result(False, "Malformed configuration update")
        mapping_changed = any(section in update for section in MAPPING_SECTIONS)
        if mapping_changed and self._mode is not Mode.DISABLED:
            return result(False, "Disable the robot before changing the mapping")
        try:
            merged = merge_config(self.config, update)
        except ConfigError as exc:
            return result(False, str(exc))
        errors = validate_config(merged)
        if errors:
            return result(False, "Configuration rejected", errors)

        if mapping_changed:
            try:
                self._hardware.reconfigure(merged)
            except HardwareError as exc:
                try:
                    self._hardware.reconfigure(self.config)
                except HardwareError as restore_exc:
                    log.error("Could not restore the previous encoder buses: %s", restore_exc)
                return result(False, str(exc))
            self._drivetrain.stop()
            self._drivetrain = Drivetrain.from_config(self._hardware, merged)
            log.warning("Module mapping changed; steering angles re-read from the encoders")
        else:
            self._drivetrain.apply_tuning(merged["tuning"])
            if self._hardware.simulated:
                self._hardware.reconfigure(merged)  # the simulator's wheel speed follows max_speed_mps
        for limiter in self._limiters:
            limiter.rate_per_s = merged["tuning"]["accel_limit"]

        self.config = merged
        self._save_config()
        self._control.broadcast(self._config_message())
        log.info("Configuration updated (%s)", ", ".join(update))
        return result(True, "Saved on the robot")

    def _set_field_forward(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Make the current heading equal ``facing_deg`` (0 = facing away from the driver station)."""
        def result(ok: bool, message: str) -> dict[str, Any]:
            return {"type": MsgType.RESULT, "request": MsgType.SET_FIELD_FORWARD, "tag": msg.get("tag"),
                    "ok": ok, "message": message, "errors": []}

        facing = msg.get("facing_deg")
        if not isinstance(facing, (int, float)) or isinstance(facing, bool) or not math.isfinite(facing):
            return result(False, "facing_deg must be a number of degrees")
        imu = self._hardware.imu
        if not imu.set_field_forward(float(facing)):
            return result(False, f"Can't set field forward: IMU {imu.status}")
        log.info("Field forward set: the robot faces %+.0f° from away-from-the-driver", facing)
        return result(True, "Field forward set")

    def _config_message(self) -> dict[str, Any]:
        return {"type": MsgType.CONFIG, "config": self.config}

    def _save_config(self) -> None:
        try:
            self._store.save(self.config)
        except OSError as exc:
            log.error("Could not save %s: %s", self._store.path, exc)

    # ------------------------------------------------------------- telemetry

    def _record_loop_time(self, seconds: float) -> None:
        self._loop_ms = seconds * 1000.0
        self._loop_ms_max = max(self._loop_ms_max, self._loop_ms)

    def _send_telemetry(self) -> None:
        self._telemetry_seq += 1
        self._receiver.send_telemetry({
            "type": MsgType.TELEMETRY,
            "seq": self._telemetry_seq,
            "mode": self._mode.value,
            "loop_ms": round(self._loop_ms, 3),
            "loop_ms_max": round(self._loop_ms_max, 3),
            "field_relative": self.config["field_relative"],
            "field_relative_active": self.config["field_relative"] and self._hardware.imu.heading_deg is not None,
            "simulated": self._hardware.simulated,
            "modules": self._drivetrain.telemetry(),
            "imu": self._hardware.imu.telemetry(),
        })
        self._loop_ms_max = 0.0

    # -------------------------------------------------------------- shutdown

    def _shutdown(self) -> None:
        try:
            if self._drivetrain.any_ready:
                self._home_before_exit()
            else:
                log.warning("Shutting down without returning to zero: no working encoders")
        finally:
            self._drivetrain.stop()
            self._hardware.close()
            logging.getLogger().removeHandler(self._log_handler)
            self._control.close()
            self._receiver.close()

    def _home_before_exit(self) -> None:
        log.info("Shutting down: returning wheels to zero")
        last = time.perf_counter()
        deadline = last + self.SHUTDOWN_HOMING_S
        while True:
            now = time.perf_counter()
            self._hardware.step(now - last)
            last = now
            self._drivetrain.read_sensors()
            if self._drivetrain.home():
                log.info("Wheels at zero")
                return
            if now > deadline:
                log.warning("Wheels did not reach zero within %.1f s", self.SHUTDOWN_HOMING_S)
                return
            time.sleep(self._period_s)
