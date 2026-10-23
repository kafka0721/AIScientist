"""Domain utility scoring for Domain-EMA distillation.

The scorer converts (metrics_json, provenance_json, domain_metadata) into a
scalar utility ``s_d`` in [0, 1]:

    s_d = alpha * delta_metric
        + beta  * reproducibility
        - gamma * leakage_risk
        - delta * artifact_risk

- ``delta_metric``      : signed improvement over baseline, normalized to [0, 1]
- ``reproducibility``   : provenance-derived score in [0, 1]
- ``leakage_risk``      : provenance/metadata-derived, higher = worse
- ``artifact_risk``     : e.g. sensitivity to a single seed, higher = worse

IVE entries (``DIRECTION_NEGATIVE``) bypass ``delta_metric`` because negative
examples do not need to beat a baseline — they gain value from being explicit.
NaN/inf inputs collapse to 0.0 (safe zero, see boundary trap T7).
"""

from __future__ import annotations

import math
from typing import Mapping

from ..types import DistillationRole, DomainFrontmatter

DEFAULT_WEIGHTS: Mapping[str, float] = {
    "alpha_metric": 0.4,
    "beta_reproducibility": 0.3,
    "gamma_leakage": 0.2,
    "delta_artifact": 0.1,
}


def _clip01(x: float) -> float:
    if math.isnan(x) or math.isinf(x):
        return 0.0
    return max(0.0, min(1.0, x))


def compute_utility_score(
    *,
    role: DistillationRole,
    metrics_json: Mapping[str, object] | None,
    provenance_json: Mapping[str, object] | None,
    domain_meta: DomainFrontmatter,
    weights: Mapping[str, float] | None = None,
) -> float:
    """Return the utility score s_d ∈ [0, 1] for a distillation candidate."""
    metrics = metrics_json or {}
    provenance = provenance_json or {}
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    if role == DistillationRole.DIRECTION_NEGATIVE:
        # IVE: don't require baseline gain; treat the direction itself as the asset.
        delta = 0.5
    else:
        primary = _as_float(metrics.get("primary_metric_value"))
        baseline = _as_float(metrics.get("baseline_metric_value"))
        higher_is_better = bool(metrics.get("higher_is_better", False))
        if primary is None or baseline is None:
            delta = 0.0
        else:
            raw = (primary - baseline) if higher_is_better else (baseline - primary)
            denom = max(abs(baseline), 1e-6)
            delta = _clip01(raw / denom)

    reproducibility = _clip01(_as_float(provenance.get("reproducibility_score")) or 0.5)
    leakage = _clip01(domain_meta.leakage_risk)
    artifact_risk = _clip01(_as_float(metrics.get("artifact_risk")) or 0.0)

    score = (
        w["alpha_metric"] * delta
        + w["beta_reproducibility"] * reproducibility
        - w["gamma_leakage"] * leakage
        - w["delta_artifact"] * artifact_risk
    )
    return _clip01(score)


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):  # bool is a subclass of int; treat as absent
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
