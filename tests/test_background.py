"""Background sensor reads: the loop gets the newest value and never waits on the bus."""

import pytest

from robot.hardware.background import BackgroundEncoder, BackgroundGyro, BackgroundReader


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_get_returns_the_newest_reading_while_it_is_fresh():
    values, clock = iter([10, 20]), Clock()
    reader = BackgroundReader("x", lambda: next(values), 0.01, 0.05, clock=clock, start=False)
    assert reader.get() == 10                       # read once at construction
    reader.poll()
    assert reader.get() == 20


def test_a_stale_reading_counts_as_a_failed_read():
    clock = Clock()
    reader = BackgroundReader("E3", lambda: 5, 0.01, 0.05, clock=clock, start=False)
    clock.now = 0.06
    with pytest.raises(OSError, match="E3: no fresh reading"):
        reader.get()


def test_failed_reads_keep_the_last_value_until_it_goes_stale():
    clock, fail = Clock(), [False]

    def read():
        if fail[0]:
            raise OSError("I2C transfer: Invalid argument")
        return 7

    reader = BackgroundReader("E2", read, 0.01, 0.05, clock=clock, start=False)
    fail[0] = True
    clock.now = 0.03
    reader.poll()
    assert reader.get() == 7                        # one bad read doesn't hide the last good one
    clock.now = 0.06
    with pytest.raises(OSError, match="Invalid argument"):
        reader.get()


def test_no_reading_at_all_is_an_error():
    def read():
        raise OSError("bus stuck")
    reader = BackgroundReader("E1", read, 0.01, 0.05, start=False)
    with pytest.raises(OSError, match="bus stuck"):
        reader.get()


def test_the_thread_keeps_reading_and_stops_on_close():
    count = [0]

    def read():
        count[0] += 1
        return count[0]

    reader = BackgroundReader("x", read, 0.001, 1.0)
    import time
    time.sleep(0.05)
    reader.close()
    seen = count[0]
    assert seen > 3
    time.sleep(0.02)
    assert count[0] == seen                         # stopped


class FakeEncoder:
    bus_path = "/dev/i2c-2"

    def __init__(self):
        self.closed = False

    def read_raw(self):
        return 1234

    def close(self):
        self.closed = True


def test_background_encoder_wraps_a_sensor():
    sensor = FakeEncoder()
    encoder = BackgroundEncoder(sensor, start=False)
    assert encoder.bus_path == "/dev/i2c-2" and encoder.read_raw() == 1234
    encoder.close()
    assert sensor.closed


class FakeGyro:
    bus_path, chip_id = "/dev/i2c-2", 0x70

    def read_rate_dps(self):
        return 1.5

    def read_sample(self):
        return {"temp": 20.0}

    def close(self):
        pass


def test_background_gyro_passes_its_readings_and_attributes_through():
    gyro = BackgroundGyro(FakeGyro(), start=False)
    assert gyro.read_rate_dps() == 1.5 and gyro.read_sample() == {"temp": 20.0}
    assert (gyro.bus_path, gyro.chip_id) == ("/dev/i2c-2", 0x70)
    gyro.close()


def test_one_thread_per_bus_so_no_bus_ever_sees_two_transfers_at_once():
    import threading
    readers = [BackgroundReader(f"r{i}", lambda: 1, 0.005, 1.0, group=f"test-bus-{i % 2}") for i in range(5)]
    try:
        names = sorted(t.name for t in threading.enumerate() if t.name.startswith("sensor-reader test-bus"))
        assert names == ["sensor-reader test-bus-0", "sensor-reader test-bus-1"]   # 5 readers, 2 threads
    finally:
        for r in readers:
            r.close()
