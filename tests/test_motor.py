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
