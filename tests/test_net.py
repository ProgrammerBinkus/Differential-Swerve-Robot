"""CommandReceiver over real UDP on localhost (ephemeral port, so it never clashes with a running robot)."""

import socket
import time

import pytest

from common.protocol import DriveCommand, encode, open_udp_socket
from robot.net import CommandReceiver


@pytest.fixture
def receiver():
    rx = CommandReceiver(port=0)
    yield rx
    rx.close()


def send(sock: socket.socket, rx: CommandReceiver, **fields) -> None:
    sock.sendto(encode(DriveCommand(**fields).to_message()), ("127.0.0.1", rx.port))


def poll(rx: CommandReceiver, now: float):
    for _ in range(50):  # give the datagram a moment to arrive
        command = rx.poll(now)
        if command is not None:
            return command
        time.sleep(0.005)
    return None


def test_newest_command_wins_and_old_ones_are_dropped(receiver):
    station = open_udp_socket()
    send(station, receiver, seq=5, vx=0.5)
    assert poll(receiver, 0.0).seq == 5
    send(station, receiver, seq=4, vx=-1.0)  # arrives late
    assert poll(receiver, 0.1) is None
    station.close()


def test_second_station_is_ignored_while_the_first_is_active(receiver):
    first, second = open_udp_socket(), open_udp_socket()
    send(first, receiver, seq=1)
    assert poll(receiver, 0.0) is not None
    send(second, receiver, seq=1, enabled=True, vx=1.0)
    assert poll(receiver, 0.5) is None
    # Once the first station has been silent long enough, the second may take over.
    send(second, receiver, seq=2, enabled=True)
    assert poll(receiver, 0.5 + CommandReceiver.PEER_TIMEOUT_S + 0.1).seq == 2
    first.close()
    second.close()
