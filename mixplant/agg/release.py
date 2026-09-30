"""Releasing the scale hopper once a batch has been dropped."""

from __future__ import annotations

from typing import Any

from ..errors import ValidationError


def release_payload(
    *,
    residual_kg: float,
    threshold_kg: float,
    category: str = "safety",
    version: int = 1,
    published_tick: int = 0,
    effective_tick: int = 0,
    effective_policy: str = "immediate",
) -> dict[str, Any]:
    """Build the payload that closes out one batch on the scale."""

    if residual_kg < 0:
        raise ValidationError("residual mass must not be negative", residual=residual_kg)
    if threshold_kg < 0:
        raise ValidationError("residual threshold must not be negative", threshold=threshold_kg)
    clear = residual_kg <= threshold_kg
    return {
        "active": True,
        "name": "hopper_residual",
        "residual_kg": round(residual_kg, 4),
        "threshold_kg": round(threshold_kg, 4),
        "clear": clear,
        "ok": clear,
        "code": "ok" if clear else "over_limit",
        "limit": round(threshold_kg, 4),
        "category": category,
        "threshold_version": version,
        "published_tick": published_tick,
        "effective_tick": effective_tick,
        "effective_policy": effective_policy,
    }


def describe_release(payload: Any) -> dict[str, Any]:
    """Summarise the release recorded for the current batch."""

    if not isinstance(payload, dict):
        return {"released": False, "residual_kg": None, "clear": None}
    return {
        "released": bool(payload.get("active", False)),
        "residual_kg": payload.get("residual_kg"),
        "clear": payload.get("clear"),
        "ok": payload.get("ok", payload.get("clear")),
        "code": payload.get("code"),
        "threshold_kg": payload.get("threshold_kg", payload.get("limit")),
        "category": payload.get("category"),
        "threshold_version": payload.get("threshold_version", payload.get("version")),
        "published_tick": payload.get("published_tick"),
        "effective_tick": payload.get("effective_tick"),
        "effective_policy": payload.get("effective_policy"),
    }
