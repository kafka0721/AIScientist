"""Workspace-scoped literature import exposed to main and research agents."""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool

from imaging_scientist import paths
from imaging_scientist.config import DomainEMAControls, get_effective_config
from imaging_scientist.memory.literature import import_literature_candidates


@tool(parse_docstring=True)
def import_domain_memory(path: str, dry_run: bool = True) -> str:
    """Validate or import literature candidates from a workspace JSONL file.

    Use dry_run first to inspect eligible, deferred and invalid entries. Call
    with dry_run=False to persist eligible entries using the configured memory
    store. This does not need execute, experiment metrics or rebuttal hints.
    Sources must be local PDFs inside the workspace. Literature remains marked
    source_unverified and is never presented as a locally validated experiment.
    Returns per-row IDs, write status, readback and retrieval verification.

    Args:
        path: Workspace-relative path to memory_candidates.jsonl.
        dry_run: True validates without writes; False imports eligible entries.
    """
    try:
        controls = DomainEMAControls.from_config(get_effective_config())
        if not controls.enabled:
            return json.dumps(
                {"error": "Domain-EMA is disabled; enable it in project configuration."}
            )
        result = import_literature_candidates(
            workspace=paths._active_workspace,
            memory_dir=Path(paths.MEMORIES_DIR),
            path=path,
            dry_run=dry_run,
            expected_domain=controls.domain,
        )
        return json.dumps(result, ensure_ascii=False)
    except (ValueError, OSError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
