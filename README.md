# Differential Swerve Chassis

Control software for a four-module differential swerve robot: an Orange Pi 4 Pro on the robot runs the
control loop, and a Windows laptop runs a dark-mode driver station that reads an Xbox controller.

```
main.py                 launcher: `python main.py robot` / `python main.py station`
common/                 shared by both sides
  config.py             config schema, defaults (from wiring sheet E-01) and validation
  protocol.py           UDP/TCP message format
robot/                  runs on the Orange Pi
  robot.py              200 Hz main loop, watchdog, modes, config updates
  swerve/               steering-angle tracking, differential mix, module, drivetrain
  hardware/             AT8236 motor channels, MT6701 encoders, MPU-6050 stub, simulator
  net.py                UDP command receiver + TCP control server
station/                runs on the laptop
  app.py                window, 50 Hz tick, safety rules
  views/                Drive, Mapping and Tuning tabs, top-down robot view
  gamepad.py            Xbox controller (pygame)
  link.py               network link to the robot
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

Then start the simulator and the driver station in two terminals, or use the **Simulator + driver
station** launch configuration in VS Code:

```powershell
.\venv\Scripts\python main.py robot --sim
.\venv\Scripts\python main.py station --host localhost
```

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
6. **Set the invert flags, wheels off the ground:**
   ```bash
   venv/bin/python -m tools.motor_test module FL
   ```
   It runs pure drive and then pure steer and tells you which flags to change. Repeat for FR, BL, BR and
   set the flags in the Mapping tab. `motor_test motor M3` spins a single motor if you need it.
7. **Run:** `venv/bin/python main.py robot`. Point the driver station at the Pi's hostname or IP.

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

Before the first run, line every wheel up straight by hand and press **−**. At every start-up after that,
each wheel must be within ±90° of zero (the encoder is geared 2:1, so it cannot tell 0° from 180°).
**Press + before switching the robot off** so the wheels are parked at zero. The program also returns
the wheels to zero when it is stopped normally, but the rocker switch cuts power instantly.

Safety rules:

- The robot only drives while the station says enabled and commands keep arriving. No command for
  250 ms disables it (watchdog).
- The station can only enable with both the controller and the robot connected, and disables itself if
  either drops out.
- Mapping changes are only accepted while the robot is disabled. Tuning changes apply live.
- A module whose encoder stops answering coasts until it answers again.

## Driver station tabs

- **Drive:** top-down robot view. Wheels turn to the angle the Pi reports, the dashed line is each
  module's target angle, and the green arrow shows which way the Pi is rolling the wheel and how hard.
  Click any part for its role, wiring and live values. Sliders with exact-value boxes set
  sensitivity and deadzone for each stick. The terminal shows everything the Pi sends (tick
  *Show telemetry* for the live data stream).
- **Mapping:** which motors, encoder and invert flags each module uses, which H-bridge channel each
  motor is plugged into, and which I2C bus each encoder is on.
- **Tuning:** steering PID, steer output limit, max wheel speed, acceleration limit and more.

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

- **MPU-6050:** `robot/hardware/imu.py` is a placeholder, as the BOM asks. Implementing it enables the
  field-relative option.
- **Measure:** max wheel speed (Tuning tab) and `geometry.module_offset_m` in `robot_config.json`.
- **Tune** the steering PID on the real robot (order is listed on the Tuning tab).
