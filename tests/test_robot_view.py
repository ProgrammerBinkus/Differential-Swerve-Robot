"""The robot view's wheel drawing, in particular a wheel the robot has flipped (optimize) and runs backwards."""

import math

import pytest

from station.views.robot_view import RobotView, heading_vector


@pytest.fixture
def view(tk_root):
    canvas = RobotView(tk_root, on_select=lambda _id: None)
    canvas.pack()
    tk_root.update()
    canvas._draw()
    yield canvas
    canvas.destroy()


def _module(angle, target, drive):
    return {"angle": angle, "target": target, "drive": drive, "steer": 0.0, "motors": [drive, drive],
            "raw": 0, "offset": 0, "fault": False}


def _arrow_heading(view, name):
    x0, y0, x1, y1 = view.coords(view._wheels[name]["arrow"])
    # heading_vector maps 0 deg to screen-up and counter-clockwise to screen-left.
    return math.degrees(math.atan2(-(x1 - x0), -(y1 - y0)))


def test_a_reversed_wheel_points_its_arrow_the_way_the_robot_moves(view):
    # Asked for 170 degrees, the wheel steered to -10 and spins backwards (drive -50%).
    view.update_modules({name: _module(-10.0, -10.0, -0.5) for name in ("FL", "FR", "BL", "BR")})
    for name in ("FL", "FR", "BL", "BR"):
        assert view.itemcget(view._wheels[name]["arrow"], "state") == "normal"
        assert _arrow_heading(view, name) == pytest.approx(170.0, abs=0.5)
        assert view.itemcget(view._wheels[name]["text"], "text") == "-10°  -50%"


def test_a_forward_wheel_points_its_arrow_along_the_wheel(view):
    view.update_modules({name: _module(30.0, 30.0, 0.5) for name in ("FL", "FR", "BL", "BR")})
    assert _arrow_heading(view, "FL") == pytest.approx(30.0, abs=0.5)


def test_heading_vector_screen_directions():
    assert heading_vector(0) == pytest.approx((0.0, -1.0))     # forward is up the screen
    assert heading_vector(90) == pytest.approx((-1.0, 0.0))    # left is left
