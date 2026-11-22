"""Wire protocol between the driver station and the robot.

Two channels are used:

* **UDP, port 5800** - the station sends a :class:`DriveCommand` 50 times a
  second and the robot answers with telemetry 20 times a second. A lost
  datagram is simply replaced by the next one, so a Wi-Fi hiccup never causes a
  burst of stale commands.
* **TCP, port 5801** - a reliable control channel carrying newline-delimited
  JSON: the robot's configuration, configuration changes, request results and
  the robot's log lines.

Every message is a JSON object with a ``"type"`` field (see :class:`MsgType`).
"""

from __future__ import annotations

import json
import math
import socket
from dataclasses import asdict, dataclass
from typing import Any, Optional

UDP_PORT = 5800
TCP_PORT = 5801

# Bump when messages or the config change in a way the other side must know about.
# The robot sends it with its config; the station warns when it differs (update both to the same version).
PROTOCOL_VERSION = 5

COMMAND_RATE_HZ = 50
TELEMETRY_RATE_HZ = 20
MAX_DATAGRAM_BYTES = 8192


class MsgType:
    """Values of the ``"type"`` field."""

    COMMAND = "cmd"              # station -> robot (UDP)
    TELEMETRY = "telemetry"      # robot -> station (UDP)
    GET_CONFIG = "get_config"    # station -> robot (TCP)
    SET_CONFIG = "set_config"    # station -> robot (TCP): partial update
    SET_FIELD_FORWARD = "set_field_forward"  # station -> robot (TCP): {"facing_deg": 0 | 90 | 180 | -90}
    CHECK_MOTORS = "check_motors"  # station -> robot (TCP): spin each motor alone and watch its encoder
    CONFIG = "config"            # robot -> station (TCP): full current config
    RESULT = "result"            # robot -> station (TCP): outcome of a request
    LOG = "log"                  # robot -> station (TCP): one log record


def encode(msg: dict[str, Any]) -> bytes:
    """Serialize a message to compact JSON bytes."""
    return json.dumps(msg, separators=(",", ":")).encode("utf-8")


def encode_line(msg: dict[str, Any]) -> bytes:
    """Serialize a message for the TCP channel (one JSON object per line)."""
    return encode(msg) + b"\n"


def decode(data: bytes) -> Optional[dict[str, Any]]:
    """Parse one message. Returns ``None`` for anything that is not a valid message."""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
        return None
    return msg


class LineBuffer:
    """Reassembles newline-delimited messages from a TCP byte stream."""

    MAX_PENDING_BYTES = 1 << 20

    def __init__(self) -> None:
        self._pending = bytearray()

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        """Add received bytes and return every complete message they finish."""
        self._pending.extend(data)
        messages = []
        while True:
            newline = self._pending.find(b"\n")
            if newline < 0:
                break
            line = bytes(self._pending[:newline])
            del self._pending[: newline + 1]
            msg = decode(line)
            if msg is not None:
                messages.append(msg)
        if len(self._pending) > self.MAX_PENDING_BYTES:
            self._pending.clear()  # a peer that never sends a newline is not speaking our protocol
        return messages


def _whole(value: Any) -> int:
    """A JSON integer. Floats, strings and booleans are rejected."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"expected an integer, got {value!r}")
    return value


def _unit(value: Any) -> float:
    """Convert to a float in [-1, 1]; non-finite values become 0."""
    number = float(value)
    if not math.isfinite(number):
        return 0.0
    return max(-1.0, min(1.0, number))


@dataclass
class DriveCommand:
    """What the driver wants right now, sent station -> robot over UDP.

    Velocities are fractions of the robot's maximum (-1 to 1) in the robot
    frame: +vx forward (away from the Orange Pi), +vy left, +omega
    counter-clockwise. The robot scales them by its measured top speed.

    Button presses are sent as counters that go up by one per press, so a
    single lost datagram cannot swallow a press.
    """

    seq: int = 0
    enabled: bool = False
    vx: float = 0.0
    vy: float = 0.0
    omega: float = 0.0
    zero_presses: int = 0   # "Swerve Set Zero" (controller "-" / View button)
    home_presses: int = 0   # "Return to Zero" (controller "+" / Menu button)

    def to_message(self) -> dict[str, Any]:
        return {"type": MsgType.COMMAND, **asdict(self)}

    @classmethod
    def from_message(cls, msg: dict[str, Any]) -> Optional["DriveCommand"]:
        """Build a command from a decoded message, or ``None`` if it is malformed."""
        if msg.get("type") != MsgType.COMMAND:
            return None
        try:
            return cls(
                seq=_whole(msg["seq"]),
                enabled=msg["enabled"] is True,  # only a real JSON true enables; "false" must not
                vx=_unit(msg["vx"]),
                vy=_unit(msg["vy"]),
                omega=_unit(msg["omega"]),
                zero_presses=_whole(msg["zero_presses"]),
                home_presses=_whole(msg["home_presses"]),
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return None


def open_udp_socket(port: int = 0) -> socket.socket:
    """Open a non-blocking UDP socket bound to ``port`` (0 picks a free port).

    On Windows, a datagram sent while the other side is not running makes the
    next receive raise ``ConnectionResetError``. Callers treat that as "no data".
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", port))
    sock.setblocking(False)
    return sock
