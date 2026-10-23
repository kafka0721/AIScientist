"""ITS-specific domain field extractor for Domain-EMA.

Given a completed experiment's ``metrics.json`` and ``provenance.json``, build
a :class:`DomainFrontmatter` populated with ITS-specific axes (task type,
metric family, road-network fingerprint, prediction horizons, etc.).

The extractor is intentionally tolerant of missing fields: absent keys map to
``None`` / ``()`` rather than raising, so partial artifacts from smoke tests
still yield usable metadata for scoring and retrieval biasing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping

from ..types import DistillationRole, DomainFrontmatter, DomainKind

DOMAIN_STANDARD_METRICS: dict[str, frozenset[str]] = {
    "predict": frozenset({"MAE", "RMSE", "MAPE", "R2"}),
    "control": frozenset({"avg_delay", "throughput", "queue_length", "stops"}),
    "joint": frozenset({"system_travel_time", "system_delay"}),
}


def fingerprint_road_network(
    edges: Iterable[object],
    nodes: Iterable[object],
) -> str:
    """Stable short hash of a road network's coarse shape for retrieval bucketing."""
    node_list = list(nodes)
    edge_list = list(edges)
    key = "|".join(
        [
            str(len(node_list)),
            str(len(edge_list)),
            ",".join(sorted(str(n) for n in node_list[:10])),
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _reported_metric_family(
    metrics_json: Mapping[str, object],
    task_type: str,
) -> tuple[str, ...]:
    reported = metrics_json.get("reported")
    if isinstance(reported, Mapping):
        names = tuple(reported.keys())
    elif isinstance(reported, list):
        names = tuple(str(n) for n in reported)
    else:
        names = ()
    standard = DOMAIN_STANDARD_METRICS.get(task_type, frozenset())
    return tuple(name for name in names if name in standard)


def _tuple_of_int(value: object) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[int] = []
    for v in value:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def _leakage_risk(provenance_json: Mapping[str, object]) -> float:
    """Coarse leakage risk: flagged provenance ⇒ 1.0; unknown ⇒ 0.0."""
    flag = provenance_json.get("data_leakage_flag")
    if isinstance(flag, bool):
        return 1.0 if flag else 0.0
    if isinstance(flag, (int, float)):
        return max(0.0, min(1.0, float(flag)))
    return 0.0


def extract_its_metadata(
    *,
    role: DistillationRole,
    metrics_json: Mapping[str, object] | None,
    provenance_json: Mapping[str, object] | None,
) -> DomainFrontmatter:
    """Build a :class:`DomainFrontmatter` for the ITS domain.

    ``utility_score`` is left at 0.0 — the scorer fills it after this returns.
    """
    metrics = metrics_json or {}
    provenance = provenance_json or {}

    task_type = str(metrics.get("task_type") or "predict")
    if task_type not in DOMAIN_STANDARD_METRICS:
        task_type = "predict"

    metric_family = _reported_metric_family(metrics, task_type)

    sim_fidelity = provenance.get("sim_fidelity")
    if not isinstance(sim_fidelity, str):
        sim_fidelity = None

    return DomainFrontmatter(
        domain=DomainKind.ITS,
        role=role,
        utility_score=0.0,
        task_type=task_type,
        metric_family=metric_family,
        leakage_risk=_leakage_risk(provenance),
        sim_fidelity=sim_fidelity,
        prediction_horizons=_tuple_of_int(metrics.get("horizons")),
        data_split_protocol=_opt_str(provenance.get("split_protocol")),
        road_network_fingerprint=_opt_str(provenance.get("road_network_fingerprint")),
        sim_config_hash=_opt_str(provenance.get("sim_config_hash")),
        controller_interface=_opt_str(provenance.get("controller_interface")),
        failure_stage=_opt_str(metrics.get("failure_stage")),
        run_id=_opt_str(provenance.get("run_id")),
        event_types=_tuple_of_str(
            provenance.get("event_types") or metrics.get("event_types")
        ),
        city=_opt_str(provenance.get("city")),
        dataset=_opt_str(provenance.get("dataset")),
        model_family=_opt_str(provenance.get("model_family")),
    )


def _opt_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _tuple_of_str(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        item.strip().lower()
        for item in value
        if isinstance(item, str) and item.strip()
    )
