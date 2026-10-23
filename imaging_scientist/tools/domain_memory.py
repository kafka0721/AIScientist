"""LangChain tool wrapper for Domain-EMA retrieval.

Exposes ``search_domain_observations`` from ``memory.observations.store`` as a
subagent-callable tool. Kept in ``tools/`` (not in ``memory/``) so it plugs into
``tool_registry`` alongside ``think_tool`` / ``tavily_search`` without pulling
memory-layer internals into the subagent factory graph.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from imaging_scientist import paths as _paths
from imaging_scientist.memory.observations.store import search_domain_observations
from imaging_scientist.memory.types import DistillationRole, DomainKind

logger = logging.getLogger(__name__)


@tool(parse_docstring=True)
def search_domain_memory(
    query: str,
    domain: str = "its",
    task_type: str | None = None,
    fingerprint: str | None = None,
    roles: str | None = None,
    limit: int = 5,
) -> str:
    """Retrieve distilled Domain-EMA observations (M_I / M_E) for the given domain.

    Call this at the START of your work when a Domain-EMA-enabled project is
    active. Two-stage retrieval: hard filter by (domain, task_type, fingerprint,
    role) then rank by cosine similarity weighted by utility_score.

    Roles you may filter by:
      - "direction_positive"  M_I+: prior positive experience (non-binding)
      - "direction_negative"  M_I-: prior negative experience (non-binding)
      - "strategy"            M_E : reusable protocols, seeds, config recipes

    Args:
        query: Free-text query. Best when it names the method/data/task
            directly (for instance "GAT+GRU METR-LA 15min MAE").
        domain: Domain key ("its", "bio", "generic"). Must match what the
            project's Domain-EMA is configured for.
        task_type: Optional hard filter (for instance "predict"/"control"/"joint"
            for ITS). Leave None to search across all task types.
        fingerprint: Optional dataset/network fingerprint hard filter (for
            instance "metr_la_v1"). Leave None to ignore.
        roles: Optional comma-separated role names to restrict results (for
            instance "direction_positive,direction_negative"). Empty means all
            roles.
        limit: Max hits to return (default 5, cap 20).

    Returns:
        JSON array of hits with keys summary, score, role, path,
        observation_id. Empty array means no memory yet or filters too tight.
    """
    query_text = query.strip()
    if not query_text:
        return json.dumps({"error": "query must not be empty", "hits": []})

    try:
        domain_kind = DomainKind(domain.strip().lower())
    except ValueError:
        return json.dumps(
            {
                "error": f"unknown domain {domain!r}; valid: {[k.value for k in DomainKind]}",
                "hits": [],
            }
        )

    role_filter: tuple[DistillationRole, ...] | None = None
    if roles:
        parsed_roles: list[DistillationRole] = []
        for name in roles.split(","):
            trimmed = name.strip().lower()
            if not trimmed:
                continue
            try:
                parsed_roles.append(DistillationRole(trimmed))
            except ValueError:
                return json.dumps(
                    {
                        "error": f"unknown role {trimmed!r}; valid: "
                        f"{[r.value for r in DistillationRole]}",
                        "hits": [],
                    }
                )
        if parsed_roles:
            role_filter = tuple(parsed_roles)

    capped_limit = max(1, min(20, int(limit)))

    try:
        hits = search_domain_observations(
            memory_dir=Path(_paths.MEMORIES_DIR),
            domain=domain_kind,
            query=query_text,
            task_type=task_type,
            fingerprint=fingerprint,
            role_filter=role_filter,
            limit=capped_limit,
        )
    except Exception as exc:  # noqa: BLE001 — tool must never crash caller
        logger.exception("search_domain_memory failed: %s", exc)
        return json.dumps({"error": str(exc), "hits": []})

    # Slim projection: agents don't need raw related_observations tuples here.
    slim: list[dict[str, Any]] = []
    for h in hits:
        slim.append(
            {
                "summary": h.get("summary"),
                "score": round(float(h.get("score", 0.0)), 4),
                "path": h.get("path"),
                "observation_id": h.get("observation_id"),
                "role": h.get("role"),
                "evidence_source": h.get("evidence_source"),
                "evidence_status": h.get("evidence_status"),
            }
        )
    return json.dumps({"count": len(slim), "hits": slim}, ensure_ascii=False)
