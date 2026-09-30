"""The moisture bands a reading falls into."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, TYPE_CHECKING, overload

if TYPE_CHECKING:
    from ..config import Limits

from ..decision.thresholds import Threshold


class MoistureMode(str, Enum):
    """How much free water the aggregate currently carries."""

    DRY = "dry"
    WET = "wet"
    SATURATED = "saturated"


@dataclass(frozen=True, slots=True)
class MoistureClassification:
    """A moisture reading and the immutable ceiling used to classify it."""

    percent: float
    mode: MoistureMode
    threshold: Threshold

    def describe(self) -> dict[str, Any]:
        return {
            "mode": str(self.mode.value),
            "percent": self.percent,
            "ceiling_percent": self.threshold.limit,
            "ok": self.percent < self.threshold.limit if self.percent > 0 else True,
            "code": "ok" if self.percent < self.threshold.limit or self.percent <= 0 else "over_limit",
            "limit": self.threshold.limit,
            "category": self.threshold.category,
            "threshold_version": self.threshold.version,
            "published_tick": self.threshold.published_tick,
            "effective_tick": self.threshold.effective_tick,
            "effective_policy": self.threshold.effective_policy,
        }


def classify_moisture(percent: float, threshold: Threshold) -> MoistureClassification:
    """Classify ``percent`` against the threshold in force for that reading."""

    if percent <= 0.0:
        mode = MoistureMode.DRY
    elif percent >= threshold.limit:
        mode = MoistureMode.SATURATED
    else:
        mode = MoistureMode.WET
    return MoistureClassification(percent=percent, mode=mode, threshold=threshold)


@overload
def mode_for(percent: float, threshold: Threshold) -> MoistureMode: ...


@overload
def mode_for(percent: float, threshold: "Limits") -> MoistureMode: ...


def mode_for(percent: float, threshold: Threshold | "Limits") -> MoistureMode:
    """Return only the mode for callers that do not persist the verdict."""

    if not isinstance(threshold, Threshold):
        threshold = Threshold("moisture", threshold.moisture_max_percent, "max", "%", "quality")
    return classify_moisture(percent, threshold).mode
