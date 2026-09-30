"""The delivery pressure reading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..decision.thresholds import ThresholdSet, Verdict
from ..errors import ValidationError


@dataclass(frozen=True, slots=True)
class PressureReading:
    """One pressure reading together with its verdict."""

    reading_mpa: float
    verdict: Verdict

    @property
    def ok(self) -> bool:
        return self.verdict.ok

    @property
    def code(self) -> str:
        return self.verdict.code

    def describe(self) -> dict[str, Any]:
        return {"active": True, "reading_mpa": self.reading_mpa, **self.verdict.describe()}


def pressure_reading(*, thresholds: ThresholdSet, reading_mpa: float) -> PressureReading:
    """Check a delivery pressure against the configured ceiling."""

    if reading_mpa < 0:
        raise ValidationError("pressure must not be negative", reading_mpa=reading_mpa)
    verdict = thresholds.evaluate("pump_pressure", reading_mpa)
    return PressureReading(reading_mpa=round(reading_mpa, 4), verdict=verdict)
