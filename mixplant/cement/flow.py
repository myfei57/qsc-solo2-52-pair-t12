"""The cement flow reading taken while the gate is open."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..decision.limitbook import LimitBook
from ..decision.thresholds import Verdict
from ..errors import ValidationError


@dataclass(frozen=True, slots=True)
class FlowReading:
    """The silo discharge rate together with its verdict."""

    silo: str
    rate_kgs: float
    mass_kg: float
    ok: bool
    code: str
    verdict: Verdict | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "active": True,
            "silo": self.silo,
            "rate_kgs": self.rate_kgs,
            "mass_kg": self.mass_kg,
            "ok": self.ok,
            "code": self.code,
            "verdict": None if self.verdict is None else self.verdict.describe(),
        }


def flow_reading(
    *,
    limits: LimitBook,
    silo: str,
    rate_kgs: float,
    mass_kg: float,
    tick: int,
) -> FlowReading:
    """Check the discharge rate against the ceiling in force at ``tick``."""

    if mass_kg <= 0:
        raise ValidationError("a cement flow needs a positive mass", silo=silo, mass_kg=mass_kg)
    verdict = limits.evaluate("cement_flow", rate_kgs, tick=tick)
    return FlowReading(
        silo=silo,
        rate_kgs=round(rate_kgs, 4),
        mass_kg=round(mass_kg, 4),
        ok=verdict.ok,
        code=verdict.code,
        verdict=verdict,
    )
