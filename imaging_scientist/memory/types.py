"""Shared types for EvoMemory observation storage and search."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class MemoryType(StrEnum):
    """Kinds of reusable memory an observation can represent."""

    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    EPISODIC = "episodic"


class MemoryScope(StrEnum):
    """Whether an observation is global or tied to the active project."""

    GLOBAL = "global"
    PROJECT = "project"


class MemorySourceType(StrEnum):
    """Where a memory observation originated."""

    SUBAGENT = "subagent"
    TURN = "turn"


class ObservationSearchMode(StrEnum):
    """Search modes supported by `search_observations`."""

    RANKED = "ranked"
    REGEX = "regex"


class ObservationRelation(StrEnum):
    """Allowed relationship labels between observations."""

    COMPLEMENTS = "complements"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"


class ObservationRecordResult(TypedDict):
    """Result returned by `record_observation`."""

    observation_id: str
    path: str
    created: bool
    memory_type: MemoryType
    scope: MemoryScope
    project_id: NotRequired[str]


class RelatedObservationResult(TypedDict):
    """One resolved observation relationship exposed to memory tools."""

    observation_id: str
    path: str
    memory_type: MemoryType
    scope: MemoryScope
    summary: str
    relation: NotRequired[ObservationRelation]
    reason: NotRequired[str]


@dataclass(frozen=True)
class ObservationSearchDocument:
    """Parsed observation document ready for search."""

    observation_id: str
    path: str
    memory_type: MemoryType
    scope: MemoryScope
    summary: str
    body: str
    text: str
    related_observations: tuple[RelatedObservationResult, ...] = ()


class ObservationSearchHit(TypedDict):
    """One result returned by `search_observations`."""

    observation_id: str
    path: str
    memory_type: MemoryType
    scope: MemoryScope
    summary: str
    matches: list[str]
    related_observations: NotRequired[list[RelatedObservationResult]]
    score: NotRequired[float]
    role: NotRequired[str]
    evidence_source: NotRequired[str | None]
    evidence_status: NotRequired[str | None]


class ObservationReadResult(TypedDict):
    """Full observation document returned by `read_memory`."""

    observation_id: str
    path: str
    memory_type: MemoryType
    scope: MemoryScope
    summary: str
    text: str
    related_observations: NotRequired[list[RelatedObservationResult]]


# ---------------------------------------------------------------------------
# Domain-EMA extension: single-domain distillation (M_I / M_E) support.
#
# All types below are OPTIONAL — legacy observations without a domain field
# continue to work unchanged. Domain-EMA writers attach `DomainFrontmatter`
# to enrich retrieval, scoring, and adversarial rebuttal-driven routing.
# ---------------------------------------------------------------------------


class DomainKind(StrEnum):
    """Supported research domains for Domain-EMA distillation."""

    ITS = "its"          # Intelligent Transportation Systems
    BIO = "bio"          # Biomedical / life sciences (placeholder for future)
    GENERIC = "generic"  # Domain-agnostic fallback


class DistillationRole(StrEnum):
    """Role of a distilled observation in the M_I / M_E dual-memory model.

    - ``DIRECTION_POSITIVE`` — IDE output: a research direction worth pursuing (M_I⁺)
    - ``DIRECTION_NEGATIVE`` — IVE output: a direction ruled out (M_I⁻)
    - ``STRATEGY``           — ESE output: a reusable execution strategy (M_E)
    """

    DIRECTION_POSITIVE = "direction_positive"
    DIRECTION_NEGATIVE = "direction_negative"
    STRATEGY = "strategy"


class ITSTaskType(StrEnum):
    """Task-type dimension for the Intelligent Transportation System domain."""

    PREDICT = "predict"
    CONTROL = "control"
    JOINT = "joint"


@dataclass(frozen=True)
class DomainFrontmatter:
    """Domain-specific frontmatter attached to distilled observations.

    Serialized under the ``domain:`` key of an observation's YAML frontmatter.
    All fields except ``domain``, ``role``, ``utility_score`` and ``task_type``
    are optional so schemas can grow per-domain without breaking readers.
    """

    domain: DomainKind
    role: DistillationRole
    utility_score: float                                # s_d ∈ [0, 1]
    task_type: str                                      # ITSTaskType.value or other domain enum
    metric_family: tuple[str, ...] = ()                 # e.g. ("MAE", "RMSE", "MAPE")
    leakage_risk: float = 0.0
    sim_fidelity: str | None = None                    # "micro" / "meso" / "macro"
    prediction_horizons: tuple[int, ...] = ()          # e.g. (15, 30, 60) minutes
    data_split_protocol: str | None = None
    road_network_fingerprint: str | None = None
    sim_config_hash: str | None = None
    controller_interface: str | None = None
    failure_stage: str | None = None                   # "data_loading|training|evaluation"
    run_id: str | None = None                          # ties back to artifacts/<run_id>/
    event_types: tuple[str, ...] = ()                  # rain / incident / holiday / compound
    city: str | None = None
    dataset: str | None = None
    model_family: str | None = None


class DomainFrontmatterModel(BaseModel):
    """Pydantic mirror of :class:`DomainFrontmatter` for YAML (de)serialization.

    ``ObservationFrontmatter`` embeds ``DomainFrontmatterModel | None`` so
    parsing legacy observations (no ``domain:`` key) stays a no-op.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    domain: DomainKind
    role: DistillationRole
    utility_score: float = Field(ge=0.0, le=1.0)
    task_type: str = Field(min_length=1)
    evidence_source: str | None = None
    evidence_status: str | None = None
    evidence_id: str | None = None
    metric_family: list[str] = Field(default_factory=list)
    leakage_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    sim_fidelity: str | None = None
    prediction_horizons: list[int] = Field(default_factory=list)
    data_split_protocol: str | None = None
    road_network_fingerprint: str | None = None
    sim_config_hash: str | None = None
    controller_interface: str | None = None
    failure_stage: str | None = None
    run_id: str | None = None
    event_types: list[str] = Field(default_factory=list)
    city: str | None = None
    dataset: str | None = None
    model_family: str | None = None

    @classmethod
    def from_dataclass(cls, dc: DomainFrontmatter) -> DomainFrontmatterModel:
        return cls(
            domain=dc.domain,
            role=dc.role,
            utility_score=dc.utility_score,
            task_type=dc.task_type,
            metric_family=list(dc.metric_family),
            leakage_risk=dc.leakage_risk,
            sim_fidelity=dc.sim_fidelity,
            prediction_horizons=list(dc.prediction_horizons),
            data_split_protocol=dc.data_split_protocol,
            road_network_fingerprint=dc.road_network_fingerprint,
            sim_config_hash=dc.sim_config_hash,
            controller_interface=dc.controller_interface,
            failure_stage=dc.failure_stage,
            run_id=dc.run_id,
            event_types=list(dc.event_types),
            city=dc.city,
            dataset=dc.dataset,
            model_family=dc.model_family,
        )

    def to_frontmatter_dict(self) -> dict[str, object]:
        """Serialize to a plain dict suitable for ``yaml.safe_dump``."""
        payload: dict[str, object] = {
            "domain": self.domain.value,
            "role": self.role.value,
            "utility_score": float(self.utility_score),
            "task_type": self.task_type,
        }
        if self.metric_family:
            payload["metric_family"] = list(self.metric_family)
        if self.leakage_risk:
            payload["leakage_risk"] = float(self.leakage_risk)
        if self.sim_fidelity is not None:
            payload["sim_fidelity"] = self.sim_fidelity
        if self.prediction_horizons:
            payload["prediction_horizons"] = list(self.prediction_horizons)
        for key in (
            "evidence_source",
            "evidence_status",
            "evidence_id",
            "data_split_protocol",
            "road_network_fingerprint",
            "sim_config_hash",
            "controller_interface",
            "failure_stage",
            "run_id",
            "city",
            "dataset",
            "model_family",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.event_types:
            payload["event_types"] = list(self.event_types)
        return payload


class EMAHints(BaseModel):
    """Structured hints emitted by the Rebuttal reviewer to steer Domain-EMA.

    Kept intentionally minimal — the reviewer only signals which distillation
    bucket to write to; classification of task_type / metrics is left to the
    domain extractor (see ``imaging_scientist/memory/agents/domain_ema.py``).
    """

    model_config = ConfigDict(extra="ignore")

    write_MI_positive: bool = False
    write_MI_negative: bool = False
    write_ME_debug: bool = False
    debug_note: str | None = None
