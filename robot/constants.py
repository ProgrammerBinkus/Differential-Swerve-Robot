"""Mechanical constants of the differential swerve modules (from the BOM)."""

import math

# 90T gear on the module, 45T gear on the encoder: the encoder turns twice per
# module revolution, so one encoder revolution is 180 degrees of steering.
ENCODER_TO_MODULE_RATIO = 90 / 45

# Steering: 16T input to 112T output, a 7:1 reduction from motor to module.
STEER_REDUCTION = 112 / 16

# Drive: 16T -> 112T, then 92T -> 16T, an overall 28:23 reduction from motor to wheel.
DRIVE_REDUCTION = (112 / 16) * (16 / 92)

TAU = 2 * math.pi
