"""One aggregate weighing against the planned target."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    code: str
    limit: float
    category: str
    version: int
    published_tick: int
    effective_tick: int
    effective_policy: str

    def describe(self) -> dict[str, Any]:
        return {
            "name": "scale_deviation",
            "bin": self.bin_name,
            "material": self.material,
            "target_kg": self.target_kg,
            "actual_kg": self.actual_kg,
            "deviation_percent": self.deviation_percent,
            "ok": self.ok,
            "code": self.code,
            "limit": self.limit,
            "category": self.category,
            "threshold_version": self.version,
            "published_tick": self.published_tick,
            "effective_tick": self.effective_tick,
            "effective_policy": self.effective_policy,
            "tolerance_percent": self.limit,
        }


def weigh(
    *,
    bin_name: str,
    material: str,
    target_kg: float,
    actual_kg: float,
    tolerance_percent: float,
    category: str = "quality",
    version: int = 1,
    published_tick: int = 0,
    effective_tick: int = 0,
    effective_policy: str = "next_day",
) -> WeightReading:
    """Build the reading for one weighing."""

    require_positive(actual_kg, field="actual_kg")
    deviation = deviation_percent(actual_kg, require_positive(target_kg, field="target_kg"))
    ok = within_tolerance(deviation, tolerance_percent)
    return WeightReading(
        bin_name=bin_name,
        material=material,
        target_kg=round(target_kg, 4),
        actual_kg=round(actual_kg, 4),
        deviation_percent=deviation,
        ok=ok,
        code="ok" if ok else "over_limit",
        limit=tolerance_percent,
        category=category,
        version=version,
        published_tick=published_tick,
        effective_tick=effective_tick,
        effective_policy=effective_policy,
    )


def reading_from_payload(payload: Any) -> WeightReading:
    """Rebuild a reading from a stored payload."""

    if payload is None:
        raise NotFoundError("no weighing was recorded")
    limit = float(payload.get("limit", payload.get("tolerance_percent", 0.0)))
    return WeightReading(
        bin_name=str(payload.get("bin", "")),
        material=str(payload.get("material", "")),
        target_kg=float(payload.get("target_kg", 0.0)),
        actual_kg=float(payload.get("actual_kg", 0.0)),
        deviation_percent=float(payload.get("deviation_percent", 0.0)),
        ok=bool(payload.get("ok", False)),
        code=str(payload.get("code", "ok" if payload.get("ok", False) else "over_limit")),
        limit=limit,
        category=str(payload.get("category", "quality")),
        version=int(payload.get("threshold_version", payload.get("version", 1))),
        published_tick=int(payload.get("published_tick", 0)),
        effective_tick=int(payload.get("effective_tick", 0)),
        effective_policy=str(payload.get("effective_policy", "next_day")),
    )
