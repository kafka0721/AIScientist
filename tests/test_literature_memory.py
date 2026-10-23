"""Literature import must preserve provenance and never invent experiment evidence."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from imaging_scientist.memory.literature import import_literature_candidates
from imaging_scientist.memory.observations.store import read_observation_document
from imaging_scientist.memory.types import DomainKind


@pytest.fixture
def batch(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "paper.pdf").write_bytes(b"%PDF-test source")
    row = dict(  # noqa: C408
        id="ITS-SV-009",
        domain="its",
        role="strategy",
        task_type="evaluation",
        summary="Repeat evaluation to measure consistency",
        conclusion="Repeat five times",
        applicable_conditions="The cited benchmark",
        inapplicable_conditions="Other protocols",
        source_paths=["paper.pdf"],
        evidence_location="PDF page 10, Table 4",
        evidence_text="Five trials",
        evidence_type="method_protocol",
        why_reusable="Estimate variance",
        utility_score=None,
    )
    return workspace, tmp_path / "memories", row


def run(batch, rows=None, dry_run=False):
    workspace, memory, row = batch
    (workspace / "candidates.jsonl").write_text(
        "\n".join(json.dumps(item) for item in (rows or [row])), encoding="utf-8"
    )
    return import_literature_candidates(
        workspace=workspace,
        memory_dir=memory,
        path="candidates.jsonl",
        dry_run=dry_run,
    )


def test_preview_does_not_write_and_import_is_retrievable_idempotent(batch):
    preview = run(batch, dry_run=True)
    assert preview["counts"] == {"ready": 1}
    assert not batch[1].exists()
    result = run(batch)
    assert result["counts"] == {"created": 1}
    row = result["rows"][0]
    assert row["readback_verified"]
    assert row["retrieval_verified"]
    metadata, body = read_observation_document(row["physical_path"])
    assert metadata.domain.task_type == "evaluation"
    assert metadata.domain.evidence_source == "literature"
    assert metadata.domain.evidence_status == "source_unverified"
    assert metadata.domain.utility_score == 0.0
    assert metadata.domain.run_id is None
    assert metadata.domain.evidence_id.startswith("literature:")
    assert '"utility_score": null' in body
    assert "sha256" in body
    assert "PDF page 10" in body
    assert run(batch)["counts"] == {"existing": 1}
    assert len(list(batch[1].rglob("D-*.md"))) == 1


def test_conflicting_reimport_is_reported_without_overwriting(batch):
    original = run(batch)["rows"][0]
    before = Path(original["physical_path"]).read_bytes()
    batch[2]["conclusion"] = "Changed claim"
    batch[2]["summary"] = "Changed wording must not create a duplicate"
    assert run(batch)["counts"] == {"error": 1}
    assert Path(original["physical_path"]).read_bytes() == before
    assert len(list(batch[1].rglob("D-*.md"))) == 1


@pytest.mark.parametrize(
    "invalid",
    [
        {"source_paths": ["../outside.pdf"]},
        {"source_paths": ["missing.pdf"]},
        {"source_paths": [""]},
        {"evidence_location": " "},
        {"domain": "bio"},
    ],
)
def test_invalid_row_prevents_partial_batch_writes(batch, invalid):
    row = batch[2]
    result = run(batch, [row, {**row, "id": "bad", **invalid}])
    assert result["validation_failed"]
    assert not batch[1].exists()


def test_duplicate_ids_fail_batch(batch):
    assert run(batch, [batch[2], batch[2]])["validation_failed"]
    assert not batch[1].exists()


def test_gap_deferred_warning_reclassified_and_secondary_claim_deferred(batch):
    row = batch[2]
    result = run(
        batch,
        [
            {
                **row,
                "id": "gap",
                "role": "direction_positive",
                "evidence_type": "survey_identified_gap",
            },
            {
                **row,
                "id": "caution",
                "role": "direction_negative",
                "evidence_type": "methodological_warning",
            },
            {
                **row,
                "id": "secondary",
                "role": "direction_positive",
                "evidence_type": "survey_reported",
            },
        ],
    )
    assert result["counts"] == {"deferred": 2, "created": 1}
    assert result["rows"][1]["role"] == "strategy"


def test_tool_respects_disabled_domain_and_uses_active_store(batch, monkeypatch):
    import importlib

    module = importlib.import_module("imaging_scientist.tools.import_domain_memory")
    run(batch, dry_run=True)
    monkeypatch.setattr(module.paths, "_active_workspace", batch[0])
    monkeypatch.setattr(module.paths, "MEMORIES_DIR", batch[1])
    config = SimpleNamespace(
        domain_ema_enabled=False, domain_ema_domain=DomainKind.ITS.value
    )
    monkeypatch.setattr(module, "get_effective_config", lambda: config)
    assert "error" in json.loads(
        module.import_domain_memory.invoke(
            {"path": "candidates.jsonl", "dry_run": False}
        )
    )
    assert not batch[1].exists()
    config.domain_ema_enabled = True
    result = json.loads(
        module.import_domain_memory.invoke(
            {"path": "candidates.jsonl", "dry_run": False}
        )
    )
    assert result["counts"] == {"created": 1}


def test_workspace_escape_for_batch_is_rejected(batch):
    with pytest.raises(ValueError, match="escapes workspace"):
        import_literature_candidates(
            workspace=batch[0], memory_dir=batch[1], path="../input.jsonl"
        )
