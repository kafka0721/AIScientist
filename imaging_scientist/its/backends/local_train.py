"""Local training / evaluation backend for ``task_type: predict``."""

from __future__ import annotations

import json
import sys
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


def _script_command(script: str, args: list[str], *, run_id: str, art: Path) -> list[str]:
    return [
        sys.executable,
        script,
        "--run-id",
        run_id,
        "--artifacts-dir",
        str(art),
        *args,
    ]


def run_local_train(
    config: ExpConfig,
    *,
    workspace: Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run train (+ optional eval) scripts and collect metrics.json."""
    workdir = (workspace / config.workdir).resolve()
    run_id = run_id or new_run_id(config.name)
    art = artifacts_dir(workdir, run_id)

    train_path = workdir / config.train_script
    if not train_path.is_file():
        raise FileNotFoundError(f"train script not found: {train_path}")

    train_cmd = _script_command(
        config.train_script, config.train_args, run_id=run_id, art=art
    )
    write_provenance(
        art,
        run_id=run_id,
        config=config.to_dict(),
        command=train_cmd,
        workdir=workdir,
        extra={"backend": "local_train", "phase": "train"},
    )

    train_result = run_command(
        train_cmd,
        cwd=workdir,
        timeout_sec=config.timeout_sec,
        env={"ITS_RUN_ID": run_id, "ITS_ARTIFACTS_DIR": str(art)},
        log_path=art / "train.log",
    )
    if train_result.returncode != 0:
        return {
            "ok": False,
            "run_id": run_id,
            "artifacts_dir": str(art),
            "phase": "train",
            "returncode": train_result.returncode,
            "stderr_tail": (train_result.stderr or "")[-2000:],
        }

    eval_path = workdir / config.eval_script
    if eval_path.is_file():
        eval_cmd = _script_command(
            config.eval_script, config.eval_args, run_id=run_id, art=art
        )
        eval_result = run_command(
            eval_cmd,
            cwd=workdir,
            timeout_sec=config.timeout_sec,
            env={"ITS_RUN_ID": run_id, "ITS_ARTIFACTS_DIR": str(art)},
            log_path=art / "eval.log",
        )
        if eval_result.returncode != 0:
            return {
                "ok": False,
                "run_id": run_id,
                "artifacts_dir": str(art),
                "phase": "eval",
                "returncode": eval_result.returncode,
                "stderr_tail": (eval_result.stderr or "")[-2000:],
            }

    metrics = load_metrics_file(art / "metrics.json")
    if metrics is None:
        # Allow scripts that print a final JSON object on stdout
        for log_name in ("eval.log", "train.log"):
            log = art / log_name
            if not log.is_file():
                continue
            text = log.read_text(encoding="utf-8", errors="replace")
            for line in reversed(text.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        metrics = parsed
                        write_metrics(art, metrics)
                        break
            if metrics is not None:
                break

    if metrics is None:
        return {
            "ok": False,
            "run_id": run_id,
            "artifacts_dir": str(art),
            "phase": "metrics",
            "error": "metrics.json missing after train/eval",
        }

    return {
        "ok": True,
        "run_id": run_id,
        "artifacts_dir": str(art),
        "metrics": metrics,
        "backend": "local_train",
    }
