"""Named bounds that readings are checked against."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..config import Limits
from ..errors import BelowLimitError, OverLimitError, ValidationError

MAX = "max"
MIN = "min"
DIRECTIONS = (MAX, MIN)


def limit_catalog(limits: Limits) -> dict[str, dict[str, Any]]:
    """Describe the standard bound categories as a version independent catalog.

    The catalog fixes each category's name, direction and unit.  Only the
    numeric bound changes between revisions.
    """

    return {
        "moisture": {"limit": limits.moisture_max_percent, "direction": MAX, "unit": "%"},
        "scale_deviation": {"limit": limits.scale_tolerance_percent, "direction": MAX, "unit": "%"},
        "cement_flow": {"limit": limits.cement_flow_max_kgs, "direction": MAX, "unit": "kg/s"},
        "water_flow": {"limit": limits.water_flow_max_lps, "direction": MAX, "unit": "L/s"},
        "hopper_residual": {"limit": limits.hopper_residual_max_kg, "direction": MAX, "unit": "kg"},
        "pump_pressure": {"limit": limits.pump_pressure_max_mpa, "direction": MAX, "unit": "MPa"},
        "prime_water": {"limit": limits.prime_water_min_l, "direction": MIN, "unit": "L"},
    }


@dataclass(frozen=True, slots=True)
class Verdict:
    """The outcome of checking one reading against one bound.

    When the verdict came from the versioned :class:`~.limitbook.LimitBook`,
    ``revision`` names the exact bound version that was applied and
    ``effective_tick`` says when that version took effect.  The pair is the
    anchor every later explanation of the result uses, so changing the limit
    afterwards can never silently re-judge an old reading.
    """

    name: str
    reading: float
    limit: float
    direction: str
    ok: bool
    code: str
    revision: int | None = None
    effective_tick: int | None = None
    evaluated_tick: int | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "reading": self.reading,
            "limit": self.limit,
            "direction": self.direction,
            "ok": self.ok,
            "code": self.code,
            "revision": self.revision,
            "effective_tick": self.effective_tick,
            "evaluated_tick": self.evaluated_tick,
        }

    def with_tick(self, tick: int) -> "Verdict":
        """Return a copy that records the tick the reading was taken at."""

        return Verdict(
            name=self.name,
            reading=self.reading,
            limit=self.limit,
            direction=self.direction,
            ok=self.ok,
            code=self.code,
            revision=self.revision,
            effective_tick=self.effective_tick,
            evaluated_tick=tick,
        )

    @property
    def is_versioned(self) -> bool:
        """Return whether the verdict names the limit revision it used."""

        return self.revision is not None


@dataclass(frozen=True, slots=True)
class Threshold:
    """One named bound together with the direction it refuses from."""

    name: str
    limit: float
    direction: str = MAX
    unit: str = ""

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise ValidationError("threshold direction must be max or min", direction=self.direction)

    def evaluate(self, reading: float) -> Verdict:
        """Return the verdict for ``reading`` without raising."""

        if self.direction == MAX:
            ok = reading <= self.limit
            code = "ok" if ok else "over_limit"
        else:
            ok = reading >= self.limit
            code = "ok" if ok else "below_limit"
        return Verdict(
            name=self.name,
            reading=reading,
            limit=self.limit,
            direction=self.direction,
            ok=ok,
            code=code,
        )

    def require(self, reading: float) -> Verdict:
        """Return the verdict or raise the limit error it maps to."""

        verdict = self.evaluate(reading)
        if verdict.ok:
            return verdict
        if self.direction == MAX:
            raise OverLimitError(
                "reading crossed an upper bound",
                name=self.name,
                reading=reading,
                limit=self.limit,
                unit=self.unit,
            )
        raise BelowLimitError(
            "reading dropped under a lower bound",
            name=self.name,
            reading=reading,
            limit=self.limit,
            unit=self.unit,
        )

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "limit": self.limit, "direction": self.direction, "unit": self.unit}


def verdict_from_payload(payload: Any) -> Verdict | None:
    """Rebuild the versioned verdict a stored reading carried.

    Returns ``None`` for records that predate limit versioning so old
    journals keep loading.
    """

    if not isinstance(payload, Mapping) or payload.get("revision") is None:
        return None
    return Verdict(
        name=str(payload.get("name", "")),
        reading=float(payload.get("reading", 0.0)),
        limit=float(payload.get("limit", 0.0)),
        direction=str(payload.get("direction", MAX)),
        ok=bool(payload.get("ok", False)),
        code=str(payload.get("code", "ok")),
        revision=int(payload["revision"]),
        effective_tick=(
            None if payload.get("effective_tick") is None else int(payload["effective_tick"])
        ),
        evaluated_tick=(
            None if payload.get("evaluated_tick") is None else int(payload["evaluated_tick"])
        ),
    )


class ThresholdSet:
    """Every bound the decision layer evaluates, addressed by name."""

    __slots__ = ("_entries",)

    def __init__(self, entries: Mapping[str, Threshold]) -> None:
        self._entries = dict(entries)

    @classmethod
    def from_limits(cls, limits: Limits) -> "ThresholdSet":
        """Build the standard bound set from the configured limits."""

        entries = {
            name: Threshold(name, spec["limit"], spec["direction"], spec["unit"])
            for name, spec in limit_catalog(limits).items()
        }
        return cls(entries)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def get(self, name: str) -> Threshold:
        """Return the bound called ``name`` or refuse the lookup."""

        entry = self._entries.get(name)
        if entry is None:
            raise ValidationError("unknown threshold", name=name, known=list(self.names()))
        return entry

    def evaluate(self, name: str, reading: float) -> Verdict:
        return self.get(name).evaluate(reading)

    def require(self, name: str, reading: float) -> Verdict:
        return self.get(name).require(reading)

    def describe(self) -> dict[str, Any]:
        return {name: self._entries[name].describe() for name in self.names()}
