"""The moisture bands a reading falls into."""

from __future__ import annotations

from enum import Enum


class MoistureMode(str, Enum):
    """How much free water the aggregate currently carries."""

    DRY = "dry"
    WET = "wet"
    SATURATED = "saturated"


def mode_for(percent: float, ceiling: float) -> MoistureMode:
    """Classify ``percent`` against the moisture ceiling in force."""

    if percent <= 0.0:
        return MoistureMode.DRY
    if percent >= ceiling:
        return MoistureMode.SATURATED
    return MoistureMode.WET
