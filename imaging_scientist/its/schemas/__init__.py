"""Experiment configuration schema for the ITS Experiment Runner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

import yaml

TaskType = Literal["predict", "control", "joint"]


@dataclass
class ExpConfig:
    """Unified experiment config loaded from ``configs/exp.yaml``."""

    task_type: TaskType = "predict"
    name: str = "exp"
    seed: int = 42
    # Working directory relative to workspace root (usually ".")
    workdir: str = "."
    # Entrypoint scripts relative to workdir
    train_script: str = "train.py"
    eval_script: str = "eval.py"
    simulate_script: str = "simulate.py"
    # Extra CLI args appended to the entrypoint (list of strings)
    train_args: list[str] = field(default_factory=list)
    eval_args: list[str] = field(default_factory=list)
    simulate_args: list[str] = field(default_factory=list)
    # Dataset / model free-form metadata (for provenance only)
    dataset: str = ""
    model: str = ""
    # Primary metric names expected in metrics.json
    metrics: list[str] = field(default_factory=list)
    # Soft budget hints
    max_epochs: int | None = None
    timeout_sec: int = 3600
    # Backend selection
    backend: str = "local_train"  # local_train | sumo_docker | joint
    # SUMO / Docker (control & joint)
    sumo_compose_file: str = "docker-compose.sumo.yml"
    sumo_service: str = "sumo"
    # Joint: path to prediction metrics or demand file consumed by control
    demand_from_run: str = ""
    demand_artifact: str = "predictions.json"
    # Extra opaque knobs passed through to backends
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_exp_config(path: str | Path) -> ExpConfig:
    """Load and validate an experiment YAML config."""
    cfg_path = Path(path)
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Experiment config not found: {cfg_path}")
    with cfg_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{cfg_path}: top-level must be a mapping")

    known = {f.name for f in fields(ExpConfig)}
    nested: dict[str, Any] = {}
    if "train" in raw and isinstance(raw["train"], dict):
        t = raw.pop("train")
        if "script" in t:
            nested["train_script"] = t["script"]
        if "args" in t:
            nested["train_args"] = list(t["args"])
    if "eval" in raw and isinstance(raw["eval"], dict):
        e = raw.pop("eval")
        if "script" in e:
            nested["eval_script"] = e["script"]
        if "args" in e:
            nested["eval_args"] = list(e["args"])
    if "simulate" in raw and isinstance(raw["simulate"], dict):
        s = raw.pop("simulate")
        if "script" in s:
            nested["simulate_script"] = s["script"]
        if "args" in s:
            nested["simulate_args"] = list(s["args"])
    if "sumo" in raw and isinstance(raw["sumo"], dict):
        su = raw.pop("sumo")
        if "compose_file" in su:
            nested["sumo_compose_file"] = su["compose_file"]
        if "service" in su:
            nested["sumo_service"] = su["service"]

    backend_explicit = "backend" in raw

    data = {**nested, **{k: v for k, v in raw.items() if k in known}}
    extra = dict(raw.get("extra") or {})
    for k, v in raw.items():
        if k not in known and k != "extra":
            extra[k] = v
    data["extra"] = extra

    task = data.get("task_type", "predict")
    if task not in ("predict", "control", "joint"):
        raise ValueError(f"Unsupported task_type: {task!r}")

    if not backend_explicit and "backend" not in nested:
        data["backend"] = {
            "predict": "local_train",
            "control": "sumo_docker",
            "joint": "joint",
        }[task]

    return ExpConfig(**data)
