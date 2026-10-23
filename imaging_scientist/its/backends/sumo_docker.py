"""SUMO-via-Docker backend for ``task_type: control``."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from imaging_scientist.its.backends import (
    artifacts_dir,
    load_metrics_file,
    new_run_id,
    run_command,
    write_metrics,
    write_provenance,
)
from imaging_scientist.its.schemas import ExpConfig


def _docker_compose_cmd() -> list[str] | None:
    if shutil.which("docker"):
        # Prefer `docker compose` (v2 plugin)
        return ["docker", "compose"]
    return None


def run_sumo_docker(
    config: ExpConfig,
    *,
    workspace: Path,
    run_id: str | None = None,
    demand_file: Path | None = None,
) -> dict[str, Any]:
    """Run a SUMO control experiment via docker compose.

    Expected layout in the experiment workdir:
    - ``docker-compose.sumo.yml`` (or ``config.sumo_compose_file``)
    - optional ``simulate.py`` that the compose service or host may invoke
    - controller/network assets referenced by compose

    The compose project should write metrics to ``$ITS_ARTIFACTS_DIR/metrics.json``
    or the host ``simulate.py`` should produce them after compose finishes.
    """
    workdir = (workspace / config.workdir).resolve()
    run_id = run_id or new_run_id(config.name)
    art = artifacts_dir(workdir, run_id)

    env = {
        "ITS_RUN_ID": run_id,
        "ITS_ARTIFACTS_DIR": str(art),
        "ITS_WORKDIR": str(workdir),
    }
    if demand_file is not None:
        env["ITS_DEMAND_FILE"] = str(demand_file)

    simulate_only = bool((config.extra or {}).get("simulate_only"))
    compose = _docker_compose_cmd()
    up_cmd: list[str] = []

    if not simulate_only:
        if compose is None:
            return {
                "ok": False,
                "run_id": run_id,
                "artifacts_dir": str(art),
                "error": "docker not found on PATH; install Docker or set extra.simulate_only: true",
            }

        compose_file = workdir / config.sumo_compose_file
        if not compose_file.is_file():
            template = (
                Path(__file__).resolve().parent.parent
                / "templates"
                / "docker-compose.sumo.yml"
            )
            if template.is_file():
                shutil.copy(template, compose_file)
            else:
                return {
                    "ok": False,
                    "run_id": run_id,
                    "artifacts_dir": str(art),
                    "error": f"compose file missing: {compose_file}",
                }

        up_cmd = [
            *compose,
            "-f",
            str(compose_file),
            "run",
            "--rm",
            "-e",
            f"ITS_RUN_ID={run_id}",
            "-e",
            f"ITS_ARTIFACTS_DIR={art}",
            config.sumo_service,
        ]
        if config.simulate_args:
            up_cmd.extend(config.simulate_args)

    write_provenance(
        art,
        run_id=run_id,
        config=config.to_dict(),
        command=up_cmd or ["simulate_only"],
        workdir=workdir,
        extra={
            "backend": "sumo_docker",
            "simulate_only": simulate_only,
            "demand_file": str(demand_file) if demand_file else None,
        },
    )

    if not simulate_only:
        result = run_command(
            up_cmd,
            cwd=workdir,
            timeout_sec=config.timeout_sec,
            env=env,
            log_path=art / "sumo.log",
        )
        if result.returncode != 0:
            return {
                "ok": False,
                "run_id": run_id,
                "artifacts_dir": str(art),
                "phase": "sumo_docker",
                "returncode": result.returncode,
                "stderr_tail": (result.stderr or "")[-2000:],
            }

    # Host-side metrics harvest / controller wrapper
    sim_script = workdir / config.simulate_script
    if sim_script.is_file():
        import sys

        sim_cmd = [
            sys.executable,
            config.simulate_script,
            "--run-id",
            run_id,
            "--artifacts-dir",
            str(art),
            *config.simulate_args,
        ]
        sim_result = run_command(
            sim_cmd,
            cwd=workdir,
            timeout_sec=config.timeout_sec,
            env=env,
            log_path=art / "simulate.log",
        )
        if sim_result.returncode != 0:
            return {
                "ok": False,
                "run_id": run_id,
                "artifacts_dir": str(art),
                "phase": "simulate",
                "returncode": sim_result.returncode,
                "stderr_tail": (sim_result.stderr or "")[-2000:],
            }
    elif simulate_only:
        return {
            "ok": False,
            "run_id": run_id,
            "artifacts_dir": str(art),
            "error": f"simulate_only requires {config.simulate_script}",
        }

    metrics = load_metrics_file(art / "metrics.json")
    if metrics is None:
        # Parse tripinfo-style stub if present
        summary = art / "tripinfo_summary.json"
        metrics = load_metrics_file(summary)
        if metrics is not None:
            write_metrics(art, metrics)

    if metrics is None:
        # Provide a clear failure rather than inventing numbers
        placeholder = {
            "status": "no_metrics",
            "hint": "Controller/compose must write metrics.json under ITS_ARTIFACTS_DIR",
        }
        write_metrics(art, placeholder)
        return {
            "ok": False,
            "run_id": run_id,
            "artifacts_dir": str(art),
            "error": "metrics.json missing after SUMO run",
            "metrics": placeholder,
        }

    return {
        "ok": True,
        "run_id": run_id,
        "artifacts_dir": str(art),
        "metrics": metrics,
        "backend": "sumo_docker",
    }


def write_stub_control_metrics(art_dir: Path, **values: float) -> Path:
    """Helper for smoke tests without a live SUMO image."""
    metrics = {
        "avg_delay": values.get("avg_delay", 0.0),
        "throughput": values.get("throughput", 0.0),
        "avg_queue": values.get("avg_queue", 0.0),
    }
    return write_metrics(art_dir, metrics)
