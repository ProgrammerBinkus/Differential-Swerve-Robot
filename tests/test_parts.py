"""The robot view's layout: parts must not overlap and every harness must reach the parts it names."""

from __future__ import annotations

from itertools import combinations

from station.parts import PARTS, PARTS_BY_ID, WIRES


def _box(part, grow: float = 0.0):
    return (part.x - part.w / 2 - grow, part.y - part.h / 2 - grow,
            part.x + part.w / 2 + grow, part.y + part.h / 2 + grow)


def _segments(wire):
    for run in (wire.points, wire.branch):
        yield from zip(run, run[1:])


def _segment_enters(segment, box) -> bool:
    """True if an axis-aligned segment passes through the inside of the box (touching an edge is fine)."""
    (ax, ay), (bx, by) = segment
    x0, y0, x1, y1 = box
    if ax == bx:  # vertical run
        return x0 < ax < x1 and min(ay, by) < y1 and max(ay, by) > y0
    return y0 < ay < y1 and min(ax, bx) < x1 and max(ax, bx) > x0


def test_no_two_parts_overlap():
    for a, b in combinations(PARTS, 2):
        ax0, ay0, ax1, ay1 = _box(a)
        bx0, by0, bx1, by1 = _box(b)
        assert ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0, f"{a.id} overlaps {b.id}"


def test_the_imu_sits_between_hb2_and_the_power_hub():
    imu, hb2, hub = PARTS_BY_ID["mpu"], PARTS_BY_ID["HB2"], PARTS_BY_ID["pdh"]
    assert _box(hb2)[3] < _box(imu)[1] and _box(imu)[3] < _box(hub)[1]      # below HB2, above the hub
    assert _box(hb2)[0] <= imu.x <= _box(hb2)[2] and _box(hub)[0] <= imu.x <= _box(hub)[2]


def test_wires_are_square_and_touch_only_the_parts_they_connect():
    for wire in WIRES:
        for (ax, ay), (bx, by) in _segments(wire):
            assert ax == bx or ay == by, f"{wire.id} has a diagonal run"
        for part in PARTS:
            entered = any(_segment_enters(seg, _box(part)) for seg in _segments(wire))
            if part.id not in wire.ends:
                assert not entered, f"{wire.id} runs through {part.id}"


def test_every_wire_end_reaches_its_part():
    for wire in WIRES:
        tips = [wire.points[0], wire.points[-1]] + ([wire.branch[0], wire.branch[-1]] if wire.branch else [])
        for part_id in wire.ends:
            x0, y0, x1, y1 = _box(PARTS_BY_ID[part_id], grow=1.0)
            on_tip = any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in tips)
            passes = any(_segment_enters(seg, _box(PARTS_BY_ID[part_id])) for seg in _segments(wire))
            assert on_tip or passes, f"{wire.id} does not reach {part_id}"
