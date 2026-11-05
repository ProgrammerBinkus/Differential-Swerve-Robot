"""Station side of the network link to the robot."""

from __future__ import annotations

import queue
import socket
import threading
import time
from typing import Any, Optional

from common.protocol import (
    MAX_DATAGRAM_BYTES, TCP_PORT, UDP_PORT, DriveCommand, LineBuffer, MsgType, decode, encode,
    encode_line, open_udp_socket,
)

# Messages the link itself generates for the UI (never sent over the network).
LINK_EVENT = "_link"


class RobotLink:
    """UDP drive commands and telemetry, plus a TCP control connection that reconnects by itself.

    All network waiting happens on a background thread. The UI thread calls
    :meth:`poll` every tick to collect received messages, so Tk widgets are
    only ever touched from the UI thread.
    """

    TELEMETRY_TIMEOUT_S = 0.5
    RECONNECT_DELAY_S = 1.5

    def __init__(self, host: str) -> None:
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
        self._thread = threading.Thread(target=self._control_loop, name="robot-link", daemon=True)
        self._thread.start()

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

    def send_command(self, command: DriveCommand) -> None:
        robot_ip = self._robot_ip
        if robot_ip is None:
            return
        try:
            self._udp.sendto(encode(command.to_message()), (robot_ip, UDP_PORT))
        except OSError:
            pass

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
        self._udp.close()

    # ------------------------------------------------------- background loop

    def _event(self, event: str, message: str) -> None:
        self._inbox.put({"type": LINK_EVENT, "event": event, "message": message})

    def _control_loop(self) -> None:
        last_problem = ""
        while self._running:
            self._host_changed.clear()
            host = self._host
            try:
                robot_ip = socket.getaddrinfo(host, TCP_PORT, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
            except OSError:
                problem = f"Cannot find '{host}' on the network"
                if problem != last_problem:
                    self._event("error", problem)
                    last_problem = problem
                self._host_changed.wait(self.RECONNECT_DELAY_S)
                continue
            self._robot_ip = robot_ip

            try:
                sock = socket.create_connection((robot_ip, TCP_PORT), timeout=2.0)
            except OSError:
                problem = f"Robot at {robot_ip} is not answering on port {TCP_PORT}"
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
            self._event("connected", f"Control link connected to {host} ({robot_ip}:{TCP_PORT})")
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
