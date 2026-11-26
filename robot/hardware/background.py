"""Sensor reads on background threads, so a stuck I2C bus can't freeze the robot loop.

With the motors running, noise makes the odd I2C transfer fail, and the Orange Pi's
TWI driver can then spend a long time recovering the bus ("Bus error ... STOP failed")
before the read returns. Read in the loop, that froze everything: the driver station
stopped hearing from the robot and disabled it. Here the sensors are read off the loop,
and the loop only takes the latest value. A reading older than ``max_age_s`` raises
``OSError`` like a failed read, so the existing error counting (a module stops after 10
in a row) still decides when a sensor has really gone.

Each I2C bus gets ONE thread, which reads that bus's sensors strictly one after another
(E3 and the IMU share /dev/i2c-2, so they share a thread). A thread per sensor (tried
first) put two transfers on the shared E3/IMU bus at once, and while the TWI driver was
recovering from noise that hung the whole kernel: the Pi froze until power-cycled. One
thread for everything (tried next) let a single stuck bus starve every sensor, so all four
wheels stopped at once.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


class _SharedPoller:
    """One thread per group (an I2C bus) that polls that group's readers in turn."""

    def __init__(self) -> None:
        self._readers: dict[str, list["BackgroundReader"]] = {}
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    def add(self, reader: "BackgroundReader") -> None:
        with self._lock:
            self._readers.setdefault(reader.group, []).append(reader)
            thread = self._threads.get(reader.group)
            if thread is None or not thread.is_alive():
                thread = threading.Thread(target=self._run, args=(reader.group,),
                                          name=f"sensor-reader {reader.group}", daemon=True)
                self._threads[reader.group] = thread
                thread.start()

    def remove(self, reader: "BackgroundReader") -> None:
        with self._lock:
            group = self._readers.get(reader.group, [])
            if reader in group:
                group.remove(reader)

    def _run(self, group: str) -> None:
        while True:
            with self._lock:
                readers = list(self._readers.get(group, []))
            if not readers:
                time.sleep(0.05)
                continue
            now = time.monotonic()
            for reader in readers:
                if reader.due(now):
                    reader.poll()
            time.sleep(min(r.period_s for r in readers) / 2)


POLLER = _SharedPoller()


class BackgroundReader:
    """Keeps the newest result of ``read``, called every ``period_s`` by the shared poller thread."""

    def __init__(self, name: str, read: Callable[[], Any], period_s: float, max_age_s: float,
                 clock: Callable[[], float] = time.monotonic, start: bool = True, group: str = "default") -> None:
        self.name = name
        self.group = group
        self.period_s = period_s
        self._read = read
        self._max_age_s = max_age_s
        self._clock = clock
        self._lock = threading.Lock()
        self._value: Any = None
        self._time: Optional[float] = None
        self._error: Optional[BaseException] = None
        self._last_poll = -1e9
        self.poll()   # one reading straight away, so the first get() has something
        self._registered = start
        if start:
            POLLER.add(self)

    def due(self, now: float) -> bool:
        return now - self._last_poll >= self.period_s

    def poll(self) -> None:
        """Take one reading now (the poller does this every ``period_s``)."""
        self._last_poll = time.monotonic()
        try:
            value = self._read()
        except OSError as exc:
            with self._lock:
                self._error = exc
            return
        with self._lock:
            self._value, self._time, self._error = value, self._clock(), None

    def get(self) -> Any:
        """The newest reading, or ``OSError`` if there is none younger than ``max_age_s``."""
        with self._lock:
            if self._time is None or self._clock() - self._time > self._max_age_s:
                reason = self._error or "no reading yet"
                raise OSError(f"{self.name}: no fresh reading ({reason})")
            return self._value

    def close(self) -> None:
        if self._registered:
            POLLER.remove(self)
            self._registered = False


class BackgroundEncoder:
    """An angle sensor whose reads happen on a background thread."""

    PERIOD_S = 0.005    # once per robot loop (200 Hz); faster only adds load on a bus that may be recovering
    MAX_AGE_S = 0.05    # 10 loops at 200 Hz

    def __init__(self, sensor: Any, start: bool = True) -> None:
        self._sensor = sensor
        self.bus_path = getattr(sensor, "bus_path", None)
        self._reader = BackgroundReader(f"encoder {self.bus_path}", sensor.read_raw,
                                        self.PERIOD_S, self.MAX_AGE_S, start=start, group=str(self.bus_path))

    def read_raw(self) -> int:
        return self._reader.get()

    def close(self) -> None:
        self._reader.close()
        self._sensor.close()


class BackgroundGyro:
    """An MPU-6050/6500 whose rate (fast) and full sample (slow) are read on background threads."""

    RATE_PERIOD_S, RATE_MAX_AGE_S = 0.004, 0.05
    SAMPLE_PERIOD_S, SAMPLE_MAX_AGE_S = 0.1, 0.5

    def __init__(self, source: Any, start: bool = True) -> None:
        self._source = source
        bus = str(getattr(source, "bus_path", ""))
        name = f"IMU {bus}".strip()
        self._rate = BackgroundReader(f"{name} rate", source.read_rate_dps,
                                      self.RATE_PERIOD_S, self.RATE_MAX_AGE_S, start=start, group=bus)
        self._sample = BackgroundReader(f"{name} sample", source.read_sample,
                                        self.SAMPLE_PERIOD_S, self.SAMPLE_MAX_AGE_S, start=start, group=bus)

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._source, attr)   # bus_path, chip_id, ...

    def read_rate_dps(self) -> float:
        return self._rate.get()

    def read_sample(self) -> dict[str, Any]:
        return self._sample.get()

    def close(self) -> None:
        self._rate.close()
        self._sample.close()
        self._source.close()
