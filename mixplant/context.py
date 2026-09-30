"""The collaborators every service is handed at boot."""

from __future__ import annotations

from dataclasses import dataclass

from .clock import Clock
from .config import StationConfig
from .decision.batch import BatchRegistry
from .decision.stateview import StateView
from .decision.limit_catalog import ThresholdRegistry
from .decision.thresholds import ThresholdSet
from .event.bus import EventBus
from .ids import SequenceIds
from .statemachine.gate import PreGate
from .store.repository import RecordRepository
from .versioning.facade import VersionedArtifacts


@dataclass(frozen=True, slots=True)
class SharedContext:
    """Read only bundle shared by every plant service."""

    store: RecordRepository
    versions: VersionedArtifacts
    bus: EventBus
    clock: Clock
    config: StationConfig
    threshold_registry: ThresholdRegistry
    thresholds: ThresholdSet
    view: StateView
    batches: BatchRegistry
    gate: PreGate
    ids: SequenceIds

    def use_thresholds(self, thresholds: ThresholdSet) -> None:
        """Switch the shared catalog to the set now in force."""

        object.__setattr__(self, "thresholds", thresholds)

    def use_threshold_registry(self, registry: ThresholdRegistry) -> None:
        """Switch to a threshold registry rebuilt during replay."""

        object.__setattr__(self, "threshold_registry", registry)
