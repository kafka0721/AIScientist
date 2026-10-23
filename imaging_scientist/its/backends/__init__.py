"""Backend helpers shared by ITS experiment runners."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def new_run_id(name: str = "exp") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:40]
    return f"{stamp}_{safe}"


def artifacts_dir(workdir: Path, run_id: str) -> Path:
    path = workdir / "artifacts" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def git_hash(workdir: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def write_provenance(
    art_dir: Path,
    *,
    run_id: str,
    config: dict[str, Any],
    command: list[str],
    workdir: Path,
    extra: dict[str, Any] | None = None,
) -> Path:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cwd": str(workdir.resolve()),
        "python": sys.executable,
        "command": command,
        "config": config,
        "git_hash": git_hash(workdir),
        "env": {
            "WITAISCIENTIST_ITS_PROFILE": os.environ.get("WITAISCIENTIST_ITS_PROFILE"),
            "WITAISCIENTIST_PROFILE": os.environ.get("WITAISCIENTIST_PROFILE"),
        },
    }
    if extra:
        payload["extra"] = extra
    path = art_dir / "provenance.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_metrics(art_dir: Path, metrics: dict[str, Any]) -> Path:
    path = art_dir / "metrics.json"
    path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return path


def load_metrics_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_sec: int,
    env: dict[str, str] | None = None,
    log_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        env=merged,
        check=False,
    )
    if log_path is not None:
        log_path.write_text(
            f"$ {' '.join(command)}\n\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}\n"
            f"exit_code={result.returncode}\n",
            encoding="utf-8",
        )
    return result
