import math

from common.protocol import DriveCommand, LineBuffer, decode, encode, encode_line


def test_command_round_trip():
    command = DriveCommand(seq=7, enabled=True, vx=0.5, vy=-0.25, omega=0.1, zero_presses=2, home_presses=3)
    assert DriveCommand.from_message(decode(encode(command.to_message()))) == command


def test_command_values_are_clamped_and_sanitized():
    msg = DriveCommand(seq=1).to_message()
    msg.update(vx=5.0, vy=-9.0, omega=math.nan)
    command = DriveCommand.from_message(msg)
    assert (command.vx, command.vy, command.omega) == (1.0, -1.0, 0.0)


def test_malformed_messages_are_rejected():
    assert decode(b"not json") is None
    assert decode(b"[1, 2]") is None
    assert decode(b'{"no_type": 1}') is None
    assert DriveCommand.from_message({"type": "cmd", "seq": 1}) is None
    assert DriveCommand.from_message({"type": "telemetry"}) is None


def test_line_buffer_reassembles_split_messages():
    buffer = LineBuffer()
    data = encode_line({"type": "a"}) + encode_line({"type": "b"})
    assert buffer.feed(data[:5]) == []
    assert [m["type"] for m in buffer.feed(data[5:])] == ["a", "b"]
