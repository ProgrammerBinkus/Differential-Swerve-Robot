"""Station side of the network link to the robot."""

from __future__ import annotations

import dataclasses
import logging
import queue
import socket
import threading
import time
from typing import Any, Optional

from common.protocol import (
    COMMAND_RATE_HZ, MAX_DATAGRAM_BYTES, TCP_PORT, UDP_PORT, DriveCommand, LineBuffer, MsgType, decode,
    encode, encode_line, open_udp_socket,
)

# Messages the link itself generates for the UI (never sent over the network).
LINK_EVENT = "_link"

log = logging.getLogger(__name__)


class RobotLink:
    """UDP drive commands and telemetry, plus a TCP control connection that reconnects by itself.

    Drive commands go out from their own thread at a steady 50 Hz, so a busy
    or briefly throttled window cannot starve the robot's watchdog. The UI
    hands over the latest command with :meth:`set_command` every tick; if the
    UI stops doing that for ``STALE_COMMAND_S`` (it has hung), sending stops
    and the robot disables itself.

    Network waiting happens on background threads. The UI thread calls
    :meth:`poll` every tick to collect received messages, so Tk widgets are
    only ever touched from the UI thread.
    """

    # How long without robot telemetry before the station disables. Motor noise can stall the robot's
    # Wi-Fi for a few hundred ms; 1.5 s rides through that. The robot's own watchdog (watchdog_s) still
    # stops it when commands stop arriving.
    TELEMETRY_TIMEOUT_S = 1.5
    RECONNECT_DELAY_S = 1.5
    COMMAND_INTERVAL_S = 1.0 / COMMAND_RATE_HZ
    STALE_COMMAND_S = 1.0

    def __init__(self, host: str, udp_port: int = UDP_PORT, tcp_port: int = TCP_PORT) -> None:
        self._udp_port, self._tcp_port = udp_port, tcp_port
        self._udp = open_udp_socket(0)
        self._inbox: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self._lock = threading.Lock()
        self._host = host
        self._robot_ip: Optional[str] = None
        self._tcp: Optional[socket.socket] = None
        self._host_changed = threading.Event()
        self._running = True
        self._last_telemetry_time = -1e9
        self.last_telemetry: Optional[dict[str, Any]] = None
        self._command: Optional[DriveCommand] = None
        self._command_time = -1e9
        self._seq = 0
        self._send_lock = threading.Lock()
        self._thread = threading.Thread(target=self._control_loop, name="robot-link", daemon=True)
        self._thread.start()
        self._sender = threading.Thread(target=self._send_loop, name="robot-commands", daemon=True)
        self._sender.start()

    # ---------------------------------------------------------------- status

    @property
    def host(self) -> str:
        return self._host

    @property
    def robot_ip(self) -> Optional[str]:
        return self._robot_ip

    @property
    def telemetry_alive(self) -> bool:
        return time.monotonic() - self._last_telemetry_time < self.TELEMETRY_TIMEOUT_S

    @property
    def threads_alive(self) -> bool:
        """False if a background thread has stopped, so this link can no longer connect."""
        return self._thread.is_alive() and self._sender.is_alive()

    @property
    def control_connected(self) -> bool:
        with self._lock:
            return self._tcp is not None

    # ------------------------------------------------------------- commands

    def set_host(self, host: str) -> None:
        """Connect to ``host``. Calling it with the current host reconnects right away."""
        host = host.strip()
        if not host:
            return
        self._host = host
        self._robot_ip = None
        self._host_changed.set()
        with self._lock:
            if self._tcp is not None:
                try:
                    self._tcp.shutdown(socket.SHUT_RDWR)  # wakes the reader so it reconnects
                except OSError:
                    pass

    def set_command(self, command: DriveCommand) -> None:
        """The command to keep sending. Its ``seq`` is ignored; the link numbers what it sends."""
        with self._send_lock:
            self._command, self._command_time = command, time.monotonic()

    def send_now(self, command: DriveCommand) -> None:
        """Send one command immediately (used when closing, so "disabled" goes out before the link does)."""
        self.set_command(command)
        self._transmit(command)

    def _transmit(self, command: DriveCommand) -> None:
        robot_ip = self._robot_ip
        if robot_ip is None:
            return
        with self._send_lock:
            self._seq += 1
            numbered = dataclasses.replace(command, seq=self._seq)
        try:
            self._udp.sendto(encode(numbered.to_message()), (robot_ip, self._udp_port))
        except OSError:
            pass

    def _send_loop(self) -> None:
        next_send = time.monotonic()
        while self._running:
            with self._send_lock:
                command, age = self._command, time.monotonic() - self._command_time
            if command is not None and age < self.STALE_COMMAND_S:
                try:
                    self._transmit(command)
                except Exception:   # noqa: BLE001 - a dead sender would leave the robot without commands
                    log.exception("Sending a drive command failed")
            next_send += self.COMMAND_INTERVAL_S
            delay = next_send - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_send = time.monotonic()  # fell behind: do not burst to catch up

    def send_control(self, msg: dict[str, Any]) -> bool:
        """Send on the reliable channel. Returns False if not connected."""
        with self._lock:
            sock = self._tcp
        if sock is None:
            return False
        try:
            sock.sendall(encode_line(msg))
            return True
        except OSError:
            return False

    def poll(self) -> list[dict[str, Any]]:
        """Every message received since the last call: telemetry, control messages and link events."""
        messages = []
        while True:
            try:
                data, (source_ip, _) = self._udp.recvfrom(MAX_DATAGRAM_BYTES)
            except BlockingIOError:
                break
            except ConnectionResetError:
                continue  # Windows: an earlier command found nobody listening
            except OSError:
                break
            msg = decode(data)
            if msg is None or msg["type"] != MsgType.TELEMETRY or source_ip != self._robot_ip:
                continue
            self._last_telemetry_time = time.monotonic()
            self.last_telemetry = msg
            messages.append(msg)
        while True:
            try:
                messages.append(self._inbox.get_nowait())
            except queue.Empty:
                break
        return messages

    def close(self) -> None:
        self._running = False
        self._host_changed.set()
        with self._lock:
            if self._tcp is not None:
                try:
                    self._tcp.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        self._thread.join(timeout=2.0)
        self._sender.join(timeout=1.0)
        self._udp.close()

    # ------------------------------------------------------- background loop

    def _event(self, event: str, message: str) -> None:
        self._inbox.put({"type": LINK_EVENT, "event": event, "message": message})

    def _control_loop(self) -> None:
        """Keeps the control connection up. An unexpected error is logged and the loop carries on:
        if this thread died, Connect would do nothing until the station was restarted."""
        while self._running:
            try:
                self._connect_and_read()
            except Exception as exc:   # noqa: BLE001 - keep the link alive whatever went wrong
                log.exception("Robot link error")
                with self._lock:
                    self._tcp = None
                self._event("error", f"Robot link error: {exc!r}; retrying")
                self._host_changed.wait(self.RECONNECT_DELAY_S)

    def _connect_and_read(self) -> None:
        last_problem = ""
        while self._running:
            self._host_changed.clear()
            host = self._host
            try:
                robot_ip = socket.getaddrinfo(host, self._tcp_port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
            except OSError:
                problem = f"Cannot find '{host}' on the network"
                if problem != last_problem:
                    self._event("error", problem)
                    last_problem = problem
                self._host_changed.wait(self.RECONNECT_DELAY_S)
                continue
            self._robot_ip = robot_ip

            try:
                sock = socket.create_connection((robot_ip, self._tcp_port), timeout=2.0)
            except OSError:
                problem = f"Robot at {robot_ip} is not answering on port {self._tcp_port}"
                if problem != last_problem:
                    self._event("error", problem)
                    last_problem = problem
                self._host_changed.wait(self.RECONNECT_DELAY_S)
                continue

            last_problem = ""
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(0.5)
            with self._lock:
                self._tcp = sock
            self._event("connected", f"Control link connected to {host} ({robot_ip}:{self._tcp_port})")
            self._read_until_closed(sock)
            with self._lock:
                self._tcp = None
            sock.close()
            if self._running:
                self._event("disconnected", "Control link closed")
                self._host_changed.wait(self.RECONNECT_DELAY_S)

    def _read_until_closed(self, sock: socket.socket) -> None:
        buffer = LineBuffer()
        while self._running and not self._host_changed.is_set():
            try:
                data = sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            if not data:
                return
            for msg in buffer.feed(data):
                self._inbox.put(msg)
