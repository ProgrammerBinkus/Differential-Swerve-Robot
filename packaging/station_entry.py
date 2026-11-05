"""Entry point of the packaged driver station (DriverStation.exe).

``DriverStation.exe --run-simulator --config <file>`` runs the bundled robot
simulator instead; the station starts it that way in Simulator mode.
"""

import sys

from station.simulator import RUN_SIMULATOR_FLAG

if RUN_SIMULATOR_FLAG in sys.argv[1:]:
    from robot.__main__ import main as run_simulator

    args = [arg for arg in sys.argv[1:] if arg != RUN_SIMULATOR_FLAG]
    raise SystemExit(run_simulator(["--sim", *args]))

from station.__main__ import main  # noqa: E402

raise SystemExit(main())
