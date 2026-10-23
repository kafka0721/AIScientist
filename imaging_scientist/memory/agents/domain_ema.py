"""Domain-EMA coordinator: classify, extract, score, gate.

Given a completed subagent run's summary and (optional) artifacts, ``distill``
decides which distillation bucket to write to (IDE → M_I⁺, IVE → M_I⁻,
ESE → M_E) and returns a :class:`DistilledEntry` for the store layer to persist.

Design goals:
    * **Pure**: no LLM calls; classification is rules + hints.
    * **Tolerant**: missing metrics/provenance still yield a decision (SKIP).
    * **Deterministic**: same inputs ⇒ same outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Mapping

from ..types import (
    DistillationRole,
    DomainFrontmatter,
    DomainKind,
    EMAHints,
    MemoryScope,
    MemoryType,
)
from .domain_scorer import compute_utility_score
from .its_extractor import extract_its_metadata

# Write threshold: strategies below this floor are noise and get dropped.
DEFAULT_STRATEGY_WRITE_THRESHOLD = 0.2


@dataclass(frozen=True)
class DistillationInput:
    """Minimal context passed from the memory worker to the distiller."""

    domain: DomainKind
    trajectory_summary: str
    ema_hints: EMAHints | None
    run_id: str | None
    metrics_json: Mapping[str, object] | None
    provenance_json: Mapping[str, object] | None


@dataclass(frozen=True)
class DistilledEntry:
    """The result of one distillation pass, ready for the observation store."""

    role: DistillationRole
    memory_type: MemoryType
    scope: MemoryScope
    summary: str
    body: str
    why_it_matters: str
    domain_metadata: DomainFrontmatter
    utility_score: float
    contradicts_ids: tuple[str, ...] = ()


DistillationAction = Literal["IDE", "IVE", "ESE", "SKIP"]


def classify_distillation(inp: DistillationInput) -> DistillationAction:
    """Decide which distillation bucket a completed run belongs in.

    Priority:
        1. Explicit ``ema_hints`` from the Rebuttal reviewer.
        2. Fallback: infer from ``metrics_json`` (``beat_baseline``,
           ``failure_type``). Absent both → SKIP.
    """
    hints = inp.ema_hints
    if hints is not None:
        if hints.write_MI_negative:
            return "IVE"
        if hints.write_MI_positive:
            return "IDE"
        if hints.write_ME_debug:
            return "ESE"

    metrics = inp.metrics_json or {}
    if metrics.get("beat_baseline"):
        return "IDE"
    failure_type = metrics.get("failure_type")
    if failure_type == "direction":
        return "IVE"
    if failure_type == "implementation":
        return "ESE"
    return "SKIP"


_ROLE_MAP: dict[DistillationAction, DistillationRole] = {
    "IDE": DistillationRole.DIRECTION_POSITIVE,
    "IVE": DistillationRole.DIRECTION_NEGATIVE,
    "ESE": DistillationRole.STRATEGY,
}


def _extract_domain_metadata(
    *,
    domain: DomainKind,
    role: DistillationRole,
    metrics_json: Mapping[str, object] | None,
    provenance_json: Mapping[str, object] | None,
) -> DomainFrontmatter:
    if domain == DomainKind.ITS:
        return extract_its_metadata(
            role=role,
            metrics_json=metrics_json,
            provenance_json=provenance_json,
        )
    return DomainFrontmatter(
        domain=domain,
        role=role,
        utility_score=0.0,
        task_type=(str((metrics_json or {}).get("task_type", "generic"))),
        run_id=_opt_str((provenance_json or {}).get("run_id")),
    )


def distill(
    inp: DistillationInput,
    *,
    strategy_write_threshold: float = DEFAULT_STRATEGY_WRITE_THRESHOLD,
) -> DistilledEntry | None:
    """Run one full distillation pass.

    Returns ``None`` when the classifier says SKIP or when a strategy candidate
    scores below the write threshold. IVE entries always pass the gate — a
    negative example is worth recording even if its "improvement" is nil.
    """
    action = classify_distillation(inp)
    if action == "SKIP":
        return None

    role = _ROLE_MAP[action]
    domain_meta = _extract_domain_metadata(
        domain=inp.domain,
        role=role,
        metrics_json=inp.metrics_json,
        provenance_json=inp.provenance_json,
    )
    utility = compute_utility_score(
        role=role,
        metrics_json=inp.metrics_json,
        provenance_json=inp.provenance_json,
        domain_meta=domain_meta,
    )
    domain_meta = replace(domain_meta, utility_score=utility)

    # Only strategies are quality-gated on write; IDE and IVE unconditionally pass.
    if action == "ESE" and utility < strategy_write_threshold:
        return None

    memory_type = (
        MemoryType.SEMANTIC
        if action in {"IDE", "IVE"}
        else MemoryType.PROCEDURAL
    )
    scope = MemoryScope.PROJECT

    summary = _build_summary(action, inp, domain_meta)
    body = _build_body(action, inp, domain_meta)
    rationale = _build_rationale(action, inp)

    return DistilledEntry(
        role=role,
        memory_type=memory_type,
        scope=scope,
        summary=summary,
        body=body,
        why_it_matters=rationale,
        domain_metadata=domain_meta,
        utility_score=utility,
    )


# ---------------------------------------------------------------------------
# Content builders — kept simple and readable; not intended as LLM prompts.
# ---------------------------------------------------------------------------


_ACTION_LABELS: dict[DistillationAction, str] = {
    "IDE": "Direction worth pursuing",
    "IVE": "Direction ruled out",
    "ESE": "Reusable strategy",
}


def _build_summary(
    action: DistillationAction,
    inp: DistillationInput,
    meta: DomainFrontmatter,
) -> str:
    label = _ACTION_LABELS[action]
    return f"[{meta.domain.value}/{meta.task_type}] {label} (s_d={meta.utility_score:.2f})"


def _build_body(
    action: DistillationAction,
    inp: DistillationInput,
    meta: DomainFrontmatter,
) -> str:
    trajectory = (inp.trajectory_summary or "").strip() or "(no trajectory summary)"
    metric_family = ", ".join(meta.metric_family) if meta.metric_family else "n/a"
    horizons = (
        ", ".join(str(h) for h in meta.prediction_horizons)
        if meta.prediction_horizons
        else "n/a"
    )
    lines = [
        f"Action: {action} — {_ACTION_LABELS[action]}",
        f"Domain: {meta.domain.value} | task_type: {meta.task_type}",
        f"metric_family: {metric_family} | horizons: {horizons}",
        f"utility_score: {meta.utility_score:.3f}",
        "",
        "## Trajectory summary",
        trajectory,
    ]
    if inp.run_id:
        lines.append(f"\nRun id: {inp.run_id}")
    if meta.road_network_fingerprint:
        lines.append(f"Road network fingerprint: {meta.road_network_fingerprint}")
    if meta.failure_stage:
        lines.append(f"Failure stage: {meta.failure_stage}")
    return "\n".join(lines)


def _build_rationale(action: DistillationAction, inp: DistillationInput) -> str:
    if action == "IDE":
        return (
            "Future planning may build on this direction; retrieval should surface "
            "it when RA drafts hypotheses in the same task_type."
        )
    if action == "IVE":
        return (
            "This direction has been shown non-viable in the current context. "
            "Retrieval must surface it so RA does not re-attempt it blindly."
        )
    # ESE
    return (
        "Reusable execution strategy (data split / seed / config / debug recipe) "
        "worth adopting in future runs of the same task_type."
    )


def _opt_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
