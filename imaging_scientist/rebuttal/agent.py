"""Independent rebuttal agent graph and isolated invocation adapter."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph

from .references import DomainEMAReferenceProvider, format_domain_ema_references
from .reviewer import (
    REBUTTAL_REVIEWER_PROMPT,
    build_review_payload,
    validate_rebuttal_result,
)
from .types import RebuttalDecision, ReviewAction

logger = logging.getLogger(__name__)


def build_rebuttal_agent(
    model: Any,
    *,
    domain_guidance: str = "",
) -> CompiledStateGraph:
    """Build the stateless, tool-free graph used for independent review.

    ``model`` may be any LangChain chat model. In particular, imaging_scientist's
    ``dashscope`` provider supplies Qwen through Alibaba Cloud's
    OpenAI-compatible endpoint.
    """
    return create_agent(
        name="rebuttal-agent",
        model=model,
        tools=[],
        system_prompt=(
            REBUTTAL_REVIEWER_PROMPT
            + (f"\n\n<domain_review_skill>\n{domain_guidance}\n</domain_review_skill>" if domain_guidance else "")
        ),
        # Keep the model response as a mapping until our protocol validator can
        # downgrade internally inconsistent pass verdicts to revise.
        response_format=RebuttalDecision.model_json_schema(),
    )


class RebuttalAgent:
    """Fresh-context agent that returns one structured gate decision.

    The compiled graph deliberately has no tools, checkpointer, store, middleware,
    or subagents. Packaged domain guidance is immutable system context, while
    Domain-EMA arrives only as a bounded read-only snapshot. Reusing the graph is
    safe because every invocation supplies fresh state and no conversation persists.
    """

    name = "rebuttal-agent"

    def __init__(
        self,
        model: Any,
        workspace_dir: str | Path,
        *,
        graph: Any | None = None,
        reference_provider: DomainEMAReferenceProvider | None = None,
        domain_guidance: str = "",
    ) -> None:
        self._workspace_dir = Path(workspace_dir).expanduser().resolve()
        self._reference_provider = reference_provider
        self._graph = (
            graph
            if graph is not None
            else build_rebuttal_agent(model, domain_guidance=domain_guidance)
        )

    @property
    def graph(self) -> Any:
        """Expose the compiled graph for deployment and inspection surfaces."""
        return self._graph

    def _domain_references(self, submission: str) -> tuple[str, set[str]]:
        if self._reference_provider is None:
            return format_domain_ema_references([]), set()
        try:
            references = self._reference_provider.references_for(submission)
        except Exception:
            logger.warning(
                "Domain-EMA reference retrieval failed; continuing without memory",
                exc_info=True,
            )
            references = []
        return (
            format_domain_ema_references(references),
            {reference.memory_id for reference in references},
        )

    @staticmethod
    def _decision(
        result: Any,
        requested_action: ReviewAction,
        allowed_memory_ids: set[str] | None = None,
    ) -> RebuttalDecision:
        if not isinstance(result, Mapping) or "structured_response" not in result:
            raise ValueError("rebuttal agent returned no structured_response")
        decision = validate_rebuttal_result(
            result["structured_response"], requested_action
        )
        unknown = set(decision.memory_references_considered) - (
            allowed_memory_ids or set()
        )
        if unknown:
            raise ValueError(
                "rebuttal agent cited Domain-EMA references outside the supplied "
                f"snapshot: {', '.join(sorted(unknown))}"
            )
        return decision

    def review(
        self,
        *,
        requested_action: ReviewAction,
        submission: str,
        evidence_paths: list[str],
    ) -> RebuttalDecision:
        references, allowed_memory_ids = self._domain_references(submission)
        payload = build_review_payload(
            workspace_dir=self._workspace_dir,
            requested_action=requested_action,
            submission=submission,
            evidence_paths=evidence_paths,
            domain_ema_references=references,
        )
        result = self._graph.invoke(
            {"messages": [HumanMessage(content=payload)]}
        )
        return self._decision(result, requested_action, allowed_memory_ids)

    async def areview(
        self,
        *,
        requested_action: ReviewAction,
        submission: str,
        evidence_paths: list[str],
    ) -> RebuttalDecision:
        # Evidence validation and reads are blocking filesystem operations.
        def build_payload() -> tuple[str, set[str]]:
            references, allowed_memory_ids = self._domain_references(submission)
            payload = build_review_payload(
                workspace_dir=self._workspace_dir,
                requested_action=requested_action,
                submission=submission,
                evidence_paths=evidence_paths,
                domain_ema_references=references,
            )
            return payload, allowed_memory_ids

        payload, allowed_memory_ids = await asyncio.to_thread(build_payload)
        result = await self._graph.ainvoke(
            {"messages": [HumanMessage(content=payload)]}
        )
        return self._decision(result, requested_action, allowed_memory_ids)
