"""The driver station window and its 50 Hz control tick."""

from __future__ import annotations

import logging
import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Optional

from common.config import MODULE_NAMES
from common.protocol import COMMAND_RATE_HZ, DriveCommand, MsgType
from station import APP_NAME, __version__, theme
from station.gamepad import Gamepad, GamepadState
from station.keyboard import KeyboardDrive, is_text_input
from station.link import LINK_EVENT, RobotLink
from station.parts import describe
from station.settings import StationSettings
from station.shaping import shape_inputs
from station.simulator import LocalSimulator
from station.views.drive_tab import DriveTab, DriveTabActions
from station.views.mapping_tab import MappingTab
from station.views.tuning_tab import TuningTab
from station.widgets import Segmented, StatusLight, TabBar, TitleBlock
from station.windows import resource_path

log = logging.getLogger(__name__)


class StationApp:
    """Reads the controller, talks to the robot and keeps the UI up to date.

    Safety rules on this side:

    * The robot can only be enabled while the robot is connected and there is
      an input (a controller, or keyboard control turned on). It is disabled
      automatically if either goes away, or when the connection is switched.
    * Keys typed into text boxes never drive, and keys count as released
      whenever the window loses focus.
    * If the robot disables itself (its watchdog tripped), the station
      disables too, so the driver has to enable again on purpose.
    * The space bar disables from anywhere in the window.
    """

    TICK_MS = 1000 // COMMAND_RATE_HZ
    UI_REFRESH_TICKS = 3          # redraw the UI at about 17 Hz
    TELEMETRY_PRINT_S = 0.5       # "Show telemetry" prints at 2 Hz
    ENABLE_GRACE_S = 1.0          # time the robot gets to report "enabled" after we enable
    SIMULATOR_RETRY_S = 3.0       # how often Simulator mode re-checks for a simulator to talk to
    PENDING_SWITCH_S = 1.5        # keep showing a toggled switch while the robot confirms it

    def __init__(self, root: tk.Tk, settings: StationSettings, host: Optional[str] = None) -> None:
        """``host`` connects to that robot address for this session, without saving it."""
        self.root = root
        self.settings = settings
        self._robot_host = host or settings.robot_host
        self._connection = "robot" if host else settings.connection
        theme.apply_theme(root)
        root.title(APP_NAME)
        icon = resource_path("icon.ico")
        if icon.exists():
            root.iconbitmap(default=str(icon))
        root.geometry("1440x940")
        root.minsize(1200, 820)

        self.simulator = LocalSimulator()
        self.link = RobotLink(self._current_host())
        self.gamepad = Gamepad()

        self._enabled = False
        self._enabled_at = 0.0
        self._zero_presses = 0
        self._home_presses = 0
        self._pad = GamepadState()
        self._previous_pad = GamepadState()
        self._telemetry: Optional[dict[str, Any]] = None
        self._robot_config: Optional[dict[str, Any]] = None
        self._selected_part: Optional[str] = None
        self._ticks = 0
        self._last_telemetry_print = 0.0
        self._was_connected = False
        self._tick_job: Optional[str] = None
        self._keyboard_paused = False
        self._simulator_checked_at = time.monotonic()
        self._field_pending_until = 0.0

        self._build()
        self.keyboard = KeyboardDrive(root, on_change=self.drive_tab.show_held_keys)
        self.keyboard.enabled = settings.keyboard_control
        root.bind_all("<space>", lambda _event: self._disable("Space bar"))
        # Clicking anywhere but a text box takes focus out of it, so the keys drive again.
        root.bind_all("<Button-1>", self._focus_clicked_area, add="+")
        root.bind_all("<Escape>", lambda _event: self.root.focus_set())
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.terminal.write("station", "Driver station started.")
        if self._connection == "simulator":
            self.terminal.write("station", self.simulator.start())
        self.terminal.write("station", f"Looking for {self._target_name()}.")
        self._tick_job = root.after(self.TICK_MS, self._tick)

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        # Header: drawing title on the left, title block on the right.
        header = ttk.Frame(outer, padding=(20, 16, 20, 10))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        title = ttk.Frame(header)
        title.grid(row=0, column=0, sticky="sw")
        ttk.Label(title, text=f"DIFFERENTIAL SWERVE DRIVEBASE  ·  CONTROL  ·  V{__version__}",
                  style="Label.TLabel").pack(anchor="w")
        ttk.Label(title, text="Driver Station", style="Title.TLabel").pack(anchor="w")

        block = TitleBlock(header)
        block.grid(row=0, column=1, sticky="se")
        self._connection_switch = Segmented(block.add_cell("Connection"),
                                            (("simulator", "Simulator"), ("robot", "Robot")),
                                            self._connection, self._set_connection)
        self._connection_switch.pack(anchor="w", pady=(3, 0))
        self._robot_light = StatusLight(block.add_cell("Robot"))
        self._robot_light.pack(anchor="w", pady=(2, 0))
        self._pad_light = StatusLight(block.add_cell("Input"))
        self._pad_light.pack(anchor="w", pady=(2, 0))
        address = block.add_cell("Robot address")
        self._host_var = tk.StringVar(value=self._robot_host)
        self._host_entry = ttk.Entry(address, textvariable=self._host_var, width=20, font=theme.FONT_MONO)
        self._host_entry.pack(side="left", pady=(2, 0))
        self._host_entry.bind("<Return>", lambda _event: self._connect())
        self._connect_button = ttk.Button(address, text="Connect", command=self._connect, padding=(10, 3))
        self._connect_button.pack(side="left", padx=(6, 0), pady=(2, 0))
        self._show_connection_widgets()

        self._tabs = TabBar(outer, on_select=self._show_page)
        self._tabs.grid(row=1, column=0, sticky="w", padx=20)
        tk.Frame(outer, height=2, bg=theme.INK).grid(row=2, column=0, sticky="ew")

        pages = ttk.Frame(outer)
        pages.grid(row=3, column=0, sticky="nsew")
        pages.columnconfigure(0, weight=1)
        pages.rowconfigure(0, weight=1)
        self.drive_tab = DriveTab(pages, self.settings, DriveTabActions(
            toggle_enable=self._toggle_enable,
            set_zero=self._set_zero,
            return_to_zero=self._return_to_zero,
            select_part=self._select_part,
            settings_changed=self._on_settings_changed,
            keyboard_toggled=self._set_keyboard,
            field_toggled=self._set_field_relative,
            set_field_forward=self._set_field_forward,
        ))
        self.mapping_tab = MappingTab(pages, apply=lambda update: self._send_config(update, "mapping"))
        self.tuning_tab = TuningTab(pages, apply=lambda update: self._send_config(update, "tuning"))
        self._pages = {"drive": self.drive_tab, "mapping": self.mapping_tab, "tuning": self.tuning_tab}
        for key, page in self._pages.items():
            page.grid(row=0, column=0, sticky="nsew")
            self._tabs.add(key, key)
        self._show_page("drive")
        self.terminal = self.drive_tab.terminal

    # -------------------------------------------------------------------- tick

    def _tick(self) -> None:
        try:
            self._step()
        except Exception:
            log.exception("Driver station tick failed")
        finally:
            self._tick_job = self.root.after(self.TICK_MS, self._tick)

    def _step(self) -> None:
        self._previous_pad, self._pad = self._pad, self.gamepad.poll()
        pad = self._pad
        if pad.back and not self._previous_pad.back:
            self._set_zero()
        if pad.start and not self._previous_pad.start:
            self._return_to_zero()

        keys = self.keyboard.poll()  # None while keyboard control is off
        paused = self.keyboard.enabled and self.keyboard.paused
        if paused != self._keyboard_paused:
            self._keyboard_paused = paused
            self.drive_tab.show_keyboard(self.keyboard.enabled, paused)
        # Held keys win; otherwise the controller, if there is one.
        if keys is not None and any(keys):
            sticks: Optional[tuple[float, float, float]] = keys
        elif pad.connected:
            sticks = (pad.left_x, pad.left_y, pad.right_x)
        else:
            sticks = None
        if sticks is not None:
            vx, vy, omega = shape_inputs(
                *sticks,
                drive_deadzone_pct=self.settings.drive_deadzone,
                drive_sensitivity_pct=self.settings.drive_sensitivity,
                turn_deadzone_pct=self.settings.turn_deadzone,
                turn_sensitivity_pct=self.settings.turn_sensitivity,
            )
        else:
            vx = vy = omega = 0.0

        # Read what has arrived first, so a late tick does not look like a lost robot.
        for msg in self.link.poll():
            self._handle_message(msg)

        if self._enabled and not self._has_input:
            self._disable("Controller disconnected")
        if self._enabled and not self.link.telemetry_alive:
            self._disable("Lost contact with the robot")

        self.link.set_command(DriveCommand(
            enabled=self._enabled, vx=vx, vy=vy, omega=omega,
            zero_presses=self._zero_presses, home_presses=self._home_presses,
        ))
        if self._enabled and self.link.telemetry_alive and self._telemetry \
                and self._telemetry.get("mode") == "disabled" \
                and time.monotonic() - self._enabled_at > self.ENABLE_GRACE_S:
            self._disable("The robot disabled itself (it stopped hearing commands). Enable again to continue")

        self._ticks += 1
        if self._ticks % self.UI_REFRESH_TICKS == 0:
            self._refresh_ui(vx, vy, omega)

    # ---------------------------------------------------------------- messages

    def _handle_message(self, msg: dict[str, Any]) -> None:
        kind = msg["type"]
        if kind == MsgType.TELEMETRY:
            self._telemetry = msg
            if self.drive_tab.show_telemetry.get() and \
                    time.monotonic() - self._last_telemetry_print > self.TELEMETRY_PRINT_S:
                self._last_telemetry_print = time.monotonic()
                self.terminal.write("data", self._summarize_telemetry(msg), "DEBUG")
        elif kind == MsgType.CONFIG and isinstance(msg.get("config"), dict):
            self._robot_config = msg["config"]
            self.mapping_tab.load(self._robot_config)
            self.tuning_tab.load(self._robot_config)
            self.terminal.write("robot", "Sent its configuration")
        elif kind == MsgType.RESULT:
            ok, text, errors = bool(msg.get("ok")), str(msg.get("message", "")), list(msg.get("errors", []))
            target = {"mapping": self.mapping_tab, "tuning": self.tuning_tab}.get(msg.get("tag"))
            if target is not None:
                target.show_result(ok, text, errors)
            if msg.get("tag") == "field":
                self._field_pending_until = 0.0  # show what the robot actually has now
            self.terminal.write("robot", "; ".join([text, *errors]), "INFO" if ok else "ERROR")
        elif kind == MsgType.LOG:
            self.terminal.write("robot", str(msg.get("message", "")), str(msg.get("level", "INFO")))
        elif kind == LINK_EVENT:
            level = "WARNING" if msg["event"] == "error" else "INFO"
            self.terminal.write("station", msg["message"], level)

    @staticmethod
    def _summarize_telemetry(msg: dict[str, Any]) -> str:
        parts = [f"#{msg.get('seq')} {msg.get('mode')} · loop {msg.get('loop_ms', 0):.2f} ms"]
        heading = (msg.get("imu") or {}).get("heading")
        if heading is not None:
            parts.append(f"heading {heading:+.1f}°{' field' if msg.get('field_relative_active') else ''}")
        for name in MODULE_NAMES:
            module = msg.get("modules", {}).get(name)
            if module and module.get("angle") is not None:
                parts.append(f"{name} {module['angle']:+6.1f}° d{module['drive']:+.2f} s{module['steer']:+.2f}")
        return " | ".join(parts)

    # ----------------------------------------------------------------- actions

    @property
    def _has_input(self) -> bool:
        return self._pad.connected or self.keyboard.enabled

    def _toggle_enable(self) -> None:
        if self._enabled:
            self._disable("Disabled from the driver station")
        elif not self._has_input:
            self.terminal.write("station", "Connect a controller or turn on keyboard control before enabling",
                                "WARNING")
        elif not self.link.telemetry_alive:
            self.terminal.write("station", "The robot is not connected", "WARNING")
        else:
            self._enabled = True
            self._enabled_at = time.monotonic()
            self.terminal.write("station", "Enabled")

    def _disable(self, reason: str) -> None:
        if self._enabled:
            self._enabled = False
            self.terminal.write("station", f"Disabled: {reason}", "WARNING")

    def _set_zero(self) -> None:
        if not self.link.telemetry_alive:
            self.terminal.write("station", "Swerve Set Zero needs the robot connected", "WARNING")
            return
        if self._enabled:
            self.terminal.write("station", "Swerve Set Zero works while disabled: disable, line the wheels "
                                           "up by hand, then press it", "WARNING")
            return
        self._zero_presses += 1
        self.terminal.write("station", "Swerve Set Zero sent")

    def _return_to_zero(self) -> None:
        if not self._enabled:
            self.terminal.write("station", "Return to Zero needs the robot enabled", "WARNING")
            return
        self._home_presses += 1
        self.terminal.write("station", "Return to Zero sent")

    def _send_config(self, update: dict[str, Any], tag: str) -> bool:
        return self.link.send_control({"type": MsgType.SET_CONFIG, "tag": tag, "config": update})

    def _show_page(self, key: str) -> None:
        self._pages[key].tkraise()
        self._tabs.select(key)

    def _connect(self) -> None:
        host = self._host_var.get().strip()
        if not host or self._connection != "robot":
            return
        self._robot_host = host
        self.settings.robot_host = host
        self.settings.save()
        self.link.set_host(host)
        self.terminal.write("station", f"Looking for {self._target_name()}.")

    def _current_host(self) -> str:
        return "localhost" if self._connection == "simulator" else self._robot_host

    def _target_name(self) -> str:
        return "the built-in simulator" if self._connection == "simulator" else f"the robot at '{self._robot_host}'"

    def _set_connection(self, connection: str) -> None:
        """Switch between the built-in simulator and the real robot."""
        if connection == self._connection:
            return
        self._disable("Switched connection")
        self._connection = connection
        self.settings.connection = connection
        self.settings.save()
        self._connection_switch.set(connection)
        self._show_connection_widgets()
        self._telemetry = None
        if connection == "simulator":
            self.terminal.write("station", self.simulator.start())
        else:
            self.simulator.stop()
        self.link.set_host(self._current_host())
        self.terminal.write("station", f"Looking for {self._target_name()}.")

    def _keep_simulator_available(self, alive: bool) -> None:
        """In Simulator mode, start the built-in simulator whenever none is answering.

        Covers a simulator started by hand that was closed, and the built-in
        one stopping on an error (it is restarted after a pause).
        """
        now = time.monotonic()
        if self._connection != "simulator" or alive or self.simulator.running \
                or now - self._simulator_checked_at < self.SIMULATOR_RETRY_S:
            return
        self._simulator_checked_at = now
        message = self.simulator.start()
        if message.startswith("Starting"):
            self.terminal.write("station", message)

    def _show_connection_widgets(self) -> None:
        state = ["!disabled"] if self._connection == "robot" else ["disabled"]
        self._host_entry.state(state)
        self._connect_button.state(state)

    def _set_keyboard(self, on: bool) -> None:
        self.keyboard.enabled = on
        self.settings.keyboard_control = on
        self.settings.save()
        self._keyboard_paused = on and self.keyboard.paused
        self.drive_tab.show_keyboard(on, self._keyboard_paused)
        self.terminal.write("station", f"Keyboard control {'on' if on else 'off'}")
        if not on and self._enabled and not self._pad.connected:
            self._disable("Keyboard control turned off and no controller is connected")

    def _set_field_relative(self, on: bool) -> None:
        """Turn field-relative drive on or off. The robot saves it and works live, even while driving."""
        sent = self.link.send_control({"type": MsgType.SET_CONFIG, "tag": "field", "config": {"field_relative": on}})
        if sent:
            self._field_pending_until = time.monotonic() + self.PENDING_SWITCH_S
            self.terminal.write("station", f"Field-relative drive {'on' if on else 'off'}")
        else:
            self.terminal.write("station", "Not connected: field-relative drive not changed", "WARNING")

    def _set_field_forward(self, facing_deg: float) -> None:
        if not self.link.send_control({"type": MsgType.SET_FIELD_FORWARD, "tag": "field", "facing_deg": facing_deg}):
            self.terminal.write("station", "Not connected: field forward not set", "WARNING")

    def _focus_clicked_area(self, event: tk.Event) -> None:
        if not is_text_input(event.widget):
            self.root.focus_set()

    def _select_part(self, part_id: Optional[str]) -> None:
        self._selected_part = part_id
        self.drive_tab.robot_view.select(part_id)
        self._refresh_part_panel()

    def _on_settings_changed(self) -> None:
        self.settings.save()

    # ---------------------------------------------------------------------- UI

    def _refresh_ui(self, vx: float, vy: float, omega: float) -> None:
        stopped = self.simulator.check()
        if stopped:
            self.terminal.write("station", stopped, "ERROR")
        alive = self.link.telemetry_alive
        self._keep_simulator_available(alive)
        control = self.link.control_connected
        ip = self.link.robot_ip or "?"
        if alive and control:
            self._robot_light.set("ok", "Simulator" if self._connection == "simulator" else f"{self.link.host} ({ip})")
        elif alive or control:
            self._robot_light.set("warn", "Telemetry only" if alive else "Control link only, no telemetry")
        else:
            self._robot_light.set("error", "Starting simulator" if self._connection == "simulator"
                                  else f"Searching for {self.link.host}")
        if alive and not self._was_connected:
            self.terminal.write("station", "Receiving telemetry from the robot")
        elif not alive and self._was_connected:
            self.terminal.write("station", "No telemetry from the robot", "WARNING")
        self._was_connected = alive

        pad = self._pad
        if pad.connected:
            self._pad_light.set("ok", pad.name)
        elif self.keyboard.enabled:
            self._pad_light.set("ok", "Keyboard")
        else:
            self._pad_light.set("error", "No controller")

        telemetry = self._telemetry if alive else None
        mode = "Robot not connected"
        if telemetry:
            mode = f"Robot mode: {telemetry['mode']}" + ("  ·  simulated hardware" if telemetry.get("simulated") else "")
        self.drive_tab.show_state(self._enabled, alive and self._has_input, mode, alive)
        self.drive_tab.show_inputs(vx, vy, omega)
        self.drive_tab.robot_view.update_modules(telemetry["modules"] if telemetry else None)
        imu = telemetry.get("imu") if telemetry else None
        self.drive_tab.robot_view.update_heading(imu.get("heading") if imu else None)
        field_relative = self._robot_config.get("field_relative") if self._robot_config and control else None
        self.drive_tab.show_field(field_relative, connected=alive and control, imu=imu,
                                  update_switch=time.monotonic() >= self._field_pending_until)
        self._refresh_part_panel()

        robot_disabled = bool(telemetry) and telemetry["mode"] == "disabled" and not self._enabled
        reason = "" if robot_disabled else "Disable the robot to apply mapping changes."
        self.mapping_tab.set_can_apply(control and robot_disabled, reason)
        self.tuning_tab.set_connected(control)

    def _refresh_part_panel(self) -> None:
        if self._selected_part is None:
            self.drive_tab.show_part(None)
            return
        telemetry = self._telemetry if self.link.telemetry_alive else None
        self.drive_tab.show_part(describe(self._selected_part, self._robot_config, telemetry))

    # ------------------------------------------------------------------- close

    def close(self) -> None:
        if self._tick_job is not None:
            self.root.after_cancel(self._tick_job)
            self._tick_job = None
        self._enabled = False
        for _ in range(3):  # make sure the robot hears "disabled" before the station goes quiet
            self.link.send_now(DriveCommand(enabled=False, zero_presses=self._zero_presses,
                                            home_presses=self._home_presses))
        self.settings.save()
        self.link.close()
        self.simulator.stop()
        self.gamepad.close()
        self.root.destroy()
