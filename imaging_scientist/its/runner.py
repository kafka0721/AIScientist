"""CLI entry for the ITS Experiment Runner.

Usage::

    python -m imaging_scientist.its run --config configs/exp.yaml
    its-runner run --config configs/exp.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from imaging_scientist.its.backends.joint import run_joint
from imaging_scientist.its.backends.local_train import run_local_train
from imaging_scientist.its.backends.sumo_docker import run_sumo_docker
from imaging_scientist.its.schemas import ExpConfig, load_exp_config


def run_experiment(
    config: ExpConfig | str | Path,
    *,
    workspace: str | Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch an experiment to the appropriate backend."""
    if not isinstance(config, ExpConfig):
        config = load_exp_config(config)
    ws = Path(workspace) if workspace else Path.cwd()

    backend = config.backend or {
        "predict": "local_train",
        "control": "sumo_docker",
        "joint": "joint",
    }.get(config.task_type, "local_train")

    if backend == "local_train":
        return run_local_train(config, workspace=ws, run_id=run_id)
    if backend == "sumo_docker":
        return run_sumo_docker(config, workspace=ws, run_id=run_id)
    if backend == "joint":
        return run_joint(config, workspace=ws, run_id=run_id)
    raise ValueError(f"Unknown backend: {backend!r}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="its-runner",
        description="EvoITS Experiment Runner — reproducible ITS experiment execution",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run an experiment from a YAML config")
    run_p.add_argument(
        "--config",
        "-c",
        required=True,
        help="Path to configs/exp.yaml",
    )
    run_p.add_argument(
        "--workspace",
        "-w",
        default=".",
        help="Workspace root (default: cwd)",
    )
    run_p.add_argument("--run-id", default=None, help="Optional explicit run id")
    run_p.add_argument(
        "--json",
        action="store_true",
        help="Print the result dict as JSON",
    )

    val_p = sub.add_parser("validate", help="Validate an experiment YAML config")
    val_p.add_argument("--config", "-c", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        cfg = load_exp_config(args.config)
        print(json.dumps(cfg.to_dict(), indent=2))
        return 0

    if args.command == "run":
        result = run_experiment(
            args.config,
            workspace=args.workspace,
            run_id=args.run_id,
        )
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            status = "OK" if result.get("ok") else "FAIL"
            print(f"[{status}] run_id={result.get('run_id')}")
            print(f"artifacts={result.get('artifacts_dir')}")
            if result.get("metrics"):
                print("metrics=", json.dumps(result["metrics"], indent=2, default=str))
            if not result.get("ok"):
                err = result.get("error") or result.get("stderr_tail") or result.get("phase")
                print(f"error={err}", file=sys.stderr)
        return 0 if result.get("ok") else 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
