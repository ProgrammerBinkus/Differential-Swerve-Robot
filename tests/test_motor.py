"""The AT8236 channel logic, with fake PWM and GPIO objects."""

from robot.hardware.motor import HBridgeChannel


class FakePwm:
    def __init__(self):
        self.duty_cycle = 0.0


class FakePin:
    def __init__(self):
        self.value = False

    def write(self, value):
        self.value = value


def channel():
    pwm, pin = FakePwm(), FakePin()
    return HBridgeChannel("HB1.A", pwm, pin), pwm, pin


def test_forward_and_reverse():
    motor, pwm, pin = channel()
    motor.set(0.3)
    assert (pin.value, pwm.duty_cycle) == (False, 0.3)       # IN2 low, IN1 30%: forward/coast
    motor.set(-0.3)
    assert (pin.value, round(pwm.duty_cycle, 6)) == (True, 0.7)  # IN2 high, IN1 70%: 30% reverse


def test_brake_drives_both_inputs_high_and_driving_resumes_after():
    motor, pwm, pin = channel()
    motor.set(0.5)
    motor.brake()
    assert (pin.value, pwm.duty_cycle, motor.braking) == (True, 1.0, True)
    motor.set(0.2)
    assert (pin.value, pwm.duty_cycle, motor.braking) == (False, 0.2, False)
    motor.stop()
    assert (pin.value, pwm.duty_cycle) == (False, 0.0)       # both low: coast


def test_reverse_is_scaled_down_when_configured():
    motor, pwm, pin = channel()
    motor.configure(reverse_scale=0.5, ramp_per_s=None)
    motor.set(-0.6)
    assert (pin.value, round(pwm.duty_cycle, 6)) == (True, 0.7)   # 30% reverse, not 60%
    motor.set(0.6)
    assert (pin.value, round(pwm.duty_cycle, 6)) == (False, 0.6)  # forward unchanged
    assert motor.output == 0.6


def test_power_rises_at_the_ramp_rate_and_falls_at_once(monkeypatch):
    import robot.hardware.motor as motor_module
    clock = [100.0]
    monkeypatch.setattr(motor_module.time, "monotonic", lambda: clock[0])
    motor, pwm, pin = channel()
    motor.configure(reverse_scale=1.0, ramp_per_s=5.0)
    motor.set(0.8)                       # first call: no time has passed, nothing applied yet
    assert pwm.duty_cycle == 0.0
    for _ in range(4):                   # 4 loops of 10 ms at 5/s: +0.05 each
        clock[0] += 0.01
        motor.set(0.8)
    assert round(pwm.duty_cycle, 6) == 0.2
    clock[0] += 0.01
    motor.set(0.1)                       # less power: at once
    assert round(pwm.duty_cycle, 6) == 0.1
    clock[0] += 0.01
    motor.set(-0.8)                      # reversing starts again from zero, then ramps
    assert pin.value is True and round(pwm.duty_cycle, 6) == 0.95  # 5% reverse
    clock[0] += 0.01
    motor.set(-0.8)
    assert round(pwm.duty_cycle, 6) == 0.9                         # 10% reverse


def test_a_long_gap_does_not_let_the_power_jump(monkeypatch):
    import robot.hardware.motor as motor_module
    clock = [0.0]
    monkeypatch.setattr(motor_module.time, "monotonic", lambda: clock[0])
    motor, pwm, _ = channel()
    motor.configure(reverse_scale=1.0, ramp_per_s=5.0)
    motor.set(0.0)
    clock[0] += 10.0
    motor.set(1.0)
    assert round(pwm.duty_cycle, 6) == 0.25                       # at most 50 ms' worth


def test_brake_resets_the_ramp(monkeypatch):
    import robot.hardware.motor as motor_module
    clock = [0.0]
    monkeypatch.setattr(motor_module.time, "monotonic", lambda: clock[0])
    motor, pwm, pin = channel()
    motor.configure(reverse_scale=1.0, ramp_per_s=5.0)
    motor.set(0.5)
    for _ in range(20):
        clock[0] += 0.01
        motor.set(0.5)
    assert round(pwm.duty_cycle, 6) == 0.5
    motor.brake()
    clock[0] += 0.01
    motor.set(0.5)
    assert pin.value is False and round(pwm.duty_cycle, 6) == 0.05
