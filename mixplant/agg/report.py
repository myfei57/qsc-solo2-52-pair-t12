"""The weight report the audit log keeps for every batch."""

from __future__ import annotations

from typing import Any, Mapping

from .weigh import WeightReading


def weight_report(
    reading: WeightReading, *, batch_id: str, version: int, threshold_version: int | None = None
) -> dict[str, Any]:
    """Build the audit report for one weighing."""

    return {
        "batch_id": batch_id,
        "version": version,
        "material": reading.material,
        "target_kg": reading.target_kg,
        "actual_kg": reading.actual_kg,
        "deviation_percent": reading.deviation_percent,
        "ok": reading.ok,
        "code": reading.code,
        "limit": reading.limit,
        "category": reading.category,
        "threshold_version": reading.version,
        "published_tick": reading.published_tick,
        "effective_tick": reading.effective_tick,
        "effective_policy": reading.effective_policy,
    }


def summarise_reports(reports: tuple[Mapping[str, Any], ...]) -> dict[str, Any]:
    """Fold several weigh reports into one summary."""

    return {
        "reports": [dict(report) for report in reports],
        "count": len(reports),
        "worst_deviation_percent": max(
            (float(report.get("deviation_percent", 0.0)) for report in reports), default=0.0
        ),
    }
