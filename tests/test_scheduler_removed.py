"""Guards for removal of the user-facing scheduled-task agent."""

from __future__ import annotations

import json
from pathlib import Path

import imaging_scientist


def test_scheduler_subagent_and_graph_are_not_registered():
    root = Path(imaging_scientist.__file__).parent
    manifest = json.loads(
        (root / "langgraph_dev" / "langgraph.json").read_text(encoding="utf-8")
    )
    assert "scheduler" not in manifest["graphs"]
    assert not (root / "subagents" / "scheduler.yaml").exists()


def test_default_middleware_has_no_scheduled_task_tools():
    from imaging_scientist.middleware import __all__ as middleware_exports

    assert "SchedulerMiddleware" not in middleware_exports
    assert "create_scheduler_middleware" not in middleware_exports


def test_schedule_command_is_not_registered():
    from imaging_scientist.commands import manager

    assert manager.get_command("/schedule") is None
