"""Threshold versions are selected by effective time and never rewrite verdicts."""

from __future__ import annotations

from mixplant.config import Limits, StationConfig
from mixplant.decision.limit_catalog import NEXT_DAY_EFFECTIVE, PUBLISH_EFFECTIVE, ThresholdRegistry
from mixplant.runtime import PlantRuntime


def test_safety_threshold_is_effective_in_the_publishing_session() -> None:
    registry = ThresholdRegistry.from_limits(Limits())

    revision = registry.publish("pump_pressure", 7.0, tick=5, seq=10)

    assert revision.version == 2
    assert revision.effective_policy == PUBLISH_EFFECTIVE
    assert revision.effective_tick == 5
    assert registry.require_revision("pump_pressure", 5).limit == 7.0
    assert registry.require_revision("pump_pressure", 4).limit == 8.0


def test_quality_threshold_is_effective_the_next_day_not_at_release() -> None:
    registry = ThresholdRegistry.from_limits(Limits(), day_ticks=24)

    revision = registry.publish("scale_deviation", 1.0, tick=5, seq=10)

    assert revision.effective_policy == NEXT_DAY_EFFECTIVE
    assert revision.published_tick == 5
    assert revision.effective_tick == 24
    assert registry.require_revision("scale_deviation", 23).version == 1
    assert registry.require_revision("scale_deviation", 24).version == 2
    assert registry.pending(5)[0].name == "scale_deviation"


def test_runtime_keeps_the_verdict_recorded_before_a_safety_change() -> None:
    runtime = PlantRuntime.in_memory()
    runtime.bootstrap()

    before = runtime.dispatch("pump.pressure", {"reading_mpa": 7.5})["result"]["pressure"]
    runtime.dispatch("threshold.publish", {"name": "pump_pressure", "limit": 7.0})
    after = runtime.dispatch("pump.pressure", {"reading_mpa": 7.5})["result"]["pressure"]

    assert before["threshold_version"] == 1
    assert before["ok"] is True
    assert after["threshold_version"] == 2
    assert after["ok"] is False
    rows = runtime.records({"kind": "pump.pressure"})["rows"]
    assert [row["payload"]["threshold_version"] for row in rows] == [1, 2]
    assert [row["payload"]["ok"] for row in rows] == [True, False]


def test_restart_replays_a_historical_verdict_with_its_own_version(tmp_path) -> None:
    config = StationConfig(data_dir=tmp_path / "state")
    first = PlantRuntime(config)
    first.bootstrap()
    first.dispatch("pump.pressure", {"reading_mpa": 7.5})
    first.dispatch("threshold.publish", {"name": "pump_pressure", "limit": 7.0})
    first.close()

    second = PlantRuntime(config)
    second.bootstrap()
    row = second.records({"kind": "pump.pressure"})["rows"][0]

    assert row["payload"]["threshold_version"] == 1
    assert row["payload"]["limit"] == 8.0
    assert row["payload"]["ok"] is True
    assert second.history(0, row["seq"])["thresholds"]["current"]["pump_pressure"]["version"] == 1
    second.close()


def test_console_exposes_pending_and_current_versions(runtime: PlantRuntime) -> None:
    runtime.dispatch("threshold.publish", {"name": "scale_deviation", "limit": 1.0})

    thresholds = runtime.state()["thresholds"]

    assert thresholds["current"]["scale_deviation"]["version"] == 1
    assert thresholds["pending"][0]["version"] == 2
    assert thresholds["policies"]["safety"] == PUBLISH_EFFECTIVE
    assert thresholds["policies"]["quality"] == NEXT_DAY_EFFECTIVE


def test_audit_can_recheck_a_historical_verdict(runtime: PlantRuntime) -> None:
    runtime.dispatch("pump.pressure", {"reading_mpa": 7.5})
    row = runtime.records({"kind": "pump.pressure"})["rows"][0]

    explained = runtime.explain_record(row["seq"])

    assert explained["verdict"] is True
    assert explained["check"]["matches"] is True
    assert explained["check"]["explained_version"] == 1


def test_verdict_is_copied_into_the_audit_stream(runtime: PlantRuntime) -> None:
    runtime.dispatch("pump.pressure", {"reading_mpa": 9.0})

    event = runtime.records({"kind": "audit.event"})["rows"][-1]
    assert event["payload"]["name"] == "pump.pressure"
    assert event["payload"]["detail"]["threshold_version"] == 1
    assert event["payload"]["detail"]["code"] == "over_limit"
