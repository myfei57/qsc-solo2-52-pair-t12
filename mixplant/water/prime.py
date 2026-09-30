"""The prime water a pump needs before it may start."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..decision.limitbook import LimitBook
from ..decision.thresholds import Verdict
from ..errors import ValidationError


@dataclass(frozen=True, slots=True)
class PrimeReading:
    """How much priming water was confirmed for the delivery line."""

    litres: float
    ok: bool
    code: str
    verdict: Verdict | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "active": True,
            "litres": self.litres,
            "ok": self.ok,
            "code": self.code,
            "verdict": None if self.verdict is None else self.verdict.describe(),
        }


def prime_reading(*, limits: LimitBook, litres: float, tick: int) -> PrimeReading:
    """Check the priming volume against the floor in force at ``tick``."""

    if litres < 0:
        raise ValidationError("priming volume must not be negative", litres=litres)
    verdict = limits.evaluate("prime_water", litres, tick=tick)
    return PrimeReading(litres=round(litres, 4), ok=verdict.ok, code=verdict.code, verdict=verdict)
