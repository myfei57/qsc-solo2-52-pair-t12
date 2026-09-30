"""Versioned process limits.

Every limit category carries an append only chain of revisions.  A revision
records when it was published and when it takes effect, so a reading can be
judged against *the revision that was in force when the reading happened*
rather than against whatever value is current today.

Two activation modes are supported, fixed per category:

* ``IMMEDIATE`` categories switch over the moment the revision is published
  (inside the publishing session): the effective tick equals the publish tick.
* ``NEXT_DAY`` categories are migration style changes: a revision published
  during a production day only takes effect at the first tick of the next
  production day, so a session can never re-judge readings it already made.

The chain itself is append only.  Old revisions are never dropped or mutated,
which is what lets the real time decision layer, the replay path and the
audit view explain any historical verdict with the exact same numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..errors import NotFoundError, ValidationError
from .thresholds import MAX, MIN, Threshold, Verdict

IMMEDIATE = "immediate"
NEXT_DAY = "next_day"
ACTIVATIONS = (IMMEDIATE, NEXT_DAY)

#: How many ticks one production day lasts.
TICKS_PER_DAY = 24

#: Fixed activation policy of every limit category.
LIMIT_ACTIVATION: Mapping[str, str] = {
    "moisture": IMMEDIATE,
    "scale_deviation": IMMEDIATE,
    "cement_flow": IMMEDIATE,
    "water_flow": IMMEDIATE,
    "hopper_residual": IMMEDIATE,
    "pump_pressure": IMMEDIATE,
    "prime_water": NEXT_DAY,
}


def next_day_start(tick: int) -> int:
    """Return the first tick of the production day after ``tick``."""

    if tick < 0:
        raise ValidationError("tick must not be negative", tick=tick)
    return (tick // TICKS_PER_DAY + 1) * TICKS_PER_DAY


def effective_tick_for(activation: str, published_tick: int) -> int:
    """Return when a revision published at ``published_tick`` takes effect."""

    if activation == IMMEDIATE:
        return published_tick
    if activation == NEXT_DAY:
        return next_day_start(published_tick)
    raise ValidationError("activation must be immediate or next_day", activation=activation)


@dataclass(frozen=True, slots=True)
class LimitRevision:
    """One immutable version of one limit category."""

    category: str
    revision: int
    limit: float
    direction: str
    unit: str
    activation: str
    published_tick: int
    effective_tick: int
    backdated: bool = False

    def __post_init__(self) -> None:
        if not self.category:
            raise ValidationError("limit category must not be empty")
        if self.revision < 1:
            raise ValidationError("limit revision starts at one", revision=self.revision)
        if self.direction not in (MAX, MIN):
            raise ValidationError("limit direction must be max or min", direction=self.direction)
        if self.activation not in ACTIVATIONS:
            raise ValidationError("unknown limit activation", activation=self.activation)
        if self.published_tick < 0:
            raise ValidationError("published tick must not be negative", published_tick=self.published_tick)
        if not self.backdated and self.effective_tick < self.published_tick:
            raise ValidationError(
                "a limit cannot take effect before it is published",
                published_tick=self.published_tick,
                effective_tick=self.effective_tick,
            )
        if self.backdated and self.effective_tick > self.published_tick:
            raise ValidationError(
                "a backdated migration must take effect no later than its publish tick",
                published_tick=self.published_tick,
                effective_tick=self.effective_tick,
            )

    @property
    def threshold(self) -> Threshold:
        return Threshold(self.category, self.limit, self.direction, self.unit)

    def in_force(self, tick: int) -> bool:
        """Return whether this revision governs readings at ``tick``."""

        return tick >= self.effective_tick

    def evaluate(self, reading: float) -> Verdict:
        """Judge ``reading`` against this frozen revision."""

        verdict = self.threshold.evaluate(reading)
        return Verdict(
            name=verdict.name,
            reading=verdict.reading,
            limit=verdict.limit,
            direction=verdict.direction,
            ok=verdict.ok,
            code=verdict.code,
            revision=self.revision,
            effective_tick=self.effective_tick,
            evaluated_tick=None,
        )

    def stamp(self, reading: float, tick: int) -> Verdict:
        """Judge ``reading`` at ``tick`` and record the tick on the verdict."""

        verdict = self.evaluate(reading)
        return verdict.with_tick(tick)

    def describe(self, *, now: int | None = None) -> dict[str, Any]:
        return {
            "category": self.category,
            "revision": self.revision,
            "limit": self.limit,
            "direction": self.direction,
            "unit": self.unit,
            "activation": self.activation,
            "published_tick": self.published_tick,
            "effective_tick": self.effective_tick,
            "backdated": self.backdated,
            "in_force": None if now is None else self.in_force(now),
        }

    def to_document(self) -> dict[str, Any]:
        """Serialise the revision for the append only stream."""

        return {
            "category": self.category,
            "revision": self.revision,
            "limit": self.limit,
            "direction": self.direction,
            "unit": self.unit,
            "activation": self.activation,
            "published_tick": self.published_tick,
            "effective_tick": self.effective_tick,
            "backdated": self.backdated,
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "LimitRevision":
        """Rebuild a revision read back from the stream after a restart."""

        return cls(
            category=str(document["category"]),
            revision=int(document["revision"]),
            limit=float(document["limit"]),
            direction=str(document["direction"]),
            unit=str(document.get("unit", "")),
            activation=str(document["activation"]),
            published_tick=int(document["published_tick"]),
            effective_tick=int(document["effective_tick"]),
            backdated=bool(document.get("backdated", False)),
        )


class LimitBook:
    """The versioned limits every reading is judged against.

    Revisions are kept oldest first per category.  Lookups are point in time
    queries: ``revision_in_force(category, tick)`` returns the newest
    revision whose effective tick is not later than ``tick``.
    """

    __slots__ = ("_revisions",)

    def __init__(self, revisions: Mapping[str, list[LimitRevision]] | None = None) -> None:
        self._revisions: dict[str, list[LimitRevision]] = {}
        if revisions:
            for category, chain in revisions.items():
                self._revisions[category] = sorted(chain, key=lambda item: item.revision)

    # -- construction -----------------------------------------------------

    @classmethod
    def seed(cls, seed: Mapping[str, Any], *, tick: int = 0) -> "LimitBook":
        """Build the revision 1 chain from the configured limits."""

        book = cls()
        for category, spec in seed.items():
            activation = cls._activation(category)
            book._adopt(
                LimitRevision(
                    category=category,
                    revision=1,
                    limit=float(spec["limit"]),
                    direction=str(spec.get("direction", MAX)),
                    unit=str(spec.get("unit", "")),
                    activation=activation,
                    published_tick=tick,
                    effective_tick=tick,
                )
            )
        return book

    @staticmethod
    def _activation(category: str) -> str:
        activation = LIMIT_ACTIVATION.get(category)
        if activation is None:
            raise ValidationError("unknown limit category", category=category)
        return activation

    # -- mutation ---------------------------------------------------------

    def publish(self, category: str, limit: float, *, tick: int) -> LimitRevision:
        """Append a new revision; its effective tick follows the category."""

        activation = self._activation(category)
        current = self.latest(category)
        direction = current.direction
        unit = current.unit
        revision = LimitRevision(
            category=category,
            revision=current.revision + 1,
            limit=float(limit),
            direction=direction,
            unit=unit,
            activation=activation,
            published_tick=tick,
            effective_tick=effective_tick_for(activation, tick),
        )
        self._adopt(revision)
        return revision

    def adopt(self, revision: LimitRevision) -> LimitRevision:
        """Adopt a revision read back from the stream after a restart."""

        expected = LIMIT_ACTIVATION.get(revision.category)
        if expected is not None and revision.activation != expected:
            raise ValidationError(
                "a limit revision changed the fixed activation of its category",
                category=revision.category,
                activation=revision.activation,
                expected=expected,
            )
        return self._adopt(revision)

    def _adopt(self, revision: LimitRevision) -> LimitRevision:
        chain = self._revisions.setdefault(revision.category, [])
        if any(existing.revision == revision.revision for existing in chain):
            raise ValidationError(
                "limit revision was reused",
                category=revision.category,
                revision=revision.revision,
            )
        chain.append(revision)
        chain.sort(key=lambda item: item.revision)
        return revision

    # -- queries ----------------------------------------------------------

    def categories(self) -> tuple[str, ...]:
        return tuple(sorted(self._revisions))

    def history(self, category: str) -> tuple[LimitRevision, ...]:
        """Return every revision of ``category`` oldest first."""

        self._require_category(category)
        return tuple(self._revisions[category])

    def latest(self, category: str) -> LimitRevision:
        """Return the highest numbered revision, even before it takes effect."""

        self._require_category(category)
        return self._revisions[category][-1]

    def current(self, category: str, *, now: int) -> LimitRevision:
        """Return the revision governing new readings at ``now``."""

        return self.revision_in_force(category, now)

    def revision_in_force(self, category: str, tick: int) -> LimitRevision:
        """Return the revision that governed ``category`` at ``tick``."""

        self._require_category(category)
        in_force = [revision for revision in self._revisions[category] if revision.in_force(tick)]
        if not in_force:
            raise NotFoundError(
                "no limit revision was in force at that tick", category=category, tick=tick
            )
        return in_force[-1]

    def pending(self, *, now: int) -> tuple[LimitRevision, ...]:
        """Return published revisions that have not taken effect yet."""

        pending = [
            revision
            for chain in self._revisions.values()
            for revision in chain
            if revision.published_tick <= now and revision.effective_tick > now
        ]
        return tuple(sorted(pending, key=lambda item: (item.effective_tick, item.category)))

    def evaluate(self, category: str, reading: float, *, tick: int) -> Verdict:
        """Judge ``reading`` against the revision in force at ``tick``."""

        return self.revision_in_force(category, tick).stamp(reading, tick)

    def re_evaluate(self, verdict: Verdict) -> Verdict:
        """Re-judge a stored verdict with the exact revision it names.

        The live path, replay and the audit view all call this when they have
        to explain an old result: by resolving the named revision instead of
        the current one, a later limit change cannot rewrite the past.
        """

        revision = self.revision(verdict.name, verdict.revision)
        tick = verdict.evaluated_tick
        fresh = revision.evaluate(verdict.reading) if tick is None else revision.stamp(verdict.reading, tick)
        return fresh

    def revision(self, category: str, revision: int) -> LimitRevision:
        """Return one specific revision by number."""

        self._require_category(category)
        for entry in self._revisions[category]:
            if entry.revision == revision:
                return entry
        raise NotFoundError(
            "limit revision does not exist", category=category, revision=revision
        )

    # -- views ------------------------------------------------------------

    def describe(self, *, now: int) -> dict[str, Any]:
        return {
            "ticks_per_day": TICKS_PER_DAY,
            "current": {
                category: self.revision_in_force(category, now).describe(now=now)
                for category in self.categories()
            },
            "pending": [revision.describe(now=now) for revision in self.pending(now=now)],
        }

    def _require_category(self, category: str) -> None:
        if category not in self._revisions:
            raise ValidationError(
                "unknown limit category", category=category, known=list(self.categories())
            )
