"""Joint predict-then-control backend for ``task_type: joint``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from imaging_scientist.its.backends import (
    artifacts_dir,
    load_metrics_file,
    new_run_id,
    write_metrics,
    write_provenance,
)
from imaging_scientist.its.backends.local_train import run_local_train
from imaging_scientist.its.backends.sumo_docker import run_sumo_docker
from imaging_scientist.its.schemas import ExpConfig


def run_joint(
    config: ExpConfig,
    *,
    workspace: Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run prediction first, then feed demand artifacts into a control simulation.

    Flow:
    1. ``local_train`` produces ``artifacts/<pred_run>/metrics.json`` and optional
       ``predictions.json`` (or ``config.demand_artifact``).
    2. ``sumo_docker`` runs with ``ITS_DEMAND_FILE`` pointing at that artifact.
    3. A combined ``metrics.json`` is written under the joint run id.
    """
    workdir = (workspace / config.workdir).resolve()
    run_id = run_id or new_run_id(config.name)
    art = artifacts_dir(workdir, run_id)

    write_provenance(
        art,
        run_id=run_id,
        config=config.to_dict(),
        command=["joint", "predict", "->", "control"],
        workdir=workdir,
        extra={"backend": "joint"},
    )

    pred_cfg = ExpConfig(**{**config.to_dict(), "backend": "local_train", "task_type": "predict"})
    pred = run_local_train(pred_cfg, workspace=workspace, run_id=f"{run_id}_predict")
    if not pred.get("ok"):
        write_metrics(
            art,
            {"status": "predict_failed", "predict": pred},
        )
        return {
            "ok": False,
            "run_id": run_id,
            "artifacts_dir": str(art),
            "phase": "predict",
            "predict": pred,
        }

    pred_art = Path(pred["artifacts_dir"])
    demand_name = config.demand_artifact or "predictions.json"
    demand_file = pred_art / demand_name
    if not demand_file.is_file():
        # Allow metrics-only joint smoke: synthesize a tiny demand stub
        stub = {"source_run": pred["run_id"], "note": "no predictions.json; stub demand"}
        demand_file = art / "demand_stub.json"
        demand_file.write_text(json.dumps(stub, indent=2), encoding="utf-8")

    ctrl_cfg = ExpConfig(**{**config.to_dict(), "backend": "sumo_docker", "task_type": "control"})
    ctrl = run_sumo_docker(
        ctrl_cfg,
        workspace=workspace,
        run_id=f"{run_id}_control",
        demand_file=demand_file,
    )

    combined: dict[str, Any] = {
        "task_type": "joint",
        "predict_run_id": pred.get("run_id"),
        "control_run_id": ctrl.get("run_id"),
        "predict_metrics": pred.get("metrics") or load_metrics_file(pred_art / "metrics.json"),
        "control_metrics": ctrl.get("metrics"),
        "control_ok": bool(ctrl.get("ok")),
    }
    # System-level KPI helpers when both sides present
    pm = combined["predict_metrics"] or {}
    cm = combined["control_metrics"] or {}
    if isinstance(pm, dict) and isinstance(cm, dict):
        if "avg_delay" in cm:
            combined["system_avg_delay"] = cm["avg_delay"]
        if "throughput" in cm:
            combined["system_throughput"] = cm["throughput"]
        if "mae" in pm:
            combined["upstream_mae"] = pm["mae"]

    write_metrics(art, combined)

    ok = bool(pred.get("ok")) and bool(ctrl.get("ok"))
    return {
        "ok": ok,
        "run_id": run_id,
        "artifacts_dir": str(art),
        "metrics": combined,
        "predict": pred,
        "control": ctrl,
        "backend": "joint",
        "error": None if ok else ctrl.get("error") or "joint pipeline failed",
    }
