# Orange Pi: setup from scratch, everyday use, and recovery

Everything needed to rebuild the robot's Orange Pi 4 Pro from a blank SD card, keep its code up to date,
and diagnose or rescue a Pi that stops booting. The wiring itself is on the two wiring sheets in this
folder: open them in a browser.

- [`wiring-sheet-E-01.html`](wiring-sheet-E-01.html): plan view, power, current budget and parts to add
  (rev A). Its pin map is older: **E-02 is the current pin assignment.**
- [`wiring-sheet-E-02.html`](wiring-sheet-E-02.html): every pin and conductor (rev D, 2026-11-20), with the
  H-bridge inputs paired on side-by-side header pins for 2-pin connectors.

## What the scripts are

| File | Runs on | What it does |
|---|---|---|
| `pi_setup/image/prepare_image.sh` | WSL, before flashing | Adds this PC's SSH key, your Wi-Fi and the robot code to a downloaded image |
| `pi_setup/image/wifi.nmconnection.example` | | Template for the Wi-Fi file (copy it, fill it in, never commit it) |
| `pi_setup/setup.sh` | Pi, once | Packages, I2C/PWM overlays, text console, HDMI fix, robot venv, reboot |
| `pi_setup/perms.sh` | Pi, once | Lets `orangepi` use I2C and GPIO without sudo |
| `pi_setup/finish.sh` | Pi, once | PWM permissions, the `orangepi4pro.local` name, the `swerve-robot` service |
| `pi_setup/hdmi-fix/` | | HDMI fix installed by `setup.sh` (from CheezeCS/armbian-a733-gpu, MIT) |
| `pi_setup/sync.ps1` | this PC | Copies the code to the Pi, updates its H-bridge pins, restarts the robot |
| `pi_setup/find_pi.ps1` | this PC | Finds the Pi on the Wi-Fi when `orangepi4pro.local` doesn't answer |
| `tools/link_check.py` | this PC | Checks the PC ↔ robot link the way the driver station uses it |
| `pi_setup/card/backup_card.ps1` | this PC (admin) | Copies a whole SD card into an image file, read-only |
| `pi_setup/card/inspect_card.sh` | WSL | Checks a card copy: filesystem, boot files, when it last booted |
| `pi_setup/card/shrink_image.sh` | WSL | Repairs a card copy and shrinks it into an image for any 8 GB+ card |

The WSL steps need the Linux layer in Windows: `wsl --install -d Ubuntu-24.04` once (it restarts
Windows). Windows itself can't read the Pi's ext4 filesystem. To remove it later:
`wsl --unregister Ubuntu-24.04`.

## Setting up a new card

1. **Download the image.** Orange Pi's official download page for the Orange Pi 4 Pro, Debian 12
   (Bookworm), kernel 6.6: `Orangepi4pro_1.0.8_debian_bookworm_desktop_xfce_linux6.6.98`. Unpack the `.7z`
   to get the `.img`. The robot needs Python 3.11+, so don't use the Ubuntu 22.04 (Jammy) image.
2. **SSH key on this PC** (once): `ssh-keygen -t ed25519` in PowerShell, accept the defaults.
3. **Wi-Fi file:** copy `pi_setup/image/wifi.nmconnection.example` to somewhere outside the repo, for
   example `Downloads\robot-wifi.nmconnection`, and fill in `ssid=` and `psk=`.
4. **Prepare the image** in WSL, from the project folder:
   ```bash
   sudo bash pi_setup/image/prepare_image.sh /mnt/c/Users/<you>/Downloads/<image>.img \
       /mnt/c/Users/<you>/.ssh/id_ed25519.pub /mnt/c/Users/<you>/Downloads/robot-wifi.nmconnection
   ```
   Then delete the Wi-Fi file: it holds the password in plain text.
5. **Flash** with Raspberry Pi Imager: *Choose OS → Use custom* → the `.img`, *Choose Storage* → the
   card. Say **No** to customising settings. If Windows offers to format the card afterwards, cancel.
6. **First boot:** card in the Pi, power on, wait 2–3 minutes. Then find it:
   `powershell -ExecutionPolicy Bypass -File pi_setup\find_pi.ps1`.
7. **Run the setup scripts.** Each asks for the Pi's password (`orangepi` on a fresh image); type it
   yourself. Use the IP from step 6 until `finish.sh` has set up the `.local` name:
   ```powershell
   ssh -t orangepi@<ip> "sudo bash ~/'Differential Swerve Chassis'/pi_setup/setup.sh"
   ssh -t orangepi@<ip> "sudo bash ~/'Differential Swerve Chassis'/pi_setup/perms.sh"
   ssh -t orangepi@<ip> "sudo bash ~/'Differential Swerve Chassis'/pi_setup/finish.sh"
   ```
   `setup.sh` reboots the Pi at the end; wait a minute before `perms.sh`.
8. **Check it:** `python -m tools.link_check orangepi4pro.local`, then the hardware steps in the README
   (`tools.probe_hardware`, `tools.encoder_monitor`, `tools.motor_test`). `probe_hardware` and
   `motor_test` pause the `swerve-robot` service while they run (it holds the pins) and start it again.

## Everyday use

- **Update the code on the Pi:** `powershell -ExecutionPolicy Bypass -File pi_setup\sync.ps1`. It keeps
  the Pi's `robot_config.json` (mapping, offsets, tuning) but always takes the H-bridge pins from
  `common/config.py`, since those only change when the robot is rewired.
- **Robot log:** `ssh orangepi@orangepi4pro.local journalctl -u swerve-robot -f`
- **Shut down before cutting power** when you can: `ssh -t orangepi@orangepi4pro.local "sudo poweroff"`.
  Cutting the battery while Linux is writing leaves damaged files behind (usually only logs).

## What the LEDs mean

- **Red:** the board has power.
- **Green blinking:** Linux is running (a heartbeat). No blinking green means Linux never started.

**HDMI on this image:** the display driver gives up on HDMI for good if the monitor briefly drops its
signal at start-up, and nothing appears before Linux loads (20–30 s in). `setup.sh` installs a fix and
boots to a text console. On a freshly flashed card the fix isn't there yet, so use SSH instead.

## Power rules

- Only header pins 2 and 4 take 5 V. Every other pin is 3.3 V and is damaged by 5 V.
- **Never** connect the Pi's USB-C supply while the hub powers it through the header.
- **Reversed battery leads can destroy the 5 V regulator and the Pi.** A cheap buck converter has no
  reverse-polarity protection. Use keyed connectors (XT60), an inline fuse, and ideally an ideal-diode or
  P-MOSFET reverse-polarity stage. After any reversal, measure the regulator's output with nothing
  connected before plugging the Pi back in.

## When the Pi won't boot

1. **Look at the LEDs.** Red off: no power reaching the board. Red on but no green blinking: power is
   there, Linux isn't starting.
2. **Measure the rails.** Meter on DC volts, black probe on pin 6 (GND): pin 2 should read about 5 V and
   pin 1 about 3.3 V. Push a female dupont jumper onto each pin and probe its other end, so a slipping
   probe can't short pin 1 to pin 2.
3. **Try known-good power:** the Pi's own USB-C supply with the header's 5 V wires unplugged.
4. **Check the card** on this PC (below). If the card is fine and the board still won't start on good
   power, flash a second card. If that fails too, the board is damaged.
5. **Definitive test:** a 3.3 V USB-to-serial adapter (CH340 or CP2102) on the debug UART shows every
   message from power-on, and so whether the boot loader runs at all.

### Checking and rescuing the SD card

WSL can't attach a USB card reader directly, so copy the card into a file first. The copy only reads the
card.

1. Card in the reader. Find its disk number with `Get-Disk` (the 15 GB "Generic Mass-Storage" one), then
   in PowerShell (Windows asks for admin approval):
   ```powershell
   Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File "<project>\pi_setup\card\backup_card.ps1" -Out C:\pi\card.img -Disk 1'
   ```
   It takes 10–45 minutes depending on the reader and writes a progress log next to the image. If the
   log shows a run of read errors, the reader dropped off USB: run it again with `-StartGB` a little
   before where they started. Leave the card alone while it runs.
2. Inspect the copy in WSL: `sudo bash pi_setup/card/inspect_card.sh /mnt/c/pi/card.img`.
   - **Last mount time** is the last boot that reached Linux. If it's long before the failed boots, the
     board never got as far as Linux.
   - After a power cut, `e2fsck` lists errors in `/var/log` and wrong free counts, and the
     `needs_recovery` feature is set. The Pi's own boot repairs these, so they don't stop it booting.
   - The boot files should all be present: `uImage` and `uInitrd` start `27051956`, the `.dtb` and every
     overlay `d00dfeed`.
3. **Make a flashable image** from the copy (work on a copy of it, since this edits in place):
   ```bash
   cp /mnt/c/pi/card.img /mnt/c/pi/robot.img
   sudo bash pi_setup/card/shrink_image.sh /mnt/c/pi/robot.img 6
   ```
   It repairs the filesystem, shrinks it to 6 GiB and switches Orange Pi's first-boot resize back on.
   Flash `robot.img` to any 8 GB+ card. On first boot the Pi grows it to fill the card and reboots once
   (allow about 3 minutes). It is the same system: Wi-Fi, SSH key, setup and robot service included.
