"""Robot side of the network link: UDP commands/telemetry and the TCP control server."""

from __future__ import annotations

import logging
import queue
import socket
import threading
from dataclasses import dataclass
from typing import Any, Optional

from common.protocol import (
    MAX_DATAGRAM_BYTES, TCP_PORT, UDP_PORT, DriveCommand, LineBuffer, MsgType, decode, encode,
    encode_line, open_udp_socket,
)

log = logging.getLogger(__name__)


class CommandReceiver:
    """Receives drive commands over UDP and sends telemetry back to the sender.

    Never blocks: :meth:`poll` drains whatever has arrived and returns only the
    newest command.
    """

    # A sequence number this far behind the last one means the station restarted.
    _RESTART_GAP = 1000

    def __init__(self, port: int = UDP_PORT) -> None:
        self._sock = open_udp_socket(port)
        self._peer: Optional[tuple[str, int]] = None
        self._last_seq: Optional[int] = None

    @property
    def peer(self) -> Optional[tuple[str, int]]:
        return self._peer

    def poll(self) -> Optional[DriveCommand]:
        newest = None
        while True:
            try:
                data, address = self._sock.recvfrom(MAX_DATAGRAM_BYTES)
            except BlockingIOError:
                return newest
            except (ConnectionResetError, OSError):
                continue
            msg = decode(data)
            command = DriveCommand.from_message(msg) if msg else None
            if command is None:
                continue
            stale = (address == self._peer and self._last_seq is not None
                     and 0 < self._last_seq - command.seq < self._RESTART_GAP)
            if stale:
                continue  # arrived out of order behind a newer command
            if address != self._peer:
                log.info("Driver station at %s:%d", *address)
            self._peer, self._last_seq = address, command.seq
            newest = command

    def send_telemetry(self, msg: dict[str, Any]) -> None:
        if self._peer is None:
            return
        try:
            self._sock.sendto(encode(msg), self._peer)
        except OSError:
            pass  # the station may have gone away; the watchdog handles it

    def close(self) -> None:
        self._sock.close()


class _Client:
    """One connected driver station. Outgoing messages go through a queue so a
    slow network can never stall the control loop."""

    def __init__(self, sock: socket.socket, address: tuple[str, int]) -> None:
        self.sock = sock
        self.address = address
        self.outbox: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=1000)
        self.alive = True

    def send(self, msg: dict[str, Any]) -> None:
        if not self.alive:
            return
        try:
            self.outbox.put_nowait(encode_line(msg))
        except queue.Full:
            pass  # drop rather than block; the station re-requests config on reconnect

    def close(self) -> None:
        if self.alive:
            self.alive = False
            self.outbox.put(None)
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()


@dataclass
class ControlEvent:
    client: _Client
    msg: dict[str, Any]


class ControlServer:
    """TCP server for the reliable control channel.

    Incoming messages land in :attr:`inbox` as :class:`ControlEvent` items for
    the control loop to handle. A new connection produces a ``"_connected"``
    event so the loop can send the current configuration.
    """

    CONNECTED = "_connected"

    def __init__(self, port: int = TCP_PORT) -> None:
        self.inbox: "queue.Queue[ControlEvent]" = queue.Queue()
        self._clients: set[_Client] = set()
        self._lock = threading.Lock()
        self._running = True
        self._server = socket.create_server(("", port))
        self._server.settimeout(0.5)
        threading.Thread(target=self._accept_loop, name="control-accept", daemon=True).start()

    def broadcast(self, msg: dict[str, Any]) -> None:
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            client.send(msg)

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def close(self) -> None:
        self._running = False
        self._server.close()
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            client.close()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                sock, address = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                return  # server socket closed
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            client = _Client(sock, address)
            with self._lock:
                self._clients.add(client)
            log.info("Control link connected from %s:%d", *address)
            threading.Thread(target=self._read_loop, args=(client,), name="control-read", daemon=True).start()
            threading.Thread(target=self._write_loop, args=(client,), name="control-write", daemon=True).start()
            self.inbox.put(ControlEvent(client, {"type": self.CONNECTED}))

    def _read_loop(self, client: _Client) -> None:
        buffer = LineBuffer()
        try:
            while client.alive:
                data = client.sock.recv(65536)
                if not data:
                    break
                for msg in buffer.feed(data):
                    self.inbox.put(ControlEvent(client, msg))
        except OSError:
            pass
        finally:
            self._drop(client)

    def _write_loop(self, client: _Client) -> None:
        try:
            while True:
                data = client.outbox.get()
                if data is None:
                    return
                client.sock.sendall(data)
        except OSError:
            self._drop(client)

    def _drop(self, client: _Client) -> None:
        with self._lock:
            known = client in self._clients
            self._clients.discard(client)
        client.close()
        if known:
            log.info("Control link from %s:%d closed", *client.address)


class BroadcastLogHandler(logging.Handler):
    """Forwards log records to every connected driver station (its terminal pane)."""

    def __init__(self, server: ControlServer, level: int = logging.INFO) -> None:
        super().__init__(level)
        self._server = server

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._server.broadcast({
                "type": MsgType.LOG,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "time": record.created,
            })
        except Exception:
            self.handleError(record)
