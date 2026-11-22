# Differential Swerve Chassis

Everything for my driver station and robot code for my custom-designed differential swerve chassis.

The robot is a four-module differential swerve. Each module has two 280 motors that drive *and* steer
the wheel together: spin both motors the same way at the same speed and the wheel rolls without
changing its steering angle, spin them opposite ways and it steers. An Orange Pi 4 Pro on the robot
runs the whole control loop, and my Windows laptop runs a (dark mode!) driver station that reads my
Xbox controller and talks to the Pi over Wi-Fi.

A few things about the hardware that matter for the code:

- **Drive gearing:** 16t to 112t, then 92t to 16t on a second stage, so 28:23 overall.
- **Steer gearing:** 16t to 112t, a 7:1 reduction.
- **Encoders:** one MT6701 per module, geared 2:1 off the steering (90t on the wheel, 45t on the
  encoder). That means it can't tell 0° from 180° at start-up, so every wheel has to be within ±90° of
  zero when the robot turns on (more on that under [Driving](#driving)).
- **No drive encoders**, so steering is closed-loop (PID on the encoder angle) and driving is open-loop.
- **Motor controllers:** four AT8236 dual H-bridges. The important thing to remember is that each
  H-bridge runs two motors on neighboring sides of *different* modules, not both motors of one module.

## What's in here

```
main.py                 launcher: `python main.py robot` / `python main.py station`
common/                 shared by both sides
  config.py             config schema, defaults (from the wiring sheets) and validation
  protocol.py           UDP/TCP message format and protocol version
  timing.py             keeps Windows from throttling the control loops
robot/                  runs on the Orange Pi
  robot.py              200 Hz main loop, watchdog, modes, config updates
  swerve/               steering-angle tracking, differential mix, module, drivetrain, motor check
  hardware/             AT8236 motor channels, MT6701 encoders, MPU-6050 heading, simulator
  net.py                UDP command receiver + TCP control server
station/                runs on the laptop
  app.py                window, 50 Hz tick, safety rules
  views/                Drive, Mapping and Tuning tabs; robot view (electronics) and field view (motion)
  part_status.py        works out whether each part is connected and working
  gamepad.py            Xbox controller (pygame)
  keyboard.py           keyboard driving (W A S D / arrows, J L)
  link.py               network link to the robot; steady 50 Hz command sender
  simulator.py          the built-in simulator behind the Simulator connection mode
  windows.py            logging, crash reports, single instance, taskbar identity
pi_setup/               scripts that set up the Pi, rescue its SD card and push code to it
packaging/              Windows app build (PyInstaller spec, build script, installer script, icon)
tools/                  bring-up tools for the Pi, plus a link check
docs/                   Pi setup and recovery guide, and both wiring sheets
tests/                  pytest suite (runs on the laptop, no hardware needed)
```

## Robot frame and names

**Front is the side away from the Orange Pi.** The Pi sits at the rear, so it's at the bottom of the
robot view in the driver station. That's a quarter turn from wiring sheet E-01, so a few labels changed:

| Wiring sheet E-01 | Software |
|---|---|
| HB-F, HB-R, HB-B, HB-L | HB1, HB2, HB3, HB4 |
| ENC on I2C0, I2C1, I2C2, I2C3 | E1, E2, E3, E4 |
| FL module (M1, M8) | **BL** |
| FR module (M2, M3) | **FL** |
| BR module (M4, M5) | **FR** |
| BL module (M6, M7) | **BR** |

Motor labels M1–M8 and all the header pins stayed the same. +x is forward, +y is left, and angles are
counter-clockwise positive. A steering angle of 0° means the wheel points forward.

**Wiring, pin by pin:** [Swerve Pin Wiring, sheet E-02](https://claude.ai/artifact/Wmyj4Z3nRD5TiJ9mj6D8z9)
uses the software names above and shows every pin of each H-bridge, encoder and the MPU-6050, the
40-pin header map, and a schedule of every wire. Its pin numbers are the defaults in `common/config.py`.
Each H-bridge input pair (PWM + direction) sits on side-by-side header pins wherever the header allows,
so I can use crimped 2-pin connectors. Copies of both wiring sheets are in [`docs/`](docs/) (just open
them in a browser).

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

The simulator treats each module as an ideal differential, so the wheel headings and motion arrows
respond to the controller exactly how the real robot should once it's set up. It keeps its own settings
(zero offsets, mapping, tuning) in `%APPDATA%\Differential Swerve Driver Station\simulator_config.json`,
so nothing mixes with the real robot's. If a simulator is already running on the laptop (say one
started by hand with `main.py robot --sim`, or the **Simulator + driver station** launch configuration),
Simulator mode just uses that one.

`main.py station --host <address>` connects to a robot at that address for one session; pressing
Connect saves an address for next time.

## Setting up the Orange Pi

The full walkthrough is in **[docs/orange-pi.md](docs/orange-pi.md)**: preparing and flashing a new card
without a monitor, the setup scripts, everyday updates, what the LEDs mean, the power rules, and how to
figure out why a Pi won't boot and rescue its SD card. The short version:

1. **OS:** the prebuilt ARM64 wpimath needs **Python 3.11 or newer and glibc 2.35 or newer**. A Debian
   12 (Bookworm) or Ubuntu 24.04 image works. Ubuntu 22.04 ships Python 3.10, so it doesn't.
2. **Overlays:** enable `i2c0 i2c1 i2c2 i2c3` and `pwm0 pwm2 pwm3 pwm4 pwm5 pwm6 pwm7 spwm2`
   (`orangepi-config` or `/boot/orangepiEnv.txt`), then reboot.
3. **Packages and code:**
   ```bash
   sudo apt install i2c-tools gpiod python3-venv
   python3 -m venv venv && venv/bin/pip install -r requirements-robot.txt
   ```
4. **Check the hardware** (read-only, nothing moves):
   ```bash
   venv/bin/python -m tools.probe_hardware
   ```
   It lists every PWM chip, finds each direction pin, and reads every encoder. If a PWM chip number,
   GPIO line or I2C bus doesn't match the defaults, fix it in `robot_config.json` (written on the first
   run), or on the Mapping tab for I2C buses. The defaults come from the wiring sheet and the Orange Pi
   manual, but the Linux numbering depends on the board image, so trust the probe.
5. **Check the encoders:** `venv/bin/python -m tools.encoder_monitor`. Turning a wheel one full turn
   should change its angle by 360°.
6. **Check the IMU:** with the robot running and the driver station connected, keep the robot still for
   two seconds while the gyro calibrates, then turn it counter-clockwise by hand. The heading in the
   *Field-relative drive* panel should go up. If it goes down, tick *Invert heading* on the Mapping tab.
7. **Set the invert flags, wheels off the ground:**
   ```bash
   venv/bin/python -m tools.motor_test module FL
   ```
   It runs pure drive and then pure steer and tells you which flags to change. Do the same for FR, BL
   and BR, and set the flags on the Mapping tab. `motor_test motor M3` spins a single motor if you need it.
8. **Run:** `venv/bin/python main.py robot`, and point the driver station at the Pi's hostname or IP.

### How my Pi is set up

It runs the Orange Pi image `Orangepi4pro_1.0.8_debian_bookworm_desktop_xfce_linux6.6.98` with the
hostname **`orangepi4pro.local`** (the driver station's default address). The scripts in `pi_setup/` did
the rest:

- `setup.sh`: packages, the I2C/PWM overlays above, the robot's venv, boot to the text console, and an
  HDMI fix. This image's display driver turns HDMI off for good if the monitor drops its connection for
  a moment at start-up ("no signal"), and the fix in `pi_setup/hdmi-fix/`, from
  [CheezeCS/armbian-a733-gpu](https://github.com/CheezeCS/armbian-a733-gpu/blob/main/docs/hdmi.md) (MIT),
  turns it back on.
- `perms.sh`, `pwm_perms.sh`: let the `orangepi` user use the I2C buses, GPIO lines and PWM outputs
  without sudo.
- `finish.sh`: `avahi-daemon` for the `.local` name, and the **`swerve-robot`** service, which starts the
  robot program on boot (as `orangepi`, from `~/robot`) and restarts it if it stops. `orangepi` can
  start, stop and restart that one service without a password.

On this image `S-PWM` shows up as `pwmchip20`, and the GPIO lines don't have names, so pins like `PD1`
are opened by Allwinner numbering (bank × 32 + pin: `PD1` is line 97 on `gpiochip0`, `PL12` is line 12
on `gpiochip1`).

**Updating the code on the Pi** from my laptop (it keeps the Pi's `robot_config.json`, but always takes
the H-bridge pins from `common/config.py`):

```powershell
powershell -ExecutionPolicy Bypass -File pi_setup\sync.ps1
```

**Robot log:** `ssh orangepi@orangepi4pro.local journalctl -u swerve-robot -f`

## Driving

| Input | Action |
|---|---|
| Left stick | Drive: the robot goes wherever the stick points |
| Right stick (left/right) | Rotate the robot |
| − (View) | Swerve Set Zero: the current wheel angles become zero (saved on the Pi) |
| + (Menu) | Return to Zero: steer every wheel back to 0° |
| Space bar | Disable |

**Keyboard control:** turn on *Keyboard control* in the Joysticks panel to drive without a controller.
The keys light up on screen while you hold them. They go through the same sensitivity and deadzone
sliders as the sticks, and if a controller is plugged in too, held keys take over from the sticks.

| Keys | Action |
|---|---|
| W or ↑ / S or ↓ | Drive forward / back |
| A / D | Strafe left / right |
| J or ← / L or → | Turn left / right |

Keys never drive while you're typing in a text box (like the robot address or a number box). Click the
drawing or press Esc to drive again. When the window loses focus, every key counts as released.

**Field-relative drive:** with this on, pushing the left stick away from you drives the robot away from
you, whichever way it's facing, which is how I wanted it to work in the first place ("wherever it is
pointing the robot should go"). Turn it on in the *Field-relative drive* panel on the Drive tab. It
saves on the robot and works while driving.

- **"Forward" is away from the laptop.** The MPU-6050 measures turning but has no compass, so the robot
  can't know on its own which way the laptop is. You tell it: point the robot, pick which way it faces
  as seen from where you're standing (*Away*, *Left*, *Toward*, *Right*), and press **Set field
  forward**. At start-up the robot assumes it faces away from you.
- **Calibration:** the gyro measures its resting offset in the first two seconds after the robot program
  starts, so keep the robot still then. The panel says "calibrating" until it's done.
- **Drift:** the heading creeps slowly, a few degrees a minute. If forward starts to feel off, point the
  robot away from you and press **Set field forward** again.
- **The dial** in the top-right corner of the drawing shows "away from the laptop" as seen from the
  robot. The arrow points away from you and the dot marks your side.
- **Without a working IMU** (not found, calibrating, or not answering), the robot drives robot-relative
  and the panel tells you why.
- The simulator has a simulated gyro and turns the chassis as the wheels push it, so you can try
  field-relative drive there too.

**Zeroing:** before the very first run, line every wheel up straight by hand and press **−**. After
that, every wheel has to be within ±90° of zero at start-up (the 2:1 encoder gearing again). **Press +
before switching the robot off** so the wheels get parked at zero. The program also returns the wheels
to zero when it's stopped normally, but the rocker switch cuts power instantly, so don't count on it.

**Safety rules:**

- The robot only drives while the station says enabled and commands keep coming in. No command for
  250 ms disables it (the watchdog).
- Disabling, whether from the station, the space bar or a lost link, **brakes** every motor for 15
  seconds: the wheels slow down and the steering angles stay put. After that the motors are released so
  you can push the robot and turn the wheels by hand. With this gearing the braking is pretty gentle at
  speed, so expect a fast robot to take several seconds to stop (about half the distance it would coast).
- After start-up or a watchdog trip, the robot stays disabled until you enable again from the station,
  even if the link comes back with the station still set to enabled.
- The station can only enable with the robot connected and an input available (a controller, or
  keyboard control turned on). It disables itself if either goes away, if the robot disables itself, or
  when you switch between Simulator and Robot.
- Only one driver station drives at a time. A second one is ignored until the first has been quiet for
  a second.
- Swerve Set Zero and mapping changes only work while the robot is disabled. Tuning changes apply live.
- A module whose encoder stops answering coasts until it answers again, and gets skipped by Set Zero.
- The motor check (below) only runs while enabled with the sticks centered, and disabling stops it
  right away.

## Driver station tabs

- **Drive:** a top-down drawing with a **Robot | Field** switch in its top-right corner.
  - **Robot view:** the robot's own frame, with all the electronics and harnesses like on the wiring
    diagram. Wheels turn to the angle the Pi reports, the dashed line is each module's target angle,
    and the green arrow shows which way the Pi is rolling the wheel and how hard. Click any part for
    its role, wiring and live values.
  - **Field view:** the robot moving over a 0.5 m field grid, with "away from the driver station" at
    the top. It shows just the chassis, the wheels at their angle on the field, their motion vectors,
    and a trail of the path driven. Scroll to zoom from 2 to 20 m across. Position comes from the
    simulator; the real robot has no drive encoders, so it can't measure where it is, and the field view
    shows it at the center turning with its true heading. *Set field forward* starts a fresh field at
    the robot.

  The view you pick is remembered. Sliders with exact-value boxes set the sensitivity and deadzone for
  each stick, and the terminal shows everything the Pi sends (tick *Show telemetry* for the live data).
- **Mapping:** which motors, encoder and invert flags each module uses, which H-bridge channel each
  motor is plugged into, and which I2C bus each encoder is on.
- **Tuning:** steering PID, steer output limit, max wheel speed (up to 10 m/s), max turn rate,
  acceleration limit and more. Full turn stick asks for the max turn rate (360°/s by default), or for as
  much as the wheels can give if that's less. The gyro reads up to 2000°/s, so the limit stops at
  1440°/s.

**Everything saves as you change it**, there's no Apply button:

- Mapping and Tuning changes go straight to the robot, which applies them and writes
  `robot_config.json`. The status line under each tab confirms "Saved on the robot". Tuning applies
  live, even while driving. Mapping only works while the robot is disabled.
- A mapping edit that isn't valid yet (like a motor used twice halfway through swapping two) waits until
  it is. I2C bus paths save when you press Enter or click away.
- If the robot rejects a change, the tab goes back to whatever the robot has saved.
- Joystick sensitivity and deadzone save on the laptop right away, in
  `%APPDATA%\Differential Swerve Driver Station\settings.json`.

### Is everything connected?

Every part the robot can report on gets a status dot in the robot view: the Orange Pi, the IMU, all four
encoders, all four H-bridges and all eight motors. **Green** is working, **red** is not answering,
**amber** is partly working (or being checked right now), and **gray** means it isn't known yet. Click a
part and its panel says what's wrong and what to check. The *Robot control* card sums it all up in one
line, like "Encoders 4/4 · IMU ok · Motors 8/8".

- **Encoders and the IMU** are known live, since the Pi reads them every loop.
- **Motors and H-bridges** have no feedback wire to the Pi, so the only way to know they work is the
  **motor check**. Enable with the **wheels off the ground**, then press **Check motors** (it takes a
  second click to start, to make sure the wheels are up). Each motor spins on its own for under half a
  second with its partner braked, and the robot watches that module's encoder: if the steering turns,
  the motor, its leads and its H-bridge channel all work. The whole thing takes about 8 seconds. An
  H-bridge where *neither* channel turns its motor gets flagged as a power, VCC or wiring problem for
  that board.

## Windows app

The driver station builds into a normal Windows program:

```powershell
.\venv\Scripts\pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

The build runs the tests first. In VS Code you can also use **Terminal → Run Task → Build Windows app**.
What you get in `dist\`:

| File | Use |
|---|---|
| `Differential Swerve Driver Station\DriverStation.exe` | The app (about 70 MB with the built-in simulator). It needs the whole folder, since it carries its own Python. |
| `DifferentialSwerveDriverStation-<version>-portable.zip` | That folder zipped. Unzip anywhere and run `DriverStation.exe`. |
| `DifferentialSwerveDriverStation-<version>-setup.exe` | Installer with Start menu and desktop shortcuts and an uninstaller. Only built if [Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed. |

Good to know:

- **Windows Firewall:** the first time the app runs, Windows asks whether it can use the network. Allow
  it on private networks, or the robot's telemetry can't reach the laptop. Installing "for all users"
  with the installer adds the rule for you.
- **SmartScreen:** the app isn't code-signed, so Windows might warn you the first time. Click
  *More info → Run anyway*.
- **One copy at a time:** opening it again just brings the running window forward, since the robot only
  listens to one station anyway.
- **Logs** are in `%LOCALAPPDATA%\Differential Swerve Driver Station\logs\station.log`. If the app ever
  has to close on an error, it tells you and points there.
- **Version:** set `__version__` in `station/__init__.py` before building a release. It shows up in the
  window header, the file's properties and the installer name.
- The app takes `--host <address>` for a one-off connection, same as `main.py station`.

## How the control loop works

Every 5 ms, the Pi:

1. Reads the four encoders and unwraps them into continuous steering angles (÷2 for the gearing).
2. Takes the newest drive command and rate-limits it.
3. `kinematics.toSwerveModuleStates` turns forward/left/rotate into a speed and angle for each module,
   and `desaturateWheelSpeeds` scales all four down together if any would go over 100%.
4. Per module: keeps the last angle if the wheel is nearly stopped (so the wheels don't snap back to 0°),
   `optimize` (never turn more than 90°, reverse the wheel instead), `cosineScale`, then the steering PID
   gives a steer command.
5. Drive is open-loop since there are no drive encoders: drive = speed ÷ max speed.
6. Steer-first desaturation keeps |drive| + |steer| ≤ 1 by shrinking drive (never steer) on all four
   modules together.
7. Differential mix: motor A = drive + steer, motor B = drive − steer. Two equations, two unknowns,
   because each motor does both driving and steering.
8. Each motor's AT8236 gets PWM on IN1 for speed and a direction pin on IN2, with the duty inverted in
   reverse (the motor drives backwards while PWM is low).

Networking: UDP port 5800 carries drive commands (50 Hz) and telemetry (20 Hz), so a lost packet just
gets replaced by the next one. TCP port 5801 carries the configuration, configuration changes and the
Pi's log lines, which all need to arrive reliably.

## Still to do

- **Measure** the max wheel speed (Tuning tab). The wheel centers are set to 110 mm from the robot's
  center in x and y (`geometry.module_offset_m` in `robot_config.json`), from the CAD.
- **Tune** the steering PID on the real robot (the order is listed on the Tuning tab).
- **Run the motor check** on the real robot once it's wired back up.
