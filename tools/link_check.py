"""Talk to the robot program over the network the way the driver station does, and check the link.

    python -m tools.link_check orangepi4pro.local          # the real robot (wheels off the ground)
    python -m tools.link_check orangepi4pro.local --sim    # the robot program started with --sim

Checks the TCP control channel (5801), that the robot sends its config with a matching protocol
version, that UDP telemetry (5800) gets through the Windows firewall, that the robot stays disabled
while told to, and the control loop's timing. With --sim it also enables the robot and drives forward.
Exits 0 when every check passes.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time

from common.config import default_config
from common.protocol import (PROTOCOL_VERSION, TCP_PORT, UDP_PORT, DriveCommand, LineBuffer, decode,
                             encode, encode_line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("host", help="robot hostname or IP, e.g. orangepi4pro.local")
    parser.add_argument("--sim", action="store_true", help="the robot program runs in simulation")
    args = parser.parse_args()
    host = args.host

    results: list[bool] = []

    def check(name: str, ok: bool, detail: object = "") -> None:
        results.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + name + (f"   [{detail}]" if detail != "" else ""))

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("0.0.0.0", 0))
    udp.settimeout(0.02)
    t0 = time.perf_counter()
    tcp = socket.create_connection((host, TCP_PORT), timeout=5)
    tcp.settimeout(0.05)
    check("TCP control channel connects", True, f"{(time.perf_counter() - t0) * 1000:.0f} ms")
    lines, inbox, telemetry, seq, count = LineBuffer(), [], {}, [0], [0]

    def pump(seconds: float, **cmd) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            seq[0] += 1
            udp.sendto(encode(DriveCommand(seq=seq[0], **cmd).to_message()), (host, UDP_PORT))
            try:
                while True:
                    msg = decode(udp.recvfrom(65536)[0])
                    if msg:
                        count[0] += 1
                        telemetry.clear()
                        telemetry.update(msg)
            except (socket.timeout, ConnectionResetError):
                pass
            try:
                inbox.extend(lines.feed(tcp.recv(65536)))
            except socket.timeout:
                pass

    pump(1.0, enabled=False)
    config = next((m for m in inbox if m.get("type") == "config"), None)
    check("robot sends its config", config is not None)
    check("protocol versions match", bool(config) and config.get("protocol") == PROTOCOL_VERSION,
          config and config.get("protocol"))
    if config:
        same = config["config"]["hbridges"] == default_config()["hbridges"]
        check("robot's H-bridge pins match common/config.py (else run pi_setup\\sync.ps1)", same)
    check("telemetry arrives over UDP (Windows firewall lets it in)", count[0] > 5, f"{count[0]} packets in 1 s")
    check("simulated" if args.sim else "real hardware", telemetry.get("simulated", False) == args.sim,
          telemetry.get("simulated"))

    tcp.sendall(encode_line({"type": "ping", "tag": 7, "t": time.time()}))
    pump(2.0, enabled=False)
    check("robot disabled while the station says disabled", telemetry.get("mode") == "disabled", telemetry.get("mode"))
    check("loop timing healthy", telemetry.get("loop_ms_max", 99) < 5.0, telemetry.get("loop_ms_max"))
    if args.sim:
        pump(0.3, enabled=True)
        pump(1.5, enabled=True, vx=0.5)
        check("enables and drives", telemetry.get("mode") == "drive"
              and (telemetry.get("pose") or {}).get("x", 0) > 0.2, (telemetry.get("mode"), telemetry.get("pose")))
    else:
        mods = telemetry.get("modules", {})
        print("info encoder faults:", {k: v["fault"] for k, v in mods.items()})
        print("info IMU:", telemetry.get("imu"))
    pump(0.5, enabled=False)
    print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
