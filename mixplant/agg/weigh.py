"""One aggregate weighing against the planned target."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..decision.thresholds import Verdict, verdict_from_payload
from ..errors import NotFoundError
from .scale import deviation_percent, require_positive, within_tolerance


@dataclass(frozen=True, slots=True)
class WeightReading:
    """The mass one bin put on the scale together with its verdict."""

    bin_name: str
    material: str
    target_kg: float
    actual_kg: float
    deviation_percent: float
    ok: bool
    verdict: Verdict | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "bin": self.bin_name,
            "material": self.material,
            "target_kg": self.target_kg,
            "actual_kg": self.actual_kg,
            "deviation_percent": self.deviation_percent,
            "ok": self.ok,
            "verdict": None if self.verdict is None else self.verdict.describe(),
        }


def weigh(
    *,
    bin_name: str,
    material: str,
    target_kg: float,
    actual_kg: float,
    tolerance_percent: float,
    verdict: Verdict | None = None,
) -> WeightReading:
    """Build the reading for one weighing."""

    require_positive(actual_kg, field="actual_kg")
    deviation = deviation_percent(actual_kg, require_positive(target_kg, field="target_kg"))
    ok = within_tolerance(deviation, tolerance_percent)
    if verdict is not None and verdict.ok != ok:
        # The versioned book is the source of truth; keep the two in step.
        ok = verdict.ok
    return WeightReading(
        bin_name=bin_name,
        material=material,
        target_kg=round(target_kg, 4),
        actual_kg=round(actual_kg, 4),
        deviation_percent=deviation,
        ok=ok,
        verdict=verdict,
    )


def reading_from_payload(payload: Any) -> WeightReading:
    """Rebuild a reading from a stored payload."""

    if payload is None:
        raise NotFoundError("no weighing was recorded")
    return WeightReading(
        bin_name=str(payload.get("bin", "")),
        material=str(payload.get("material", "")),
        target_kg=float(payload.get("target_kg", 0.0)),
        actual_kg=float(payload.get("actual_kg", 0.0)),
        deviation_percent=float(payload.get("deviation_percent", 0.0)),
        ok=bool(payload.get("ok", False)),
        verdict=verdict_from_payload(payload.get("verdict")),
    )
