"""Manual smoke test for Domain-EMA — no pytest needed.

Run:
    cd E:/evo22
    python scripts/smoke_test_domain_ema.py

Exercises the full pipeline without a live memory worker:
    1. Craft synthetic metrics.json + provenance.json in a tmp workspace
    2. Call distill() → verify entry produced
    3. Write via record_domain_observation_file() → verify disk artifact
    4. Retrieve via search_domain_observations() → verify hit + score

Prints PASS/FAIL for each step; exits non-zero on any failure so it can be
wired into CI or a pre-commit hook.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from imaging_scientist.memory.agents.domain_ema import (
    DistillationInput,
    distill,
)
from imaging_scientist.memory.observations.store import (
    record_domain_observation_file,
    search_domain_observations,
)
from imaging_scientist.memory.types import (
    DistillationRole,
    DomainFrontmatterModel,
    DomainKind,
    EMAHints,
)


class SmokeError(AssertionError):
    """Marker exception for smoke failures — never swallow."""


def _pass(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    raise SmokeError(msg)


def _step(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------------------
# Fixtures — synthetic artifacts imitating a real ITS run
# ---------------------------------------------------------------------------


def _build_run_artifacts(workspace: Path, run_id: str) -> None:
    art = workspace / "artifacts" / run_id
    art.mkdir(parents=True, exist_ok=True)
    (art / "metrics.json").write_text(
        json.dumps(
            {
                "task_type": "predict",
                "reported": {"MAE": 3.12, "RMSE": 4.85, "MAPE": 7.1},
                "horizons": [15, 30, 60],
                "primary_metric_value": 3.12,
                "baseline_metric_value": 4.55,
                "higher_is_better": False,
                "beat_baseline": True,
            }
        ),
        encoding="utf-8",
    )
    (art / "provenance.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "split_protocol": "temporal_80_10_10",
                "road_network_fingerprint": "metr_la_v1",
                "reproducibility_score": 0.88,
                "data_leakage_flag": False,
                "sim_fidelity": "meso",
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def step_1_distill(workspace: Path, run_id: str):
    _step("Step 1 — distill() produces a DIRECTION_POSITIVE entry")
    art = workspace / "artifacts" / run_id
    metrics = json.loads((art / "metrics.json").read_text(encoding="utf-8"))
    provenance = json.loads((art / "provenance.json").read_text(encoding="utf-8"))

    entry = distill(
        DistillationInput(
            domain=DomainKind.ITS,
            trajectory_summary="Smoke: GAT+GRU on METR-LA beat DCRNN baseline",
            ema_hints=EMAHints(write_MI_positive=True),
            run_id=run_id,
            metrics_json=metrics,
            provenance_json=provenance,
        )
    )
    if entry is None:
        _fail("distill returned None")
    if entry.role != DistillationRole.DIRECTION_POSITIVE:
        _fail(f"expected DIRECTION_POSITIVE, got {entry.role}")
    if not (0.0 <= entry.utility_score <= 1.0):
        _fail(f"utility_score out of [0,1]: {entry.utility_score}")
    _pass(
        f"role={entry.role.value}, "
        f"utility_score={entry.utility_score:.3f}, "
        f"task_type={entry.domain_metadata.task_type}"
    )
    _pass(f"summary: {entry.summary}")
    return entry


def step_2_record(memory_dir: Path, entry) -> dict:
    _step("Step 2 — record_domain_observation_file() writes to disk")
    domain_model = DomainFrontmatterModel.from_dataclass(entry.domain_metadata)
    result = record_domain_observation_file(
        memory_dir=memory_dir,
        project_id="smoke-proj",
        domain=domain_model,
        memory_type=entry.memory_type,
        summary=entry.summary,
        observation=entry.body,
        why_it_matters=entry.why_it_matters,
        source_agent="smoke_test",
        source_session_id="smoke-sess-01",
    )
    if not result.get("created"):
        _fail(f"observation not created (result={result})")
    expected_fragment = f"observations/domain/its/{entry.role.value}"
    if expected_fragment not in result["path"]:
        _fail(
            f"path missing domain segment: got {result['path']!r}, "
            f"expected substring {expected_fragment!r}"
        )
    _pass(f"path: {result['path']}")
    _pass(f"observation_id: {result['observation_id']}")
    return result


def step_3_verify_disk(memory_dir: Path, result: dict) -> None:
    _step("Step 3 — verify disk file has proper domain frontmatter")
    import yaml

    rel = result["path"].replace("/memories/", "")
    disk_path = memory_dir / rel.lstrip("/")
    if not disk_path.is_file():
        _fail(f"file not on disk: {disk_path}")
    content = disk_path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        _fail("file does not start with YAML frontmatter")
    fm_text = content.split("---\n", 2)[1]
    fm = yaml.safe_load(fm_text)
    if "domain" not in fm:
        _fail("frontmatter missing 'domain' key")
    dom = fm["domain"]
    if dom.get("domain") != "its":
        _fail(f"domain != 'its': {dom.get('domain')!r}")
    if dom.get("role") != "direction_positive":
        _fail(f"role != 'direction_positive': {dom.get('role')!r}")
    if "utility_score" not in dom:
        _fail("frontmatter.domain missing utility_score")
    _pass(f"frontmatter.domain = {dom}")


def step_4_search(memory_dir: Path):
    _step("Step 4 — search_domain_observations() retrieves the entry")
    hits = search_domain_observations(
        memory_dir=memory_dir,
        domain=DomainKind.ITS,
        query="GAT GRU beat baseline",
        role_filter=(DistillationRole.DIRECTION_POSITIVE,),
        limit=5,
    )
    if not hits:
        _fail("no hits returned")
    top = hits[0]
    if "its" not in top["summary"].lower():
        _fail(f"top hit missing 'its' marker: {top['summary']}")
    _pass(f"top hit: {top['summary']}  (score={top.get('score', 0):.3f})")


def step_5_filter_out(memory_dir: Path):
    _step("Step 5 — role_filter=STRATEGY excludes positive entries")
    hits = search_domain_observations(
        memory_dir=memory_dir,
        domain=DomainKind.ITS,
        query="GAT GRU beat baseline",
        role_filter=(DistillationRole.STRATEGY,),
        limit=5,
    )
    if hits:
        _fail(f"unexpected hits under STRATEGY filter: {[h['summary'] for h in hits]}")
    _pass("no strategy entries surfaced (as expected — we only wrote a positive)")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    print("Domain-EMA smoke test — synthetic ITS run")
    tmp = Path(tempfile.mkdtemp(prefix="evo22-smoke-"))
    try:
        workspace = tmp / "workspace"
        memory_dir = tmp / "memories"
        workspace.mkdir()
        memory_dir.mkdir()

        run_id = "run-smoke-001"
        _build_run_artifacts(workspace, run_id)

        entry = step_1_distill(workspace, run_id)
        result = step_2_record(memory_dir, entry)
        step_3_verify_disk(memory_dir, result)
        step_4_search(memory_dir)
        step_5_filter_out(memory_dir)

        print("\nAll steps PASSED.")
        print(f"Artifacts left in: {tmp}")
        print("(delete manually or wire cleanup into your CI runner)")
        return 0
    except SmokeError as exc:
        print(f"\nSMOKE FAILED: {exc}")
        print(f"Debug artifacts kept at: {tmp}")
        return 1
    finally:
        # Only clean on success — keep failure artifacts for post-mortem.
        pass


if __name__ == "__main__":
    sys.exit(main())
