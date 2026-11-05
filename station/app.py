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
from station.link import LINK_EVENT, RobotLink
from station.parts import describe
from station.settings import StationSettings
from station.shaping import shape_inputs
from station.views.drive_tab import DriveTab, DriveTabActions
from station.views.mapping_tab import MappingTab
from station.views.tuning_tab import TuningTab
from station.widgets import StatusLight, TabBar, TitleBlock
from station.windows import resource_path

log = logging.getLogger(__name__)


class StationApp:
    """Reads the controller, talks to the robot and keeps the UI up to date.

    Safety rules on this side:

    * The robot can only be enabled while the controller and the robot are
      both connected, and it is disabled automatically if either drops out.
    * If the robot disables itself (its watchdog tripped), the station
      disables too, so the driver has to enable again on purpose.
    * The space bar disables from anywhere in the window.
    """

    TICK_MS = 1000 // COMMAND_RATE_HZ
    UI_REFRESH_TICKS = 3          # redraw the UI at about 17 Hz
    TELEMETRY_PRINT_S = 0.5       # "Show telemetry" prints at 2 Hz
    ENABLE_GRACE_S = 1.0          # time the robot gets to report "enabled" after we enable

    def __init__(self, root: tk.Tk, settings: StationSettings, host: Optional[str] = None) -> None:
        """``host`` overrides the saved robot address for this session without saving it."""
        self.root = root
        self.settings = settings
        self._host = host or settings.robot_host
        theme.apply_theme(root)
        root.title(APP_NAME)
        icon = resource_path("icon.ico")
        if icon.exists():
            root.iconbitmap(default=str(icon))
        root.geometry("1440x940")
        root.minsize(1200, 820)

        self.link = RobotLink(self._host)
        self.gamepad = Gamepad()

        self._enabled = False
        self._enabled_at = 0.0
        self._seq = 0
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

        self._build()
        root.bind_all("<space>", lambda _event: self._disable("Space bar"))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.terminal.write("station", f"Driver station started. Looking for the robot at '{self._host}'.")
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
        self._robot_light = StatusLight(block.add_cell("Robot"))
        self._robot_light.pack(anchor="w", pady=(2, 0))
        self._pad_light = StatusLight(block.add_cell("Controller"))
        self._pad_light.pack(anchor="w", pady=(2, 0))
        address = block.add_cell("Robot address")
        self._host_var = tk.StringVar(value=self._host)
        host_entry = ttk.Entry(address, textvariable=self._host_var, width=20, font=theme.FONT_MONO)
        host_entry.pack(side="left", pady=(2, 0))
        host_entry.bind("<Return>", lambda _event: self._connect())
        ttk.Button(address, text="Connect", command=self._connect, padding=(10, 3)).pack(
            side="left", padx=(6, 0), pady=(2, 0))

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

        if pad.connected:
            vx, vy, omega = shape_inputs(
                pad.left_x, pad.left_y, pad.right_x,
                drive_deadzone_pct=self.settings.drive_deadzone,
                drive_sensitivity_pct=self.settings.drive_sensitivity,
                turn_deadzone_pct=self.settings.turn_deadzone,
                turn_sensitivity_pct=self.settings.turn_sensitivity,
            )
        else:
            vx = vy = omega = 0.0

        if self._enabled and not pad.connected:
            self._disable("Controller disconnected")
        if self._enabled and not self.link.telemetry_alive:
            self._disable("Lost contact with the robot")

        self._seq += 1
        self.link.send_command(DriveCommand(
            seq=self._seq, enabled=self._enabled, vx=vx, vy=vy, omega=omega,
            zero_presses=self._zero_presses, home_presses=self._home_presses,
        ))

        for msg in self.link.poll():
            self._handle_message(msg)
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
            self.terminal.write("robot", "; ".join([text, *errors]), "INFO" if ok else "ERROR")
        elif kind == MsgType.LOG:
            self.terminal.write("robot", str(msg.get("message", "")), str(msg.get("level", "INFO")))
        elif kind == LINK_EVENT:
            level = "WARNING" if msg["event"] == "error" else "INFO"
            self.terminal.write("station", msg["message"], level)

    @staticmethod
    def _summarize_telemetry(msg: dict[str, Any]) -> str:
        parts = [f"#{msg.get('seq')} {msg.get('mode')} · loop {msg.get('loop_ms', 0):.2f} ms"]
        for name in MODULE_NAMES:
            module = msg.get("modules", {}).get(name)
            if module and module.get("angle") is not None:
                parts.append(f"{name} {module['angle']:+6.1f}° d{module['drive']:+.2f} s{module['steer']:+.2f}")
        return " | ".join(parts)

    # ----------------------------------------------------------------- actions

    def _toggle_enable(self) -> None:
        if self._enabled:
            self._disable("Disabled from the driver station")
        elif not self._pad.connected:
            self.terminal.write("station", "Connect a controller before enabling", "WARNING")
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
        if not host:
            return
        self._host = host
        self.settings.robot_host = host
        self.settings.save()
        self.link.set_host(host)
        self.terminal.write("station", f"Looking for the robot at '{host}'")

    def _select_part(self, part_id: Optional[str]) -> None:
        self._selected_part = part_id
        self.drive_tab.robot_view.select(part_id)
        self._refresh_part_panel()

    def _on_settings_changed(self) -> None:
        self.settings.save()

    # ---------------------------------------------------------------------- UI

    def _refresh_ui(self, vx: float, vy: float, omega: float) -> None:
        alive = self.link.telemetry_alive
        control = self.link.control_connected
        ip = self.link.robot_ip or "?"
        if alive and control:
            self._robot_light.set("ok", f"{self.link.host} ({ip})")
        elif alive or control:
            self._robot_light.set("warn", "Telemetry only" if alive else "Control link only, no telemetry")
        else:
            self._robot_light.set("error", f"Searching for {self.link.host}")
        if alive and not self._was_connected:
            self.terminal.write("station", "Receiving telemetry from the robot")
        elif not alive and self._was_connected:
            self.terminal.write("station", "No telemetry from the robot", "WARNING")
        self._was_connected = alive

        pad = self._pad
        self._pad_light.set("ok" if pad.connected else "error", pad.name if pad.connected else "Not detected")

        telemetry = self._telemetry if alive else None
        mode = "Robot not connected"
        if telemetry:
            mode = f"Robot mode: {telemetry['mode']}" + ("  ·  simulated hardware" if telemetry.get("simulated") else "")
        self.drive_tab.show_state(self._enabled, alive and pad.connected, mode, alive)
        self.drive_tab.show_inputs(vx, vy, omega)
        self.drive_tab.robot_view.update_modules(telemetry["modules"] if telemetry else None)
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
            self._seq += 1
            self.link.send_command(DriveCommand(seq=self._seq, enabled=False,
                                                zero_presses=self._zero_presses, home_presses=self._home_presses))
        self.settings.save()
        self.link.close()
        self.gamepad.close()
        self.root.destroy()
