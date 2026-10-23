"""Domain-EMA middleware: run distillation after a subagent's memory pass.

Wires the Domain-EMA distiller (``memory.agents.domain_ema.distill``) into the
subagent memory worker's ``after_agent`` lifecycle. Reads three keys from the
worker's ``configurable`` payload:

    - ``evomemory_domain``      : DomainKind value ("its" / ...)
    - ``evomemory_run_id``      : id of the artifacts/<run_id>/ dir to inspect
    - ``evomemory_ema_hints``   : JSON-serialized :class:`EMAHints`

Metrics and provenance are read from ``artifacts/<run_id>/metrics.json`` and
``artifacts/<run_id>/provenance.json`` under the workspace root. Missing files
degrade gracefully: the classifier still runs on the trajectory summary alone.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

from ..observations.store import record_domain_observation_file
from ..types import (
    DomainFrontmatterModel,
    DomainKind,
    EMAHints,
)
from .domain_ema import DistillationInput, DistilledEntry, distill

logger = logging.getLogger(__name__)


class DomainEMAMiddleware(AgentMiddleware):
    """Post-run middleware that persists domain-scoped distilled observations."""

    name = "evomemory_domain_ema"

    def __init__(
        self,
        *,
        memory_dir: str | Path,
        workspace_dir: str | Path,
    ) -> None:
        super().__init__()
        self._memory_dir = Path(memory_dir).expanduser()
        self._workspace_dir = Path(workspace_dir).expanduser()

    # ------------------------------------------------------------------ hooks

    def after_agent(
        self,
        state: AgentState[object],
        runtime: Runtime,
    ) -> dict[str, object] | None:
        self._maybe_distill(state)
        return None

    async def aafter_agent(
        self,
        state: AgentState[object],
        runtime: Runtime,
    ) -> dict[str, object] | None:
        # Distillation is CPU/IO-bound (json+md file writes); keep it sync for
        # simplicity — this callback runs at graph end, not on the hot path.
        self._maybe_distill(state)
        return None

    # ------------------------------------------------------------------ core

    def _maybe_distill(self, state: AgentState[object]) -> None:
        cfg = _current_configurable()
        raw_domain = _config_str(cfg, "evomemory_domain")
        if not raw_domain:
            return  # Not a domain-tagged run — leave to the generic worker.
        try:
            domain = DomainKind(raw_domain)
        except ValueError:
            logger.warning("Unknown evomemory_domain=%r; skipping distillation", raw_domain)
            return

        run_id = _config_str(cfg, "evomemory_run_id")
        project_id = _config_str(cfg, "evomemory_project_id") or "default"
        source_agent = _config_str(cfg, "evomemory_source_agent") or "unknown_agent"
        session_id = _config_str(cfg, "evomemory_source_session_id") or ""

        hints = _parse_hints(cfg.get("evomemory_ema_hints"))
        metrics = _load_json(self._workspace_dir, run_id, "metrics.json")
        provenance = _load_json(self._workspace_dir, run_id, "provenance.json")
        trajectory_summary = _extract_trajectory_summary(state)

        inp = DistillationInput(
            domain=domain,
            trajectory_summary=trajectory_summary,
            ema_hints=hints,
            run_id=run_id,
            metrics_json=metrics,
            provenance_json=provenance,
        )
        entry = distill(inp)
        if entry is None:
            return

        try:
            _persist_entry(
                memory_dir=self._memory_dir,
                project_id=project_id,
                source_agent=source_agent,
                session_id=session_id,
                entry=entry,
            )
        except Exception as exc:  # noqa: BLE001 — never break the run for memory writes
            logger.exception("Domain-EMA persist failed: %s", exc)


# ---------------------------------------------------------------------------
# Helpers — no external deps beyond stdlib + pydantic (already required).
# ---------------------------------------------------------------------------


def _persist_entry(
    *,
    memory_dir: Path,
    project_id: str,
    source_agent: str,
    session_id: str,
    entry: DistilledEntry,
) -> None:
    if not session_id.strip():
        # record_domain_observation_file requires a non-empty session id; the
        # worker should always supply one, but guard defensively so unit tests
        # of the middleware can synthesize a fallback.
        session_id = "domain-ema-fallback"
    domain_model = DomainFrontmatterModel.from_dataclass(entry.domain_metadata)
    record_domain_observation_file(
        memory_dir=memory_dir,
        project_id=project_id,
        domain=domain_model,
        memory_type=entry.memory_type,
        summary=entry.summary,
        observation=entry.body,
        why_it_matters=entry.why_it_matters,
        source_agent=source_agent,
        source_session_id=session_id,
        scope=entry.scope,
    )


def _current_configurable() -> Mapping[str, object]:
    try:
        config = get_config()
    except RuntimeError:
        return {}
    configurable = config.get("configurable", {})
    return configurable if isinstance(configurable, dict) else {}


def _config_str(cfg: Mapping[str, object], key: str) -> str | None:
    value = cfg.get(key)
    return value if isinstance(value, str) and value else None


def _parse_hints(raw: object) -> EMAHints | None:
    if raw is None:
        return None
    if isinstance(raw, EMAHints):
        return raw
    if isinstance(raw, Mapping):
        try:
            return EMAHints.model_validate(dict(raw))
        except Exception:
            return None
    if isinstance(raw, str) and raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            try:
                return EMAHints.model_validate(payload)
            except Exception:
                return None
    return None


def _load_json(
    workspace_dir: Path,
    run_id: str | None,
    filename: str,
) -> dict[str, Any] | None:
    if not run_id:
        return None
    path = workspace_dir / "artifacts" / run_id / filename
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _extract_trajectory_summary(state: AgentState[object]) -> str:
    """Best-effort summary extraction; falls back to '' for graceful degradation."""
    structured = state.get("structured_response") if isinstance(state, Mapping) else None
    if structured is not None:
        # SubagentMemoryDecision or similar pydantic model with .summary attr
        summary = getattr(structured, "summary", None)
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
        if isinstance(structured, Mapping):
            summary = structured.get("summary")
            if isinstance(summary, str) and summary.strip():
                return summary.strip()
    messages = state.get("messages") if isinstance(state, Mapping) else None
    if isinstance(messages, list):
        for message in reversed(messages):
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return content.strip()[:2000]
    return ""
