"""Inject 6 curated ITS priors so RA has something to retrieve.

Run once from repo root:
    python scripts/inject_its_priors.py
"""

from __future__ import annotations

from pathlib import Path

from imaging_scientist import paths as _paths
from imaging_scientist.memory.observations.store import record_domain_observation_file
from imaging_scientist.memory.types import (
    DistillationRole,
    DomainFrontmatterModel,
    DomainKind,
    MemoryScope,
    MemoryType,
)

MEMORY = Path(_paths.MEMORIES_DIR)
PID = "its-exp"


def _write(role, mtype, summary, body, reason, **domain_kw):
    meta = DomainFrontmatterModel(
        domain=DomainKind.ITS,
        role=role,
        utility_score=0.75,  # curated priors → high confidence
        task_type="predict",
        road_network_fingerprint="metr_la_v1",
        **domain_kw,
    )
    return record_domain_observation_file(
        memory_dir=MEMORY,
        project_id=PID,
        domain=meta,
        memory_type=mtype,
        summary=summary,
        observation=body,
        why_it_matters=reason,
        source_agent="prior_injector",
        source_session_id="cold-start-01",
        scope=MemoryScope.PROJECT,
    )


def main() -> None:
    # --- M_I+ direction_positive ---
    _write(
        DistillationRole.DIRECTION_POSITIVE,
        MemoryType.SEMANTIC,
        "Graph-based spatiotemporal models are strong on METR-LA",
        (
            "DCRNN, Graph WaveNet, and MTGNN set strong baselines on METR-LA. "
            "Adding graph structure over pure temporal models typically yields "
            "a 5-15 percent MAE reduction. Representative DCRNN numbers on "
            "METR-LA: 15min MAE ~2.77, 30min MAE ~3.15, 60min MAE ~3.60."
        ),
        (
            "Any new attempt on METR-LA MUST benchmark against these; skipping "
            "graph structure is unusual and requires justification."
        ),
        metric_family=("MAE", "RMSE", "MAPE"),
        prediction_horizons=(5, 15, 30, 60),
    )

    _write(
        DistillationRole.DIRECTION_POSITIVE,
        MemoryType.SEMANTIC,
        "Adaptive graph learning outperforms static adjacency on METR-LA",
        (
            "Graph WaveNet and MTGNN show that learning the adjacency matrix "
            "instead of using a fixed distance-based one gives further "
            "1-3 percent MAE reduction at 15min horizon."
        ),
        (
            "When designing a new GAT/GRU variant, prefer adaptive/learnable "
            "adjacency rather than fixed distance graphs."
        ),
        metric_family=("MAE", "RMSE"),
        prediction_horizons=(15, 30, 60),
    )

    # --- M_I- direction_negative ---
    _write(
        DistillationRole.DIRECTION_NEGATIVE,
        MemoryType.SEMANTIC,
        "Pure LSTM/GRU without graph structure underperforms on METR-LA",
        (
            "Multiple works (2018-2020) confirm that pure temporal models "
            "(LSTM/GRU without spatial graph) are 8-12 percent worse than "
            "graph-aware models on 15min/30min MAE at METR-LA. Do not "
            "re-attempt unless you have a specific mechanism to compensate."
        ),
        (
            "Prevents wasted cycles on a known-inferior direction; RA should "
            "either abandon the pure-temporal path or explicitly justify."
        ),
        metric_family=("MAE", "RMSE"),
        prediction_horizons=(15, 30),
    )

    _write(
        DistillationRole.DIRECTION_NEGATIVE,
        MemoryType.SEMANTIC,
        "Random train/test split leaks future information in METR-LA",
        (
            "METR-LA is a temporal series. Random splits let future speeds "
            "leak into training and inflate metrics artifactually (apparent "
            "RMSE drop up to 40 percent). Reject any plan that uses random "
            "splits for time series."
        ),
        (
            "Any new experiment on METR-LA MUST use a temporal split. R2 "
            "review should hard-reject random splits."
        ),
    )

    # --- M_E strategy ---
    _write(
        DistillationRole.STRATEGY,
        MemoryType.PROCEDURAL,
        "Temporal 80/10/10 split protocol for METR-LA",
        (
            "Split by time: first 80% train, next 10% val, last 10% test. "
            "Ensures no future leakage. Report MAE/RMSE/MAPE at horizons "
            "{5, 15, 30, 60} minutes."
        ),
        (
            "Reused across all METR-LA experiments; adopting saves ~20 minutes "
            "of protocol re-derivation per new run and prevents leakage bugs."
        ),
        data_split_protocol="temporal_80_10_10",
        prediction_horizons=(5, 15, 30, 60),
        metric_family=("MAE", "RMSE", "MAPE"),
    )

    _write(
        DistillationRole.STRATEGY,
        MemoryType.PROCEDURAL,
        "Multi-seed averaging (3-5 seeds) for METR-LA reproducibility",
        (
            "Single-seed runs on METR-LA have +/- 0.15 MAE variance across "
            "seeds. Report mean +/- std across at least 3 seeds; single-seed "
            "claims are not defensible for headline results."
        ),
        "R3 will reject headline claims that lack multi-seed evidence.",
        metric_family=("MAE",),
    )

    _write(
        DistillationRole.STRATEGY,
        MemoryType.PROCEDURAL,
        "GPU OOM avoidance for GAT+GRU on METR-LA",
        (
            "GAT with 8 heads plus 2-layer GRU (hidden=64) exceeds 12GB VRAM "
            "at batch_size=64. Reduce to batch_size=32 or enable gradient "
            "checkpointing. Sequence length 12 (1 hour history) is a solid "
            "default."
        ),
        "Reused for any GAT+RNN combo on METR-LA; prevents job crashes.",
    )

    print("Injected 7 priors: 2 direction_positive, 2 direction_negative, 3 strategy")
    print(f"Wrote under: {MEMORY / 'observations' / 'domain' / 'its'}")


if __name__ == "__main__":
    main()
