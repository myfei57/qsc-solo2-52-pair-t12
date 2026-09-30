"""The delivery pressure reading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..decision.limitbook import LimitBook
from ..decision.thresholds import Verdict
from ..errors import ValidationError


@dataclass(frozen=True, slots=True)
class PressureReading:
    """One pressure reading together with its verdict."""

    reading_mpa: float
    ok: bool
    code: str
    verdict: Verdict | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "active": True,
            "reading_mpa": self.reading_mpa,
            "ok": self.ok,
            "code": self.code,
            "verdict": None if self.verdict is None else self.verdict.describe(),
        }


def pressure_reading(*, limits: LimitBook, reading_mpa: float, tick: int) -> PressureReading:
    """Check a delivery pressure against the ceiling in force at ``tick``."""

    if reading_mpa < 0:
        raise ValidationError("pressure must not be negative", reading_mpa=reading_mpa)
    verdict = limits.evaluate("pump_pressure", reading_mpa, tick=tick)
    return PressureReading(
        reading_mpa=round(reading_mpa, 4), ok=verdict.ok, code=verdict.code, verdict=verdict
    )
