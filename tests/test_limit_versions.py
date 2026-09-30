"""Versioned limits: historical verdicts stay frozen when limits change.

The rule under test is that a reading is always judged against the revision
that was in force at the reading tick.  Immediate categories switch over in
the publishing session; next day categories only take effect at the first
tick of the next production day.  Stored verdicts name their revision, so
the live console, replay and the audit view explain an old decision with
the exact same numbers regardless of later changes.
"""

from __future__ import annotations

import json

import pytest

from mixplant.config import Limits, StationConfig
from mixplant.decision.limitbook import (
    IMMEDIATE,
    NEXT_DAY,
    TICKS_PER_DAY,
    LIMIT_ACTIVATION,
    LimitBook,
    LimitRevision,
    effective_tick_for,
    next_day_start,
)
from mixplant.decision.thresholds import limit_catalog, verdict_from_payload
from mixplant.errors import NotFoundError, ValidationError
from mixplant.runtime import LIMIT_KIND, PlantRuntime
from mixplant.console.pages import PageStore
from mixplant.console.router import Request
from mixplant.console.server import ConsoleServer
from tests.support import run


# ---------------------------------------------------------------- book unit


def test_seed_book_has_revision_one_for_every_category() -> None:
    book = LimitBook.seed(limit_catalog(Limits()))
    assert set(book.categories()) == set(LIMIT_ACTIVATION)
    for category in book.categories():
        revision = book.revision(category, 1)
        assert revision.revision == 1
        assert revision.effective_tick == 0
        assert revision.in_force(0)


def test_immediate_publish_takes_effect_in_the_same_session() -> None:
    assert effective_tick_for(IMMEDIATE, 7) == 7
    book = LimitBook.seed(limit_catalog(Limits()))
    revision = book.publish("pump_pressure", 12.0, tick=7)
    assert revision.effective_tick == 7
    assert book.revision_in_force("pump_pressure", 6).revision == 1
    assert book.revision_in_force("pump_pressure", 7).revision == 2


def test_next_day_publish_waits_for_the_next_production_day() -> None:
    assert next_day_start(0) == TICKS_PER_DAY
    assert next_day_start(TICKS_PER_DAY + 3) == 2 * TICKS_PER_DAY
    book = LimitBook.seed(limit_catalog(Limits()))
    revision = book.publish("prime_water", 70.0, tick=5)
    assert revision.activation == NEXT_DAY
    assert revision.effective_tick == TICKS_PER_DAY
    assert [item.category for item in book.pending(now=5)] == ["prime_water"]
    assert book.revision_in_force("prime_water", TICKS_PER_DAY - 1).revision == 1
    assert book.revision_in_force("prime_water", TICKS_PER_DAY).revision == 2


def test_an_old_tick_cannot_see_a_revision_published_later() -> None:
    book = LimitBook.seed(limit_catalog(Limits()))
    book.publish("pump_pressure", 12.0, tick=10)
    early = book.evaluate("pump_pressure", 11.0, tick=5)
    late = book.evaluate("pump_pressure", 11.0, tick=10)
    assert (early.revision, early.ok) == (1, False)
    assert (late.revision, late.ok) == (2, True)
    # Explaining the old verdict uses the revision it names, not the current one.
    replayed = book.re_evaluate(early)
    assert replayed.revision == 1 and replayed.ok is False
    assert replayed.limit == 8.0


def test_revisions_are_append_only_and_cannot_be_reused() -> None:
    book = LimitBook.seed(limit_catalog(Limits()))
    book.publish("pump_pressure", 12.0, tick=1)
    assert [item.revision for item in book.history("pump_pressure")] == [1, 2]
    duplicate = LimitRevision(
        category="pump_pressure",
        revision=2,
        limit=99.0,
        direction="max",
        unit="MPa",
        activation=IMMEDIATE,
        published_tick=2,
        effective_tick=2,
    )
    with pytest.raises(ValidationError):
        book.adopt(duplicate)


def test_activation_is_fixed_per_category() -> None:
    book = LimitBook.seed(limit_catalog(Limits()))
    forged = LimitRevision(
        category="pump_pressure",
        revision=2,
        limit=99.0,
        direction="max",
        unit="MPa",
        activation=NEXT_DAY,  # pump_pressure is an immediate category
        published_tick=2,
        effective_tick=2,
    )
    with pytest.raises(ValidationError):
        book.adopt(forged)


def test_unknown_category_is_refused() -> None:
    book = LimitBook.seed(limit_catalog(Limits()))
    with pytest.raises(ValidationError):
        book.publish("no_such_limit", 1.0, tick=1)
    with pytest.raises(NotFoundError):
        book.revision("pump_pressure", 9)


# --------------------------------------------------------------- immutability


def test_changing_a_limit_does_not_rewrite_a_past_verdict(runtime: PlantRuntime) -> None:
    run(runtime, "water.prime", {"litres": 60})
    before = runtime.records({"kind": "water.prime"})["rows"][-1]["payload"]["verdict"]
    assert before["revision"] == 1 and before["ok"] is True and before["limit"] == 40.0

    # New floor of 70 L is a next day change; it does not touch the same session.
    published = run(runtime, "limits.publish", {"category": "prime_water", "value": 70})
    assert published["revision"]["activation"] == NEXT_DAY
    assert published["revision"]["effective_tick"] == TICKS_PER_DAY

    # The old reading is still compliant when explained with its own revision.
    explained = runtime.explain_verdict(before)
    assert explained["consistent"] is True
    assert explained["explained"]["ok"] is True
    assert explained["explained"]["revision"] == 1

    # Same day readings keep using revision one.
    run(runtime, "clock.advance", {"ticks": 5})
    run(runtime, "water.prime", {"litres": 60})
    same_day = runtime.records({"kind": "water.prime"})["rows"][-1]["payload"]["verdict"]
    assert same_day["revision"] == 1 and same_day["ok"] is True

    # After the next day boundary the very same reading fails under revision two.
    run(runtime, "clock.advance", {"ticks": TICKS_PER_DAY})
    run(runtime, "water.prime", {"litres": 60})
    next_day = runtime.records({"kind": "water.prime"})["rows"][-1]["payload"]["verdict"]
    assert next_day["revision"] == 2 and next_day["ok"] is False and next_day["limit"] == 70.0

    # The first verdict still explains as a pass.
    assert runtime.explain_verdict(before)["explained"]["ok"] is True


def test_immediate_category_switches_inside_the_publishing_session(
    runtime: PlantRuntime,
) -> None:
    run(runtime, "pump.pressure", {"reading_mpa": 9.5})
    old = runtime.records({"kind": "pump.pressure"})["rows"][-1]["payload"]["verdict"]
    assert old["revision"] == 1 and old["ok"] is False

    run(runtime, "limits.publish", {"category": "pump_pressure", "value": 12})
    run(runtime, "pump.pressure", {"reading_mpa": 9.5})
    new = runtime.records({"kind": "pump.pressure"})["rows"][-1]["payload"]["verdict"]
    assert new["revision"] == 2 and new["ok"] is True
    # The old failed verdict keeps failing under the revision it names.
    assert runtime.explain_verdict(old)["explained"]["ok"] is False


def test_every_verdict_is_audited_with_its_version(runtime: PlantRuntime) -> None:
    run(runtime, "water.dispense", {"litres": 100, "rate_lps": 70})  # over rev1 ceiling
    entries = [entry for entry in runtime.audit.ledger.entries() if entry.name == "decision.water_flow"]
    assert entries, "a judged reading must land in the audit ledger"
    detail = entries[-1].detail
    assert detail["revision"] == 1
    assert detail["effective_tick"] == 0
    assert detail["evaluated_tick"] == runtime.clock.now()
    assert detail["ok"] is False
    # The ledger entry is also durable in the stream via the event subscriber.
    assert runtime.records({"kind": "audit.event"})["matched"] >= 1


# --------------------------------------------------------- replay and console


def test_console_state_exposes_current_and_pending_limits(runtime: PlantRuntime) -> None:
    run(runtime, "limits.publish", {"category": "prime_water", "value": 70})
    state = runtime.state()
    assert state["limits"]["ticks_per_day"] == TICKS_PER_DAY
    assert state["limits"]["current"]["prime_water"]["revision"] == 1
    pending = state["limits"]["pending"]
    assert len(pending) == 1 and pending[0]["category"] == "prime_water"
    assert pending[0]["in_force"] is False


def test_console_serves_limit_history(runtime: PlantRuntime) -> None:
    run(runtime, "limits.publish", {"category": "pump_pressure", "value": 12})
    server = ConsoleServer(runtime, pages=PageStore(runtime.config.web_dir))
    response = server.handle(Request(method="GET", path="/api/limits", query={"category": "pump_pressure"}))
    assert response.ok
    body = json.loads(response.text)
    assert [item["revision"] for item in body["revisions"]] == [1, 2]


def test_explain_endpoint_re_judges_with_the_named_revision(runtime: PlantRuntime) -> None:
    run(runtime, "pump.pressure", {"reading_mpa": 9.5})
    verdict = runtime.records({"kind": "pump.pressure"})["rows"][-1]["payload"]["verdict"]
    run(runtime, "limits.publish", {"category": "pump_pressure", "value": 12})
    server = ConsoleServer(runtime, pages=PageStore(runtime.config.web_dir))
    response = server.handle(
        Request(method="POST", path="/api/limits/explain", body={"verdict": verdict})
    )
    assert response.ok
    body = json.loads(response.text)
    assert body["consistent"] is True
    assert body["explained"]["revision"] == 1
    assert body["explained"]["ok"] is False


def test_replay_as_of_explains_a_reading_with_the_then_limit(runtime: PlantRuntime) -> None:
    run(runtime, "pump.pressure", {"reading_mpa": 9.5})
    run(runtime, "limits.publish", {"category": "pump_pressure", "value": 12})
    run(runtime, "clock.advance", {"ticks": 2})
    run(runtime, "pump.pressure", {"reading_mpa": 9.5})
    first_tick = 0
    state_then = runtime.view.as_of(first_tick)
    old_payload = state_then["pump"]["pressure"]
    verdict = verdict_from_payload(old_payload["verdict"])
    assert verdict is not None and verdict.revision == 1
    assert runtime.limit_book.re_evaluate(verdict).ok is False


# --------------------------------------------------------------- durability


def test_limit_revisions_survive_a_restart(tmp_path) -> None:
    config = StationConfig(data_dir=tmp_path / "state")
    first = PlantRuntime(config)
    first.bootstrap()
    run(first, "water.prime", {"litres": 60})
    first_verdict = first.records({"kind": "water.prime"})["rows"][0]["payload"]["verdict"]
    run(first, "limits.publish", {"category": "prime_water", "value": 70})
    run(first, "clock.advance", {"ticks": TICKS_PER_DAY + 1})
    first.close()

    second = PlantRuntime(config)
    second.bootstrap()
    assert second.limit_book.current("prime_water", now=second.clock.now()).revision == 2
    # History is rebuilt from the append only stream.
    assert [item.revision for item in second.limit_book.history("prime_water")] == [1, 2]
    # The pre-change verdict is still explained as compliant after restart.
    explained = second.explain_verdict(first_verdict)
    assert explained["consistent"] is True and explained["explained"]["ok"] is True
    second.close()


def test_legacy_journal_is_migrated_with_tick_zero_effective_revision(tmp_path) -> None:
    from mixplant.clock import ManualClock
    from mixplant.ids import SequenceIds
    from mixplant.store.repository import RecordRepository

    data_dir = tmp_path / "state"
    clock = ManualClock()
    legacy_store = RecordRepository.open(data_dir, clock, SequenceIds())
    clock.advance(10)
    legacy_store.publish(
        "pump.pressure",
        "pump",
        0,
        {"active": True, "reading_mpa": 9.5, "ok": False, "code": "over_limit"},
    )
    legacy_store.close()

    config = StationConfig(data_dir=data_dir)
    runtime = PlantRuntime(config)
    runtime.bootstrap()
    revision = runtime.limit_book.revision("pump_pressure", 1)
    assert revision.backdated is True
    assert revision.published_tick == 10
    assert revision.effective_tick == 0
    assert runtime.limit_book.revision_in_force("pump_pressure", 10).revision == 1
    migration_records = [
        record
        for record in runtime.store.committed_records()
        if record.kind == LIMIT_KIND and record.payload.get("kind") == "migration"
    ]
    assert migration_records
    runtime.close()
