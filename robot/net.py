"""Robot side of the network link: UDP commands/telemetry and the TCP control server."""

from __future__ import annotations

import logging
import math
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
    newest command. Only one driver station is obeyed at a time: commands from
    a second address are ignored until the current one has been silent for
    ``PEER_TIMEOUT_S`` (a restarted station gets a new port, so it takes over
    after that pause).
    """

    PEER_TIMEOUT_S = 1.0

    def __init__(self, port: int = UDP_PORT) -> None:
        self._sock = open_udp_socket(port)
        self._peer: Optional[tuple[str, int]] = None
        self._peer_seen = -math.inf
        self._last_seq: Optional[int] = None
        self._ignored: Optional[tuple[str, int]] = None

    @property
    def peer(self) -> Optional[tuple[str, int]]:
        return self._peer

    @property
    def port(self) -> int:
        return self._sock.getsockname()[1]

    def poll(self, now: float) -> Optional[DriveCommand]:
        newest = None
        while True:
            try:
                data, address = self._sock.recvfrom(MAX_DATAGRAM_BYTES)
            except BlockingIOError:
                return newest
            except ConnectionResetError:
                continue  # Windows: an earlier telemetry send found nobody listening
            except OSError as exc:
                log.error("Command socket error: %s", exc)
                return newest
            msg = decode(data)
            command = DriveCommand.from_message(msg) if msg else None
            if command is None:
                continue
            if address != self._peer:
                if now - self._peer_seen < self.PEER_TIMEOUT_S:
                    if address != self._ignored:
                        log.warning("Ignoring commands from %s:%d: already driven from %s:%d",
                                    *address, *self._peer)
                        self._ignored = address
                    continue
                log.info("Driver station at %s:%d", *address)
                self._peer, self._last_seq, self._ignored = address, None, None
            elif self._last_seq is not None and command.seq <= self._last_seq:
                continue  # duplicate, or arrived out of order behind a newer command
            self._last_seq, self._peer_seen = command.seq, now
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
        self._lock = threading.Lock()
        self._alive = True

    @property
    def alive(self) -> bool:
        return self._alive

    def send(self, msg: dict[str, Any]) -> None:
        if not self._alive:
            return
        try:
            self.outbox.put_nowait(encode_line(msg))
        except queue.Full:
            pass  # drop rather than block; the station gets the full config again on reconnect

    def close(self) -> None:
        """Safe to call from any thread, any number of times; never blocks."""
        with self._lock:
            if not self._alive:
                return
            self._alive = False
        try:
            self.outbox.put_nowait(None)  # wakes the writer; if the queue is full the closed socket stops it
        except queue.Full:
            pass
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
    def port(self) -> int:
        return self._server.getsockname()[1]

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
                if data is None or not client.alive:
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
