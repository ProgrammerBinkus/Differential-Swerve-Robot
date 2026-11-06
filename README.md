# Differential Swerve Chassis

Control software for a four-module differential swerve robot: an Orange Pi 4 Pro on the robot runs the
control loop, and a Windows laptop runs a dark-mode driver station that reads an Xbox controller.

```
main.py                 launcher: `python main.py robot` / `python main.py station`
common/                 shared by both sides
  config.py             config schema, defaults (from wiring sheet E-01) and validation
  protocol.py           UDP/TCP message format and protocol version
  timing.py             keeps Windows from throttling the control loops
robot/                  runs on the Orange Pi
  robot.py              200 Hz main loop, watchdog, modes, config updates
  swerve/               steering-angle tracking, differential mix, module, drivetrain
  hardware/             AT8236 motor channels, MT6701 encoders, MPU-6050 heading, simulator
  net.py                UDP command receiver + TCP control server
station/                runs on the laptop
  app.py                window, 50 Hz tick, safety rules
  views/                Drive, Mapping and Tuning tabs; robot view (electronics) and field view (motion)
  gamepad.py            Xbox controller (pygame)
  keyboard.py           keyboard driving (W A S D / arrows, J L)
  link.py               network link to the robot; steady 50 Hz command sender
  simulator.py          the built-in simulator behind the Simulator connection mode
  windows.py            logging, crash reports, single instance, taskbar identity
packaging/              Windows app build (PyInstaller spec, build script, installer script, icon)
tools/                  bring-up tools for the Pi
tests/                  pytest suite (runs on the laptop, no hardware)
```

## Robot frame and names

**Front is the side away from the Orange Pi.** The Pi is at the rear, shown at the bottom of the driver
station's robot view. This is a quarter turn from wiring sheet E-01, so labels changed:

| Wiring sheet E-01 | Software |
|---|---|
| HB-F, HB-R, HB-B, HB-L | HB1, HB2, HB3, HB4 |
| ENC on I2C0, I2C1, I2C2, I2C3 | E1, E2, E3, E4 |
| FL module (M1, M8) | **BL** |
| FR module (M2, M3) | **FL** |
| BR module (M4, M5) | **FR** |
| BL module (M6, M7) | **BR** |

Motor labels M1–M8 and all header pins are unchanged. +x is forward, +y is left, and angles are
counter-clockwise positive. A steering angle of 0° means the wheel points forward.

## Try it on the laptop (no robot needed)

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements-dev.txt
.\venv\Scripts\python -m pytest
```

Then start the driver station and pick **Simulator** in the *Connection* switch at the top. It starts
a built-in simulator by itself and stops it when you switch back to **Robot** or close the app:

```powershell
.\venv\Scripts\python main.py station
```

The built-in simulator keeps its own settings (zero offsets, mapping, tuning) in
`%APPDATA%\Differential Swerve Driver Station\simulator_config.json`, separate from the real robot's.
If a simulator is already running on the laptop, for example one started by hand with
`main.py robot --sim` or the **Simulator + driver station** launch configuration, Simulator mode uses
that one instead.

`main.py station --host <address>` connects to a robot at that address for one session; pressing
Connect saves an address for next time.

The simulator models each module as an ideal differential, so wheel headings and motion arrows
respond to the controller exactly as the real robot should once it is configured.

## Set up the Orange Pi

1. **OS:** the prebuilt ARM64 wpimath needs **Python 3.11 or newer and glibc 2.35 or newer**. A Debian
   12 (Bookworm) or Ubuntu 24.04 image works. Ubuntu 22.04 ships Python 3.10, which does not.
2. **Overlays:** enable `i2c0 i2c1 i2c2 i2c3` and `pwm0 pwm2 pwm3 pwm4 pwm5 pwm6 pwm7 spwm2`
   (`orangepi-config` or `/boot/orangepiEnv.txt`), then reboot.
3. **Packages and code:**
   ```bash
   sudo apt install i2c-tools gpiod python3-venv
   python3 -m venv venv && venv/bin/pip install -r requirements-robot.txt
   ```
4. **Check the hardware** (read-only):
   ```bash
   venv/bin/python -m tools.probe_hardware
   ```
   It lists every PWM chip, finds each direction pin by name, and reads every encoder. If a PWM chip
   number, GPIO line or I2C bus differs from the defaults, edit `robot_config.json` (written on first run)
   or the Mapping tab for I2C buses. The defaults come from the wiring sheet and the Orange Pi manual,
   but the Linux numbering is board-image specific, so trust the probe.
5. **Check the encoders:** `venv/bin/python -m tools.encoder_monitor`. Turning a wheel one full turn
   should change its angle by 360°.
6. **Check the IMU:** with the robot running and the driver station connected, keep the robot still for
   two seconds while the gyro calibrates, then turn it counter-clockwise by hand. The heading in the
   *Field-relative drive* panel should go up. If it goes down, tick *Invert heading* on the Mapping tab.
7. **Set the invert flags, wheels off the ground:**
   ```bash
   venv/bin/python -m tools.motor_test module FL
   ```
   It runs pure drive and then pure steer and tells you which flags to change. Repeat for FR, BL, BR and
   set the flags in the Mapping tab. `motor_test motor M3` spins a single motor if you need it.
8. **Run:** `venv/bin/python main.py robot`. Point the driver station at the Pi's hostname or IP.

To start on boot, a systemd unit along these lines works (adjust the paths):

```ini
[Unit]
Description=Differential swerve robot
After=network-online.target

[Service]
WorkingDirectory=/home/orangepi/Differential Swerve Chassis
ExecStart=/home/orangepi/Differential Swerve Chassis/venv/bin/python main.py robot
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## Driving

| Input | Action |
|---|---|
| Left stick | Drive: the robot moves wherever the stick points |
| Right stick (left/right) | Rotate the robot |
| − (View) | Swerve Set Zero: the current wheel angles become zero (saved on the Pi) |
| + (Menu) | Return to Zero: steer every wheel back to 0° |
| Space bar | Disable |

**Keyboard control:** turn on *Keyboard control* in the Joysticks panel to drive without a controller.
The keys light up on screen while you hold them. They go through the same sensitivity and deadzone
sliders as the sticks, and if a controller is also connected, held keys take over from the sticks.

| Keys | Action |
|---|---|
| W or ↑ / S or ↓ | Drive forward / back |
| A / D | Strafe left / right |
| J or ← / L or → | Turn left / right |

Keys never drive while you're typing in a text box, such as the robot address or a number box. Click
the drawing or press Esc to drive again. When the window loses focus, every key counts as released.

**Field-relative drive:** with it on, pushing the left stick away from you drives the robot away from
you, whichever way the robot is facing, as the outline asks ("wherever it is pointing the robot should
go"). Turn it on in the *Field-relative drive* panel on the Drive tab. It saves on the robot and works
while driving.

- **"Forward" is away from the laptop.** The MPU-6050 measures turning but has no compass, so the robot
  can't know on its own which way the laptop is. You tell it: point the robot, pick which way it faces
  as seen from where you stand at the laptop (*Away*, *Left*, *Toward*, *Right*), and press **Set field
  forward**. At start-up the robot assumes it faces away from you.
- **Calibration:** the gyro measures its resting offset in the first two seconds after the robot program
  starts, so keep the robot still then. The panel says "calibrating" until it's done.
- **Drift:** the heading creeps slowly, a few degrees a minute. If forward starts to feel off, point the
  robot away from you and press **Set field forward** again.
- **The dial** in the top-right corner of the drawing shows "away from the laptop" as seen from the
  robot. The arrow points away from you and the dot marks your side.
- **Without a working IMU** (not found, calibrating, or not answering), the robot drives robot-relative
  and the panel says why.
- The simulator has a simulated gyro and turns the chassis as the wheels push it, so field-relative drive
  can be tried there too.

Before the first run, line every wheel up straight by hand and press **−**. At every start-up after that,
each wheel must be within ±90° of zero (the encoder is geared 2:1, so it cannot tell 0° from 180°).
**Press + before switching the robot off** so the wheels are parked at zero. The program also returns
the wheels to zero when it is stopped normally, but the rocker switch cuts power instantly.

Safety rules:

- The robot only drives while the station says enabled and commands keep arriving. No command for
  250 ms disables it (watchdog).
- Disabling, whether from the station, the space bar or a lost link, **brakes** every motor for 15 seconds:
  the wheels slow down and the steering angles stay where they are. Then the motors are released, so you
  can push the robot and turn the wheels by hand. With this gearing the braking is gentle at speed:
  expect a fast robot to take several seconds to stop, about half the distance it would coast.
- After start-up or a watchdog trip the robot stays disabled until you enable again from the station,
  even if the link comes back with the station still set to enabled.
- The station can only enable with the robot connected and an input available (a controller, or
  keyboard control turned on). It disables itself if either goes away, if the robot disables itself, or
  when you switch between Simulator and Robot.
- Only one driver station drives at a time. A second one is ignored until the first has been silent
  for a second.
- Swerve Set Zero and mapping changes only work while the robot is disabled. Tuning changes apply live.
- A module whose encoder stops answering coasts until it answers again, and is skipped by Set Zero.

## Driver station tabs

- **Drive:** a top-down drawing with a **Robot | Field** switch in its top-right corner.
  - **Robot view:** the robot's own frame, with the electronics and harnesses. Wheels turn to the angle
    the Pi reports, the dashed line is each module's target angle, and the green arrow shows which way
    the Pi is rolling the wheel and how hard. Click any part for its role, wiring and live values.
  - **Field view:** the robot moving over a 0.5 m field grid, with "away from the driver station" at
    the top. It shows only the chassis, the wheels at their angle on the field, their motion vectors,
    and a trail of the path driven, without the electronics. Scroll to zoom from 2 to 20 m across.
    Position comes from the simulator. The real robot has no drive encoders, so it can't measure where
    it is; the field view then shows it at the center, turning with its true heading.
    *Set field forward* starts a fresh field at the robot.

  The view you pick is remembered. Sliders with exact-value boxes set
  sensitivity and deadzone for each stick. The terminal shows everything the Pi sends (tick
  *Show telemetry* for the live data stream).
- **Mapping:** which motors, encoder and invert flags each module uses, which H-bridge channel each
  motor is plugged into, and which I2C bus each encoder is on.
- **Tuning:** steering PID, steer output limit, max wheel speed, acceleration limit and more.

**Everything saves as you change it**, with no Apply button:

- Mapping and Tuning changes go straight to the robot, which applies them and writes
  `robot_config.json`. The status line under each tab confirms "Saved on the robot". Tuning applies
  live, even while driving. Mapping only works while the robot is disabled.
- A mapping edit that isn't valid yet, such as a motor used twice halfway through swapping two, waits
  until it is. I2C bus paths save when you press Enter or click away.
- If the robot rejects a change, the tab goes back to what the robot has saved.
- Joystick sensitivity and deadzone save on the laptop immediately, in
  `%APPDATA%\Differential Swerve Driver Station\settings.json`.

## Windows app

Build the driver station as a normal Windows program:

```powershell
.\venv\Scripts\pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

The build runs the tests first. In VS Code you can use **Terminal → Run Task → Build Windows app**
instead. The output in `dist\`:

| File | Use |
|---|---|
| `Differential Swerve Driver Station\DriverStation.exe` | The app (about 70 MB with the built-in simulator). The whole folder is needed; it carries its own Python. |
| `DifferentialSwerveDriverStation-<version>-portable.zip` | That folder zipped. Unzip anywhere and run `DriverStation.exe`. |
| `DifferentialSwerveDriverStation-<version>-setup.exe` | Installer with Start menu and desktop shortcuts and an uninstaller. Built only if [Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed. |

Notes:

- **Windows Firewall:** the first time the app runs, Windows asks whether it may use the network.
  Allow it on private networks, or the robot's telemetry can't reach the laptop. Installing "for all
  users" with the installer adds the rule for you.
- **SmartScreen:** the app isn't code-signed, so Windows may warn on first launch. Click
  *More info → Run anyway*.
- **One copy at a time:** opening it again brings the running window forward, since the robot only
  obeys one station.
- **Logs** are in `%LOCALAPPDATA%\Differential Swerve Driver Station\logs\station.log`. If the app
  ever has to close on an error, it says so and points there.
- **Version:** set `__version__` in `station/__init__.py` before building a release. It appears in the
  window header, the file's properties and the installer name.
- The app accepts `--host <address>` for a one-off connection, the same as `main.py station`.

## How the control loop works

Each 5 ms loop on the Pi:

1. Read the four encoders and unwrap them into continuous steering angles (÷2 for the gearing).
2. Take the newest drive command. Rate-limit it.
3. `kinematics.toSwerveModuleStates` turns forward/left/rotate into a speed and angle per module;
   `desaturateWheelSpeeds` scales all four down together if any would exceed 100%.
4. Per module: keep the last angle if the wheel is nearly stopped, `optimize` (never turn more than
   90°; reverse instead), `cosineScale`, then the steering PID gives a steer command.
5. Drive is open-loop (no drive encoders): drive = speed ÷ max speed.
6. Steer-first desaturation keeps |drive| + |steer| ≤ 1 by shrinking drive on all four modules together.
7. Differential mix: motor A = drive + steer, motor B = drive − steer.
8. Each motor's AT8236 gets PWM on IN1 and direction on IN2, with the duty inverted in reverse.

Networking: UDP port 5800 carries drive commands (50 Hz) and telemetry (20 Hz); TCP port 5801 carries
the configuration, configuration changes and the Pi's log lines.

## Still to do

- **Measure:** max wheel speed (Tuning tab) and `geometry.module_offset_m` in `robot_config.json`.
- **Tune** the steering PID on the real robot (order is listed on the Tuning tab).
