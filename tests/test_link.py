"""RobotLink's command sender, against a local UDP socket standing in for the robot."""

import socket
import time

from common.protocol import DriveCommand, decode, open_udp_socket
from station.link import RobotLink


def unused_tcp_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def receive(sock, seconds):
    end, seqs = time.monotonic() + seconds, []
    while time.monotonic() < end:
        try:
            data, _ = sock.recvfrom(8192)
            seqs.append(decode(data)["seq"])
        except (BlockingIOError, ConnectionResetError):
            time.sleep(0.002)
    return seqs


def test_sends_steadily_and_stops_when_the_ui_goes_quiet():
    robot = open_udp_socket(0)
    link = RobotLink("127.0.0.1", udp_port=robot.getsockname()[1], tcp_port=unused_tcp_port())
    link.STALE_COMMAND_S = 0.3
    try:
        deadline = time.monotonic() + 3
        while link.robot_ip is None and time.monotonic() < deadline:
            time.sleep(0.01)
        link.set_command(DriveCommand(enabled=False))
        seqs = receive(robot, 0.25)
        assert len(seqs) >= 8, seqs                     # about 50 Hz
        assert seqs == sorted(set(seqs))               # numbered by the link, always increasing
        time.sleep(0.4)                                # the UI stopped calling set_command (hung)
        receive(robot, 0.05)                           # drain anything already in flight
        assert receive(robot, 0.3) == []
    finally:
        link.close()
        robot.close()
