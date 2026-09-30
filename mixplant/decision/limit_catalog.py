"""Versioned threshold catalog and effective-time selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from ..config import Limits
from ..errors import ValidationError
from .thresholds import MAX, MIN, Threshold, ThresholdSet, Verdict

PUBLISH_EFFECTIVE = "immediate"
NEXT_DAY_EFFECTIVE = "next_day"
EFFECTIVE_POLICIES = (PUBLISH_EFFECTIVE, NEXT_DAY_EFFECTIVE)

DEFAULT_DAY_TICKS = 24

THRESHOLD_SPECS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("moisture", "moisture_max_percent", "quality", MAX, "%", "moisture"),
    ("scale_deviation", "scale_tolerance_percent", "quality", MAX, "%", "scale"),
    ("cement_flow", "cement_flow_max_kgs", "safety", MAX, "kg/s", "cement"),
    ("water_flow", "water_flow_max_lps", "safety", MAX, "L/s", "water"),
    ("hopper_residual", "hopper_residual_max_kg", "safety", MAX, "kg", "hopper"),
    ("pump_pressure", "pump_pressure_max_mpa", "safety", MAX, "MPa", "pump"),
    ("prime_water", "prime_water_min_l", "safety", MIN, "L", "water"),
)

THRESHOLD_NAMES = tuple(name for name, _field, _category, _direction, _unit, _key in THRESHOLD_SPECS)
CATEGORY_POLICY = {
    "safety": PUBLISH_EFFECTIVE,
    "quality": NEXT_DAY_EFFECTIVE,
}
POLICY_CATEGORY = {
    PUBLISH_EFFECTIVE: "safety",
    NEXT_DAY_EFFECTIVE: "quality",
}


@dataclass(frozen=True, slots=True)
class ThresholdRevision:
    """One immutable value for a threshold category."""

    name: str
    category: str
    version: int
    limit: float
    direction: str
    unit: str
    published_tick: int
    effective_tick: int
    effective_policy: str
    effective_seq: int = 0
    migration: bool = False

    def threshold(self) -> Threshold:
        return Threshold(
            self.name,
            self.limit,
            self.direction,
            self.unit,
            version=self.version,
            category=self.category,
            published_tick=self.published_tick,
            effective_tick=self.effective_tick,
            effective_policy=self.effective_policy,
            migration=self.migration,
            effective_seq=self.effective_seq,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "version": self.version,
            "limit": self.limit,
            "direction": self.direction,
            "unit": self.unit,
            "published_tick": self.published_tick,
            "effective_tick": self.effective_tick,
            "effective_policy": self.effective_policy,
            "effective_seq": self.effective_seq,
            "migration": self.migration,
        }


def next_day_tick(published_tick: int, *, day_ticks: int = DEFAULT_DAY_TICKS) -> int:
    """Return the first tick of the next deterministic production day."""

    if published_tick < 0:
        raise ValidationError("published tick must not be negative", tick=published_tick)
    if day_ticks < 1:
        raise ValidationError("a production day must contain at least one tick", day_ticks=day_ticks)
    return (published_tick // day_ticks + 1) * day_ticks


def effective_tick_for(category: str, published_tick: int, *, day_ticks: int) -> int:
    """Apply the effective-time policy owned by a threshold category."""

    policy = CATEGORY_POLICY.get(category)
    if policy is None:
        raise ValidationError("unknown threshold category", category=category)
    if policy == PUBLISH_EFFECTIVE:
        return published_tick
    return next_day_tick(published_tick, day_ticks=day_ticks)


def revision_payload(revision: ThresholdRevision) -> dict[str, Any]:
    """Build the persistent payload for one threshold revision."""

    return {"active": True, **revision.describe()}


def revision_from_payload(payload: Mapping[str, Any]) -> ThresholdRevision:
    """Rebuild one immutable revision from a journal payload."""

    return ThresholdRevision(
        name=str(payload["name"]),
        category=str(payload["category"]),
        version=int(payload["version"]),
        limit=float(payload["limit"]),
        direction=str(payload["direction"]),
        unit=str(payload.get("unit", "")),
        published_tick=int(payload["published_tick"]),
        effective_tick=int(payload["effective_tick"]),
        effective_policy=str(payload["effective_policy"]),
        effective_seq=int(payload.get("effective_seq", 0)),
        migration=bool(payload.get("migration", False)),
    )


def baseline_revisions(limits: Limits) -> tuple[ThresholdRevision, ...]:
    """Build the v1 catalog migrated from static configuration."""

    revisions: list[ThresholdRevision] = []
    for name, field_name, category, direction, unit, _key in THRESHOLD_SPECS:
        revisions.append(
            ThresholdRevision(
                name=name,
                category=category,
                version=1,
                limit=float(getattr(limits, field_name)),
                direction=direction,
                unit=unit,
                published_tick=0,
                effective_tick=0,
                effective_policy=CATEGORY_POLICY[category],
                migration=True,
            )
        )
    return tuple(revisions)


def _latest_before(
    revisions: Sequence[ThresholdRevision], tick: int, seq: int | None = None
) -> ThresholdRevision:
    eligible = [
        revision
        for revision in revisions
        if revision.effective_tick < tick
        or (revision.effective_tick == tick and (seq is None or revision.effective_seq <= seq))
    ]
    if not eligible:
        raise ValidationError("no threshold revision is effective at the requested tick", tick=tick, seq=seq)
    return max(
        eligible,
        key=lambda revision: (revision.effective_tick, revision.effective_seq, revision.version),
    )


def _payload_reading(name: str, payload: Mapping[str, Any]) -> float:
    keys = {
        "moisture": ("percent",),
        "scale_deviation": ("deviation_percent",),
        "cement_flow": ("rate_kgs",),
        "water_flow": ("rate_lps",),
        "hopper_residual": ("residual_kg",),
        "pump_pressure": ("reading_mpa",),
        "prime_water": ("litres",),
    }
    for key in keys.get(name, ("reading",)):
        value = payload.get(key)
        if value is not None:
            return float(value)
    return float(payload.get("reading", 0.0))


class ThresholdRegistry:
    """Keeps every threshold revision and selects the version in force."""

    __slots__ = ("_revisions", "_day_ticks")

    def __init__(self, *, day_ticks: int = DEFAULT_DAY_TICKS) -> None:
        self._revisions: dict[str, list[ThresholdRevision]] = {name: [] for name in THRESHOLD_NAMES}
        self._day_ticks = day_ticks

    @classmethod
    def from_limits(
        cls, limits: Limits, *, day_ticks: int = DEFAULT_DAY_TICKS, now: int = 0
    ) -> "ThresholdRegistry":
        registry = cls(day_ticks=day_ticks)
        registry.adopt_many(baseline_revisions(limits), published_tick=now)
        return registry

    def adopt_many(
        self, revisions: Sequence[ThresholdRevision], *, published_tick: int | None = None
    ) -> None:
        for revision in revisions:
            self.adopt(revision, published_tick=published_tick)

    def adopt(
        self, revision: ThresholdRevision, *, published_tick: int | None = None
    ) -> ThresholdRevision:
        """Adopt a revision restored from the journal."""

        self._require_known(revision.name)
        history = self._revisions[revision.name]
        if history and revision.version <= max(item.version for item in history):
            return revision
        if published_tick is not None and revision.published_tick > published_tick:
            raise ValidationError(
                "a threshold revision cannot be published after the record that carries it",
                published_tick=revision.published_tick,
                record_tick=published_tick,
            )
        history.append(revision)
        history.sort(key=lambda item: (item.effective_tick, item.effective_seq, item.version))
        return revision

    def publish(self, name: str, limit: float, *, tick: int, seq: int) -> ThresholdRevision:
        """Publish a value under the policy configured for its category."""

        revision = self._revision(name, limit, tick=tick, seq=seq)
        self.adopt(revision, published_tick=tick)
        return revision

    def draft(self, name: str, limit: float, *, tick: int, seq: int) -> ThresholdRevision:
        """Build a revision without installing it before its journal commit."""

        return self._revision(name, limit, tick=tick, seq=seq)

    def _revision(self, name: str, limit: float, *, tick: int, seq: int) -> ThresholdRevision:
        if limit < 0:
            raise ValidationError("a threshold limit must not be negative", name=name, limit=limit)
        if seq < 1:
            raise ValidationError("a published threshold needs a positive record sequence", seq=seq)
        history = self._history(name)
        latest = max(history, key=lambda revision: revision.version)
        category = latest.category
        effective_tick = effective_tick_for(category, tick, day_ticks=self._day_ticks)
        revision = ThresholdRevision(
            name=name,
            category=category,
            version=latest.version + 1,
            limit=limit,
            direction=latest.direction,
            unit=latest.unit,
            published_tick=tick,
            effective_tick=effective_tick,
            effective_policy=CATEGORY_POLICY[category],
            effective_seq=seq,
        )
        return revision

    def names(self) -> tuple[str, ...]:
        return tuple(THRESHOLD_NAMES)

    def _history(self, name: str) -> tuple[ThresholdRevision, ...]:
        self._require_known(name)
        return tuple(self._revisions[name])

    def require_revision(self, name: str, tick: int, seq: int | None = None) -> ThresholdRevision:
        return _latest_before(self._history(name), tick, seq)

    def revision(self, name: str, tick: int, seq: int | None = None) -> ThresholdRevision | None:
        history = self._history(name)
        try:
            return _latest_before(history, tick, seq)
        except ValidationError:
            return None

    def explain_verdict(self, name: str, reading: float, tick: int, seq: int | None = None) -> Verdict:
        """Evaluate a historical reading with the revision in force at ``tick``."""

        return self.require_revision(name, tick, seq).threshold().evaluate(reading)

    def verify_payload(self, payload: Mapping[str, Any], *, tick: int | None = None) -> dict[str, Any]:
        """Check that a stored verdict still matches its recorded limit version."""

        name = str(payload.get("name", ""))
        tick_value = int(payload.get("tick", tick if tick is not None else 0))
        seq_value = payload.get("seq")
        revision = self.require_revision(
            name, tick_value, None if seq_value in (None, "") else int(seq_value)
        )
        recorded_version = int(payload.get("threshold_version", payload.get("version", 0)))
        recorded_limit = float(payload.get("limit", payload.get("tolerance_percent", 0.0)))
        reading = _payload_reading(name, payload)
        verdict = revision.threshold().evaluate(reading)
        return {
            "name": name,
            "tick": tick,
            "matches": (
                revision.version == recorded_version
                and revision.limit == recorded_limit
                and verdict.ok == bool(payload.get("ok"))
                and verdict.code == str(payload.get("code"))
            ),
            "recorded_version": recorded_version,
            "explained_version": revision.version,
            "recorded_limit": recorded_limit,
            "explained_limit": revision.limit,
            "recorded_code": payload.get("code"),
            "explained_code": verdict.code,
        }

    def active_cursor(self, tick: int) -> tuple[int, int]:
        """Return the newest effective point at ``tick``."""

        points = [
            (revision.effective_tick, revision.effective_seq)
            for history in self._revisions.values()
            for revision in history
            if revision.effective_tick < tick
            or (revision.effective_tick == tick and revision.effective_seq > 0)
        ]
        if not points:
            return (tick, 0)
        return max(points)

    def active_set(self, tick: int) -> ThresholdSet:
        cursor_tick, cursor_seq = self.active_cursor(tick)
        return ThresholdSet(
            {
                name: self.require_revision(name, cursor_tick, cursor_seq).threshold()
                for name in THRESHOLD_NAMES
            }
        )

    def pending(self, tick: int) -> tuple[ThresholdRevision, ...]:
        pending = [
            revision
            for history in self._revisions.values()
            for revision in history
            if revision.published_tick <= tick < revision.effective_tick
        ]
        return tuple(sorted(pending, key=lambda revision: (revision.effective_tick, revision.name)))

    def versions(self) -> dict[str, list[dict[str, Any]]]:
        return {
            name: [revision.describe() for revision in self._revisions[name]]
            for name in THRESHOLD_NAMES
        }

    def describe(self, tick: int, seq: int | None = None) -> dict[str, Any]:
        return {
            "current": {
                name: self.require_revision(name, tick, seq).describe()
                for name in THRESHOLD_NAMES
            },
            "pending": [revision.describe() for revision in self.pending(tick)],
            "versions": self.versions(),
            "policies": dict(CATEGORY_POLICY),
            "day_ticks": self._day_ticks,
        }

    def _require_known(self, name: str) -> None:
        if name not in self._revisions:
            raise ValidationError("unknown threshold", name=name, known=list(THRESHOLD_NAMES))
