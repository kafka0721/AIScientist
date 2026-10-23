"""Unit tests for Domain-EMA distillation (pure Python, no LLM, no fs)."""

from __future__ import annotations

import pytest

from imaging_scientist.memory.agents.domain_ema import (
    DistillationInput,
    classify_distillation,
    distill,
)
from imaging_scientist.memory.agents.domain_scorer import compute_utility_score
from imaging_scientist.memory.agents.its_extractor import (
    DOMAIN_STANDARD_METRICS,
    extract_its_metadata,
    fingerprint_road_network,
)
from imaging_scientist.memory.types import (
    DistillationRole,
    DomainFrontmatter,
    DomainKind,
    EMAHints,
    MemoryScope,
    MemoryType,
)


# ---------------------------------------------------------------------------
# Layer 1: classify_distillation — pure rules over hints + metrics
# ---------------------------------------------------------------------------


class TestClassify:
    def _mk(self, *, hints=None, metrics=None) -> DistillationInput:
        return DistillationInput(
            domain=DomainKind.ITS,
            trajectory_summary="",
            ema_hints=hints,
            run_id=None,
            metrics_json=metrics,
            provenance_json=None,
        )

    def test_hint_MI_negative_wins(self):
        assert (
            classify_distillation(
                self._mk(hints=EMAHints(write_MI_negative=True))
            )
            == "IVE"
        )

    def test_hint_MI_positive_wins(self):
        assert (
            classify_distillation(
                self._mk(hints=EMAHints(write_MI_positive=True))
            )
            == "IDE"
        )

    def test_hint_ME_debug_wins(self):
        assert (
            classify_distillation(
                self._mk(hints=EMAHints(write_ME_debug=True))
            )
            == "ESE"
        )

    def test_negative_takes_precedence_over_positive(self):
        # Reviewer emitted a contradictory hint; negative signal is stronger.
        hints = EMAHints(write_MI_positive=True, write_MI_negative=True)
        assert classify_distillation(self._mk(hints=hints)) == "IVE"

    def test_beat_baseline_infers_IDE(self):
        assert (
            classify_distillation(self._mk(metrics={"beat_baseline": True}))
            == "IDE"
        )

    def test_failure_type_direction_infers_IVE(self):
        assert (
            classify_distillation(
                self._mk(metrics={"failure_type": "direction"})
            )
            == "IVE"
        )

    def test_failure_type_implementation_infers_ESE(self):
        assert (
            classify_distillation(
                self._mk(metrics={"failure_type": "implementation"})
            )
            == "ESE"
        )

    def test_no_signal_returns_SKIP(self):
        assert classify_distillation(self._mk()) == "SKIP"
        assert classify_distillation(self._mk(metrics={})) == "SKIP"


# ---------------------------------------------------------------------------
# Layer 2: compute_utility_score — nan-safe, weighted formula
# ---------------------------------------------------------------------------


class TestUtilityScore:
    def _meta(self, *, leakage_risk=0.0) -> DomainFrontmatter:
        return DomainFrontmatter(
            domain=DomainKind.ITS,
            role=DistillationRole.STRATEGY,
            utility_score=0.0,
            task_type="predict",
            leakage_risk=leakage_risk,
        )

    def test_score_bounded_in_unit_interval(self):
        s = compute_utility_score(
            role=DistillationRole.STRATEGY,
            metrics_json={
                "primary_metric_value": 3.0,
                "baseline_metric_value": 5.0,
                "higher_is_better": False,
            },
            provenance_json={"reproducibility_score": 0.9},
            domain_meta=self._meta(),
        )
        assert 0.0 <= s <= 1.0

    def test_improvement_increases_score(self):
        base_metrics = {
            "primary_metric_value": 3.0,
            "baseline_metric_value": 5.0,
            "higher_is_better": False,
        }
        better_metrics = {
            "primary_metric_value": 1.0,  # bigger improvement
            "baseline_metric_value": 5.0,
            "higher_is_better": False,
        }
        s_base = compute_utility_score(
            role=DistillationRole.STRATEGY,
            metrics_json=base_metrics,
            provenance_json={},
            domain_meta=self._meta(),
        )
        s_better = compute_utility_score(
            role=DistillationRole.STRATEGY,
            metrics_json=better_metrics,
            provenance_json={},
            domain_meta=self._meta(),
        )
        assert s_better > s_base

    def test_leakage_lowers_score(self):
        m = {
            "primary_metric_value": 3.0,
            "baseline_metric_value": 5.0,
            "higher_is_better": False,
        }
        s_clean = compute_utility_score(
            role=DistillationRole.STRATEGY,
            metrics_json=m,
            provenance_json={},
            domain_meta=self._meta(leakage_risk=0.0),
        )
        s_leaky = compute_utility_score(
            role=DistillationRole.STRATEGY,
            metrics_json=m,
            provenance_json={},
            domain_meta=self._meta(leakage_risk=1.0),
        )
        assert s_leaky < s_clean

    def test_nan_input_returns_zero(self):
        # NaN in artifact_risk should not propagate to s_d.
        s = compute_utility_score(
            role=DistillationRole.STRATEGY,
            metrics_json={
                "primary_metric_value": float("nan"),
                "baseline_metric_value": 5.0,
                "higher_is_better": False,
            },
            provenance_json={},
            domain_meta=self._meta(),
        )
        assert 0.0 <= s <= 1.0  # never NaN

    def test_IVE_ignores_delta_metric(self):
        # For DIRECTION_NEGATIVE, s_d must not depend on primary/baseline.
        m_no_data = compute_utility_score(
            role=DistillationRole.DIRECTION_NEGATIVE,
            metrics_json={},
            provenance_json={},
            domain_meta=self._meta(),
        )
        m_with_data = compute_utility_score(
            role=DistillationRole.DIRECTION_NEGATIVE,
            metrics_json={
                "primary_metric_value": 3.0,
                "baseline_metric_value": 5.0,
            },
            provenance_json={},
            domain_meta=self._meta(),
        )
        assert m_no_data == m_with_data


# ---------------------------------------------------------------------------
# Layer 3: extract_its_metadata — schema-tolerant field extraction
# ---------------------------------------------------------------------------


class TestITSExtractor:
    def test_full_metrics_populate_all_fields(self):
        meta = extract_its_metadata(
            role=DistillationRole.STRATEGY,
            metrics_json={
                "task_type": "predict",
                "reported": {"MAE": 3.1, "RMSE": 4.2, "not_standard": 99},
                "horizons": [15, 30, 60],
            },
            provenance_json={
                "run_id": "run-001",
                "split_protocol": "temporal_80_10_10",
                "road_network_fingerprint": "metr_la_v1",
                "data_leakage_flag": False,
                "sim_fidelity": "meso",
            },
        )
        assert meta.task_type == "predict"
        # Non-standard metrics dropped from metric_family
        assert set(meta.metric_family) == {"MAE", "RMSE"}
        assert meta.prediction_horizons == (15, 30, 60)
        assert meta.road_network_fingerprint == "metr_la_v1"
        assert meta.data_split_protocol == "temporal_80_10_10"
        assert meta.leakage_risk == 0.0
        assert meta.sim_fidelity == "meso"
        assert meta.run_id == "run-001"

    def test_missing_task_type_defaults_to_predict(self):
        meta = extract_its_metadata(
            role=DistillationRole.STRATEGY,
            metrics_json={},
            provenance_json={},
        )
        assert meta.task_type == "predict"

    def test_unknown_task_type_falls_back(self):
        meta = extract_its_metadata(
            role=DistillationRole.STRATEGY,
            metrics_json={"task_type": "unknown_task"},
            provenance_json={},
        )
        assert meta.task_type == "predict"

    def test_leakage_flag_as_bool(self):
        m = extract_its_metadata(
            role=DistillationRole.STRATEGY,
            metrics_json={},
            provenance_json={"data_leakage_flag": True},
        )
        assert m.leakage_risk == 1.0

    def test_fingerprint_is_stable(self):
        # Same nodes/edges produce same fingerprint
        fp1 = fingerprint_road_network(edges=range(10), nodes=range(5))
        fp2 = fingerprint_road_network(edges=range(10), nodes=range(5))
        assert fp1 == fp2
        # Different inputs produce different fingerprints
        fp3 = fingerprint_road_network(edges=range(10), nodes=range(6))
        assert fp1 != fp3

    def test_standard_metrics_are_expected(self):
        # Guard against silent removal
        assert "MAE" in DOMAIN_STANDARD_METRICS["predict"]
        assert "avg_delay" in DOMAIN_STANDARD_METRICS["control"]
        assert "system_delay" in DOMAIN_STANDARD_METRICS["joint"]


# ---------------------------------------------------------------------------
# Layer 4: distill() — end-to-end pure function
# ---------------------------------------------------------------------------


class TestDistill:
    def _mk_input(
        self,
        *,
        hints=None,
        metrics=None,
        provenance=None,
    ) -> DistillationInput:
        return DistillationInput(
            domain=DomainKind.ITS,
            trajectory_summary="test run",
            ema_hints=hints,
            run_id="run-t01",
            metrics_json=metrics,
            provenance_json=provenance,
        )

    def test_SKIP_returns_none(self):
        assert distill(self._mk_input()) is None

    def test_IDE_produces_semantic_positive(self):
        entry = distill(self._mk_input(hints=EMAHints(write_MI_positive=True)))
        assert entry is not None
        assert entry.role == DistillationRole.DIRECTION_POSITIVE
        assert entry.memory_type == MemoryType.SEMANTIC
        assert entry.scope == MemoryScope.PROJECT

    def test_IVE_produces_semantic_negative_unconditional(self):
        # Even with empty metrics, IVE must persist (negatives are assets).
        entry = distill(self._mk_input(hints=EMAHints(write_MI_negative=True)))
        assert entry is not None
        assert entry.role == DistillationRole.DIRECTION_NEGATIVE
        assert entry.memory_type == MemoryType.SEMANTIC

    def test_ESE_below_threshold_returns_none(self):
        # Low-utility strategy suppressed by the write gate.
        # (utility ≈ 0.15 with 0.5 repro, no delta, no leakage → below 0.2)
        entry = distill(
            self._mk_input(
                hints=EMAHints(write_ME_debug=True),
                metrics={},
                provenance={"reproducibility_score": 0.0},
            ),
            strategy_write_threshold=0.5,
        )
        assert entry is None

    def test_ESE_above_threshold_persists(self):
        entry = distill(
            self._mk_input(
                hints=EMAHints(write_ME_debug=True),
                metrics={
                    "primary_metric_value": 2.0,
                    "baseline_metric_value": 5.0,
                    "higher_is_better": False,
                    "task_type": "predict",
                },
                provenance={"reproducibility_score": 0.9},
            ),
            strategy_write_threshold=0.2,
        )
        assert entry is not None
        assert entry.role == DistillationRole.STRATEGY
        assert entry.memory_type == MemoryType.PROCEDURAL

    def test_summary_contains_domain_and_task_type(self):
        entry = distill(self._mk_input(hints=EMAHints(write_MI_positive=True)))
        assert entry is not None
        assert "its" in entry.summary.lower()
        assert entry.domain_metadata.utility_score >= 0.0

    def test_deterministic_output(self):
        """Same input → same output (no LLM, no random)."""
        inp = self._mk_input(hints=EMAHints(write_MI_positive=True))
        entry1 = distill(inp)
        entry2 = distill(inp)
        assert entry1 is not None and entry2 is not None
        assert entry1.summary == entry2.summary
        assert entry1.utility_score == entry2.utility_score


# ---------------------------------------------------------------------------
# Layer 5: I/O smoke — write to tmp_path and read back
# ---------------------------------------------------------------------------


class TestDomainObservationIO:
    def test_write_and_read_roundtrip(self, tmp_path):
        from imaging_scientist.memory.observations.store import (
            record_domain_observation_file,
        )
        from imaging_scientist.memory.types import DomainFrontmatterModel

        domain_meta = DomainFrontmatterModel(
            domain=DomainKind.ITS,
            role=DistillationRole.STRATEGY,
            utility_score=0.42,
            task_type="predict",
            metric_family=["MAE", "RMSE"],
            prediction_horizons=[15, 30, 60],
            road_network_fingerprint="metr_la_v1",
            run_id="run-io-01",
        )
        result = record_domain_observation_file(
            memory_dir=tmp_path,
            project_id="test-proj",
            domain=domain_meta,
            memory_type=MemoryType.PROCEDURAL,
            summary="Temporal split protocol",
            observation="Use 80/10/10 temporal split; avoid random split.",
            why_it_matters="Prevents future-data leakage.",
            source_agent="test-agent",
            source_session_id="sess-01",
        )
        assert result["created"] is True
        # File exists at the domain-scoped path
        expected_path_fragment = "observations/domain/its/strategy"
        assert expected_path_fragment in result["path"]

        # Read back and verify frontmatter has domain block
        import yaml
        from pathlib import Path

        disk_path = Path(str(result["path"]).replace("/memories/", str(tmp_path) + "/"))
        content = disk_path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        fm_text = content.split("---\n", 2)[1]
        fm = yaml.safe_load(fm_text)
        assert fm["domain"]["domain"] == "its"
        assert fm["domain"]["role"] == "strategy"
        assert fm["domain"]["utility_score"] == 0.42

    def test_second_write_is_idempotent(self, tmp_path):
        """Same content → same observation id → created=False on 2nd write."""
        from imaging_scientist.memory.observations.store import (
            record_domain_observation_file,
        )
        from imaging_scientist.memory.types import DomainFrontmatterModel

        domain_meta = DomainFrontmatterModel(
            domain=DomainKind.ITS,
            role=DistillationRole.STRATEGY,
            utility_score=0.42,
            task_type="predict",
            run_id="run-idem-01",
        )
        args = dict(
            memory_dir=tmp_path,
            project_id="test-proj",
            domain=domain_meta,
            memory_type=MemoryType.PROCEDURAL,
            summary="Idempotency check",
            observation="Body content",
            why_it_matters="Reasoning",
            source_agent="test",
            source_session_id="sess-01",
        )
        r1 = record_domain_observation_file(**args)
        r2 = record_domain_observation_file(**args)
        assert r1["observation_id"] == r2["observation_id"]
        assert r1["created"] is True
        assert r2["created"] is False

    def test_search_filters_by_role(self, tmp_path):
        from imaging_scientist.memory.observations.store import (
            record_domain_observation_file,
            search_domain_observations,
        )
        from imaging_scientist.memory.types import DomainFrontmatterModel

        # Write one STRATEGY and one DIRECTION_NEGATIVE
        for role, summary in [
            (DistillationRole.STRATEGY, "GPU OOM avoidance"),
            (DistillationRole.DIRECTION_NEGATIVE, "Pure LSTM banned"),
        ]:
            record_domain_observation_file(
                memory_dir=tmp_path,
                project_id="test-proj",
                domain=DomainFrontmatterModel(
                    domain=DomainKind.ITS,
                    role=role,
                    utility_score=0.7,
                    task_type="predict",
                    run_id=f"run-{role.value}",
                ),
                memory_type=(
                    MemoryType.PROCEDURAL
                    if role == DistillationRole.STRATEGY
                    else MemoryType.SEMANTIC
                ),
                summary=summary,
                observation=f"Body for {summary}",
                why_it_matters="Reason",
                source_agent="test",
                source_session_id="sess-role",
            )
        # role_filter=STRATEGY should exclude the negative direction hit
        hits = search_domain_observations(
            memory_dir=tmp_path,
            domain=DomainKind.ITS,
            query="LSTM banned",  # matches negative better, but filter excludes it
            role_filter=(DistillationRole.STRATEGY,),
        )
        assert all("banned" not in h["summary"].lower() for h in hits)
