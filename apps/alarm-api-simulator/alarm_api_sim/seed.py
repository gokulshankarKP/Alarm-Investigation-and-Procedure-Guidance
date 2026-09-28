"""Deterministic seed-data generator.

The history is synthetic but tells coherent stories that the RAG corpus can explain:

* **BFP-101 recurring cavitation** - DA-101 low level -> BFP-101 low suction pressure ->
  high vibration -> sometimes a vibration trip (TSG-BFP-002 section 4). Frequency increases
  over the last 60 days.
* **Current NorthPlant upset** - DA-101 low level with BFP-102 low-low suction pressure
  (critical) and a vibration trip, both active and unacknowledged.
* **EastRefinery discharge pressure** - K-201 and K-202 alarm together with PCV-210 position
  deviation (downstream restriction, TSG-CMP-002 cause 1), many short chattering alarms
  (cause 2), and slowly increasing K-201 intercooler temperature alarms (cause 3). An active
  CMP-SURGE on K-202 is the highest-priority alarm on site.
* **SouthPlant motor trips** - M-501 and M-502 trip together after TR-501 voltage dips
  (MM-MTR-001 section 4 correlation rule).
* **Alarm flood** in EastRefinery Unit 2 110 days before the anchor (2026-06-12 by default).
* Nuisance/chattering alarms in EastRefinery Unit 4 and background alarms in NorthPlant Unit 3.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from alarm_api_sim.catalog import ALARM_DEFINITIONS

SEED_DAYS = 183


@dataclass
class AlarmRecord:
    alarm_id: str
    asset_id: str
    alarm_code: str
    start_time: datetime
    end_time: datetime | None
    ack_time: datetime | None
    value: float | None

    @property
    def is_active(self) -> bool:
        return self.end_time is None


class _Builder:
    def __init__(self, anchor: datetime, seed: int) -> None:
        self.anchor = anchor
        self.start = anchor - timedelta(days=SEED_DAYS)
        self.rng = random.Random(seed)
        self.rows: list[tuple[str, str, datetime, datetime | None, datetime | None, float | None]] = []

    def add(
        self,
        asset_id: str,
        code: str,
        start: datetime,
        duration_min: float | None,
        ack_delay_s: float | None,
    ) -> None:
        if start >= self.anchor or start < self.start:
            return
        end = None if duration_min is None else start + timedelta(minutes=duration_min)
        if end is not None and end >= self.anchor:
            end = None  # still active at the anchor
        ack = None if ack_delay_s is None else start + timedelta(seconds=ack_delay_s)
        if ack is not None and ack >= self.anchor:
            ack = None
        self.rows.append((asset_id, code, start, end, ack, self._value(code)))

    def _value(self, code: str) -> float | None:
        setpoint = ALARM_DEFINITIONS[code].setpoint
        if setpoint is None:
            return None
        low_alarm = code.endswith(("-L", "-LL")) or code.endswith("DIP")
        delta = abs(setpoint) * self.rng.uniform(0.01, 0.08)
        return round(setpoint - delta if low_alarm else setpoint + delta, 2)

    def minutes_ago(self, minutes: float) -> datetime:
        return self.anchor - timedelta(minutes=minutes)

    def u(self, a: float, b: float) -> float:
        return self.rng.uniform(a, b)


def _bfp_cavitation(b: _Builder) -> None:
    t = b.start + timedelta(days=b.u(1, 4))
    recent = b.anchor - timedelta(days=60)
    while t < b.anchor - timedelta(days=2):
        b.add("DA-101", "DA-LVL-L", t, b.u(20, 60), b.u(40, 200))
        if b.rng.random() < 0.4:
            b.add("DA-101", "DA-P-L", t + timedelta(minutes=1), b.u(10, 30), b.u(60, 240))
        b.add("BFP-101", "BFP-SUCT-P-L", t + timedelta(minutes=2), b.u(10, 30), b.u(30, 150))
        b.add("BFP-101", "BFP-VIB-H", t + timedelta(minutes=5), b.u(15, 40), b.u(30, 240))
        if b.rng.random() < (0.55 if t > recent else 0.3):
            b.add("BFP-101", "BFP-VIB-HH", t + timedelta(minutes=9), b.u(60, 240), b.u(20, 90))
            if b.rng.random() < 0.3:
                b.add("BLR-101", "BLR-DRUM-LVL-L", t + timedelta(minutes=10), b.u(5, 15), b.u(15, 60))
        if b.rng.random() < 0.15:
            b.add("BFP-101", "BFP-SEAL-LEAK-H", t + timedelta(hours=b.u(4, 30)), b.u(60, 400), b.u(120, 900))
        t += timedelta(days=b.u(2.5, 5) if t > recent else b.u(5, 9))

    for _ in range(3):
        b.add("BFP-101", "BFP-BRG-TEMP-H", b.start + timedelta(days=b.u(10, 170)), b.u(20, 90), b.u(60, 300))
    trip = b.anchor - timedelta(days=71, hours=5)
    b.add("M-101", "MTR-TRIP-OL", trip, 95, 45)
    b.add("BFP-101", "BFP-MOTOR-TRIP", trip + timedelta(seconds=5), 95, 40)
    for _ in range(4):
        b.add("FCV-101", "FCV-POS-DEV", b.start + timedelta(days=b.u(5, 175)), b.u(30, 300), None)


def _bfp_current_upset(b: _Builder) -> None:
    for _ in range(2):
        b.add("BFP-102", "BFP-SEAL-LEAK-H", b.start + timedelta(days=b.u(20, 150)), b.u(120, 600), b.u(300, 1200))
    b.add("BFP-102", "BFP-MIN-FLOW-L", b.anchor - timedelta(days=12), 25, 180)
    b.add("BFP-101", "BFP-VIB-H", b.minutes_ago(42), None, 95)
    b.add("DA-101", "DA-LVL-L", b.minutes_ago(18), None, 70)
    b.add("BFP-102", "BFP-SUCT-P-L", b.minutes_ago(15), None, None)
    b.add("BFP-102", "BFP-SUCT-P-LL", b.minutes_ago(12), None, None)
    b.add("BFP-102", "BFP-VIB-HH", b.minutes_ago(10), None, None)
    b.add("FCV-101", "FCV-POS-DEV", b.anchor - timedelta(days=2, hours=3), None, None)  # stale


def _compressors(b: _Builder) -> None:
    t = b.start + timedelta(days=b.u(0.5, 2))
    while t < b.anchor - timedelta(days=1):
        b.add("PCV-210", "PCV-POS-DEV", t, b.u(30, 90), b.u(120, 600))
        for asset, offset in (("K-201", 3), ("K-202", 4)):
            s = t + timedelta(minutes=offset + b.u(0, 1))
            for _ in range(b.rng.randint(1, 4)):  # chattering activations
                b.add(asset, "CMP-DISCH-P-H", s, b.u(0.5, 1.8), b.u(40, 90) if b.rng.random() < 0.3 else None)
                s += timedelta(minutes=b.u(1.5, 4))
        if b.rng.random() < 0.08:
            b.add("K-201", "CMP-DISCH-P-HH", t + timedelta(minutes=12), b.u(60, 180), b.u(30, 90))
        t += timedelta(days=b.u(2, 5))

    # Intercooler fouling on K-201: sparse at first, more frequent in the last 90 days.
    t = b.start + timedelta(days=15)
    while t < b.anchor - timedelta(days=1):
        b.add("K-201", "CMP-INTERCOOL-T-H", t, b.u(60, 300), b.u(120, 900))
        if b.rng.random() < 0.3:
            b.add("K-201", "CMP-DISCH-T-H", t + timedelta(minutes=b.u(20, 60)), b.u(20, 90), b.u(60, 300))
        days_left = (b.anchor - t).days
        t += timedelta(days=b.u(9, 14) if days_left > 90 else b.u(2.5, 5))

    for _ in range(3):
        b.add("K-203", "CMP-LUBE-P-L", b.start + timedelta(days=b.u(5, 175)), b.u(5, 20), b.u(20, 80))
    for _ in range(4):
        b.add("K-202", "CMP-VIB-H", b.start + timedelta(days=b.u(5, 175)), b.u(10, 60), b.u(60, 200))

    # Active now.
    b.add("K-202", "CMP-SURGE", b.minutes_ago(25), None, None)
    b.add("PCV-210", "PCV-POS-DEV", b.minutes_ago(15), None, 300)
    b.add("K-201", "CMP-DISCH-P-H", b.minutes_ago(8), None, 60)


def _unit2_flood(b: _Builder) -> None:
    t0 = (b.anchor - timedelta(days=110)).replace(hour=10, minute=4, second=0, microsecond=0)
    sequence = [
        ("PCV-210", "PCV-POS-DEV", 0.0),
        ("K-201", "CMP-DISCH-P-H", 0.5),
        ("K-202", "CMP-DISCH-P-H", 0.7),
        ("K-201", "CMP-DISCH-P-HH", 1.2),
        ("K-202", "CMP-SURGE", 1.6),
        ("UV-202", "PCV-POS-DEV", 1.9),
        ("K-202", "CMP-VIB-H", 2.4),
        ("K-201", "CMP-DISCH-T-H", 2.8),
        ("M-202", "MTR-PHASE-IMB", 3.1),
        ("K-203", "CMP-LUBE-P-L", 3.6),
        ("K-202", "CMP-DISCH-P-HH", 4.2),
        ("E-201", "CMP-INTERCOOL-T-H", 4.9),
        ("K-203", "CMP-DISCH-P-H", 5.6),
        ("K-201", "CMP-VIB-H", 6.3),
        ("M-201", "MTR-VIB-H", 7.4),
    ]
    for asset, code, minute in sequence:
        b.add(asset, code, t0 + timedelta(minutes=minute), b.u(5, 45), b.u(60, 420))


def _motors(b: _Builder) -> None:
    for day in (160, 118, 64, 23):
        t = (b.anchor - timedelta(days=day)).replace(hour=b.rng.randint(1, 22), minute=b.rng.randint(0, 59))
        b.add("TR-501", "TR-VOLT-DIP", t, b.u(1, 3), b.u(30, 120))
        b.add("M-501", "MTR-TRIP-OL", t + timedelta(minutes=1), b.u(40, 120), b.u(30, 120))
        b.add("M-502", "MTR-TRIP-OL", t + timedelta(minutes=2), b.u(40, 120), b.u(30, 180))
        if b.rng.random() < 0.5:
            b.add("M-501", "MTR-PHASE-IMB", t, b.u(1, 4), b.u(60, 200))
    for _ in range(6):
        b.add("M-503", "MTR-WDG-TEMP-H", b.start + timedelta(days=b.u(10, 180)), b.u(30, 120), b.u(60, 400))
    b.add("M-503", "MTR-WDG-TEMP-HH", b.anchor - timedelta(days=41), 80, 50)
    # Active now: a fresh bus event.
    b.add("TR-501", "TR-VOLT-DIP", b.minutes_ago(35), 2, 50)
    b.add("M-501", "MTR-TRIP-OL", b.minutes_ago(34), None, 90)
    b.add("M-502", "MTR-TRIP-OL", b.minutes_ago(33), None, None)


def _background(b: _Builder) -> None:
    for _ in range(10):
        b.add("CWP-301", "CWP-FLOW-L", b.start + timedelta(days=b.u(1, 182)), b.u(10, 90), b.u(60, 600))
    for _ in range(8):
        b.add("CTF-302", "CTF-VIB-H", b.start + timedelta(days=b.u(1, 182)), b.u(30, 400), b.u(300, 3000))
    for _ in range(5):
        b.add("H-401", "HTR-TEMP-H", b.start + timedelta(days=b.u(1, 182)), b.u(10, 60), b.u(30, 180))
    # Chattering nuisance alarm on P-402: many short activations, rarely acknowledged.
    for week in (150, 95, 40):
        t = b.anchor - timedelta(days=week)
        for _ in range(b.rng.randint(8, 14)):
            b.add("P-402", "P-DISCH-P-L", t, b.u(0.2, 0.8), None if b.rng.random() < 0.85 else 45)
            t += timedelta(minutes=b.u(0.3, 0.9)) if b.rng.random() < 0.6 else timedelta(hours=b.u(2, 20))
    b.add("P-402", "P-DISCH-P-L", b.minutes_ago(50), None, None)


def generate_alarms(anchor: datetime, seed: int = 42) -> list[AlarmRecord]:
    builder = _Builder(anchor, seed)
    for scenario in (_bfp_cavitation, _bfp_current_upset, _compressors, _unit2_flood, _motors, _background):
        scenario(builder)
    rows = sorted(builder.rows, key=lambda r: (r[2], r[0], r[1]))
    return [
        AlarmRecord(f"ALM-{i:06d}", asset, code, start, end, ack, value)
        for i, (asset, code, start, end, ack, value) in enumerate(rows, start=1)
    ]
