"""Metered water delivered to the mixer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..decision.limitbook import LimitBook
from ..decision.thresholds import Verdict
from ..errors import ValidationError


@dataclass(frozen=True, slots=True)
class DispenseReading:
    """One metering reading together with its verdict."""

    litres: float
    rate_lps: float
    ok: bool
    code: str
    verdict: Verdict | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "active": True,
            "litres": self.litres,
            "rate_lps": self.rate_lps,
            "ok": self.ok,
            "code": self.code,
            "verdict": None if self.verdict is None else self.verdict.describe(),
        }


def dispense_reading(*, limits: LimitBook, litres: float, rate_lps: float, tick: int) -> DispenseReading:
    """Check one metering reading against the flow ceiling in force at ``tick``."""

    if litres <= 0:
        raise ValidationError("a dispense needs a positive volume", litres=litres)
    verdict = limits.evaluate("water_flow", rate_lps, tick=tick)
    return DispenseReading(
        litres=round(litres, 4), rate_lps=round(rate_lps, 4), ok=verdict.ok, code=verdict.code, verdict=verdict
    )
