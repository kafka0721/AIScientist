"""Thin enforcement adapter for the independent rebuttal agent."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Annotated, Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain.tools import InjectedToolCallId, ToolRuntime
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import interrupt

from ..rebuttal import (
    HumanNextStep,
    HumanRebuttalDecision,
    RebuttalAgent,
    ReviewAction,
    Verdict,
    rebuild_rebuttal_state,
)
from ..rebuttal.state import make_record

if TYPE_CHECKING:
    from langchain.agents.middleware.types import ToolCallRequest
    from langgraph.types import Command


logger = logging.getLogger(__name__)

_EXECUTION_TOOLS = {"execute", "run_in_background"}
_EXECUTING_SUBAGENTS = {
    "code-agent",
    "debug-agent",
    "data-analysis-agent",
    "writing-agent",
}

REBUTTAL_AGENT_PROMPT = """<rebuttal_agent_review>
An independent rebuttal agent owns scientific clearance for end-to-end research.
There is no R1/R2/R3 submission protocol and no separate plan-approval tool.

This protocol applies to requested experiment execution, not literature reading,
PDF extraction, memory ingestion, directory inspection, or drafting experiment
plans. Paper titles containing Benchmarking are not requests to run benchmarks.
For those preparation tasks, use normal tools without requesting scientific
clearance. Do not switch tools to circumvent a blocked experiment.

Before executing a requested experiment, call request_rebuttal_review with
requested_action="execute" and submit the complete hypothesis and experiment plan.
The rebuttal agent internally checks hypothesis quality and experiment design.
Present its opinion, then call confirm_rebuttal_next_step. That tool directly asks
the human to select proceed, revise, or stop and pauses until they answer. Do not
execute before the human selects proceed. If the human selects revise, follow their
instructions, update the hypothesis or plan, and request a fresh review.

Before delivering a final research result, call request_rebuttal_review with
requested_action="finalize" and provide the complete report plus metrics.json,
provenance.json, and the Markdown report path. The agent internally re-checks the
hypothesis and design and then checks result evidence. A revise verdict requires a
corrected resubmission; a kill verdict stops the current research direction.
Present the full opinion. A passing opinion must include pass criteria and optimization
suggestions; a failing opinion must include an iteration plan. Then call
confirm_rebuttal_next_step and wait for the human decision before finalizing or revising.

The adapter only enforces the agent's decision; it performs no scientific review.
Current review status: {status}
</rebuttal_agent_review>"""


def _messages_from_runtime(runtime: ToolRuntime | None) -> list[Any]:
    state = getattr(runtime, "state", None)
    if isinstance(state, dict):
        messages = state.get("messages", [])
        return list(messages) if isinstance(messages, Iterable) else []
    return []


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        values = []
        for block in content:
            if isinstance(block, str):
                values.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                values.append(block["text"])
        return "\n".join(values)
    return ""


def _looks_like_research_workflow(text: str) -> bool:
    """Match execution intent, not subject words in titles or source material.

    This is workflow routing, not a shell safety classifier. A literature label
    never exempts an explicit experiment request in another clause.
    """
    for clause in re.split(
        r"[\n.!?。\uff01\uff1f;\uff1b，,]|\b(?:and then|and|then)\s+"
        r"(?=(?:run|conduct|execute|benchmark|reproduce|train)\b)",
        text.lower(),
    ):
        clause = clause.strip(" \t`*-0123456789)")
        if re.match(r"(?:please\s+)?(?:do not|don't|never)\b", clause):
            continue
        if re.match(r"(?:请)?(?:不要|无需|禁止|不必|不需要|暂不)", clause):
            continue
        # A directive must precede an experiment action. Mere mentions of
        # benchmark/reproduce/research project no longer activate the gate.
        if re.match(
            r"(?:(?:please|now|then|and|also)\s+)*"
            r"(?:(?:can|could|would) you\s+|i (?:want|need) (?:you )?to\s+|let's\s+)?"
            r"(?:(?:run|conduct|execute)\s+(?:(?:a|an|the|another|new)\s+)*"
            r"(?:experiments?\b|benchmarks?\b|scientific study\b|research project\b)"
            r"|(?:implement|train)\s+and\s+evaluate\b"
            r"|(?:benchmark|reproduce)\s+(?:(?:the|this|a|an)\s+)?"
            r"(?:model|method|baseline|paper|results?|experiment)\b"
            r"|(?:train|evaluate)\s+(?:(?:the|this|a|an)\s+)?model\b)",
            clause,
        ):
            return True
        if re.match(
            r"(?:(?:请|现在|然后|接着|并且|并|再|帮我|开始|实际|直接|立即))*"
            r"(?:运行(?:一个|一次|这个|该)?(?:实验|基准测试)"
            r"|开展实验|执行实验|复现实验|实现并评估|训练并评估"
            r"|训练(?:这个|该)?模型|复现(?:这篇|该)?论文(?:的)?(?:实验|结果)"
            r"|开展端到端研究)",
            clause,
        ):
            return True
    return False


def _last_human_message(messages: list[Any]) -> Any | None:
    return next(
        (
            message
            for message in reversed(messages)
            if isinstance(message, HumanMessage)
        ),
        None,
    )


def research_review_required(messages: list[Any]) -> bool:
    """Return whether this user turn is an end-to-end research workflow."""
    human = _last_human_message(messages)
    if human is None:
        return False
    return _looks_like_research_workflow(_message_text(human))


def _tool_is_execution_capable(name: str, args: dict[str, Any]) -> bool:
    if name in _EXECUTION_TOOLS:
        return True
    if name in {"task", "start_async_task"}:
        return args.get("subagent_type") in _EXECUTING_SUBAGENTS
    return name == "update_async_task"


def _format_review_opinion(decision: Any) -> str:
    lines = [
        f"Verdict: {decision.verdict.value}",
        f"Review: {decision.summary}",
    ]
    sections = (
        ("Required revisions", decision.required_revisions),
        ("Pass criteria", decision.pass_criteria),
        ("Optimization suggestions", decision.optimization_suggestions),
        ("Iteration plan", decision.iteration_plan),
    )
    for title, values in sections:
        if values:
            lines.append(f"{title}: " + "; ".join(values))
    return "\n".join(lines)


def _parse_human_next_step(response: object) -> tuple[HumanNextStep, str] | None:
    if not isinstance(response, dict) or response.get("status") != "answered":
        return None
    answers = response.get("answers")
    if not isinstance(answers, list) or not answers:
        return None
    aliases = {
        "proceed": HumanNextStep.PROCEED,
        "revise": HumanNextStep.REVISE,
        "stop": HumanNextStep.STOP,
        "继续执行": HumanNextStep.PROCEED,
        "修改": HumanNextStep.REVISE,
        "停止": HumanNextStep.STOP,
    }
    selected = aliases.get(str(answers[0]).strip().lower())
    if selected is None:
        return None
    instructions = str(answers[1]).strip() if len(answers) > 1 else ""
    return selected, instructions


class RebuttalAgentMiddleware(AgentMiddleware):
    """Expose the rebuttal agent and enforce only its clearance decisions."""

    name = "rebuttal_agent"

    def __init__(self, rebuttal_agent: Any) -> None:
        super().__init__()
        self._rebuttal_agent = rebuttal_agent

        @tool(parse_docstring=True)
        async def request_rebuttal_review(
            requested_action: ReviewAction,
            submission: str,
            evidence_paths: list[str],
            runtime: ToolRuntime = None,
        ) -> str:
            """Ask the independent agent for execution or finalization clearance.

            Args:
                requested_action: Action to clear: execute or finalize.
                submission: Complete hypothesis, plan, or report to review.
                evidence_paths: Workspace evidence files visible to the agent.
            """
            try:
                decision = await self._rebuttal_agent.areview(
                    requested_action=requested_action,
                    submission=submission,
                    evidence_paths=evidence_paths,
                )
            except Exception as exc:
                logger.exception(
                    "Rebuttal agent failed closed (action=%s)",
                    requested_action.value,
                )
                reason = (
                    f"agent protocol/evidence failure ({type(exc).__name__}): {exc}"
                )
                return make_record(
                    kind="review_error",
                    requested_action=requested_action,
                    error=reason,
                    message=f"{requested_action.value} review_error: {reason}",
                )
            return make_record(
                kind="review",
                requested_action=requested_action,
                decision=decision,
                message=(
                    f"{requested_action.value} verdict={decision.verdict.value}: "
                    f"{decision.summary}"
                ),
            )

        @tool(parse_docstring=True)
        def confirm_rebuttal_next_step(
            requested_action: ReviewAction,
            tool_call_id: Annotated[str, InjectedToolCallId],
            runtime: ToolRuntime = None,
        ) -> str:
            """Ask the human to select and record the next step after a review.

            Args:
                requested_action: Reviewed action: execute or finalize.
            """
            state = rebuild_rebuttal_state(_messages_from_runtime(runtime))
            agent_decision = state.decisions.get(requested_action)
            if agent_decision is None:
                return make_record(
                    kind="status",
                    message="BLOCKED: request rebuttal-agent review first",
                )
            review_summary = _format_review_opinion(agent_decision)
            response = interrupt(
                {
                    "type": "ask_user",
                    "tool_call_id": tool_call_id,
                    "questions": [
                        {
                            "question": (
                                f"Rebuttal Agent review for {requested_action.value}:\n"
                                f"{review_summary}\n\nChoose the next step."
                            ),
                            "type": "multiple_choice",
                            "choices": [
                                {"value": "proceed"},
                                {"value": "revise"},
                                {"value": "stop"},
                            ],
                            "required": True,
                        },
                        {
                            "question": (
                                "For revise, enter concrete modification instructions. "
                                "For proceeding against a non-pass review, enter the "
                                "override rationale. Otherwise this may be left blank."
                            ),
                            "type": "text",
                            "required": False,
                        },
                    ],
                }
            )
            parsed = _parse_human_next_step(response)
            if parsed is None:
                return make_record(
                    kind="status",
                    message="BLOCKED: no valid human next-step decision was received",
                )
            next_step, instructions = parsed
            if (
                next_step == HumanNextStep.PROCEED
                and agent_decision.verdict != Verdict.PASS
                and not instructions.strip()
            ):
                return make_record(
                    kind="status",
                    message=(
                        "BLOCKED: proceeding against a non-pass opinion requires "
                        "an explicit human override rationale"
                    ),
                )
            human_decision = HumanRebuttalDecision(
                requested_action=requested_action,
                next_step=next_step,
                review_summary=review_summary,
                instructions=instructions,
            )
            return make_record(
                kind="human_decision",
                requested_action=requested_action,
                human_decision=human_decision,
                message=(
                    f"Human selected {next_step.value} after "
                    f"{requested_action.value} review."
                ),
            )

        @tool(parse_docstring=True)
        def rebuttal_agent_status(runtime: ToolRuntime = None) -> str:
            """Return the current rebuttal-agent clearance status."""
            state = rebuild_rebuttal_state(_messages_from_runtime(runtime))
            return make_record(kind="status", message=state.status_text())

        self.tools = [
            request_rebuttal_review,
            confirm_rebuttal_next_step,
            rebuttal_agent_status,
        ]

    def _modify_request(self, request: ModelRequest) -> ModelRequest:
        from deepagents.middleware._utils import append_to_system_message

        state = rebuild_rebuttal_state(request.messages)
        if not research_review_required(request.messages) and not (
            state.decisions or state.errors or state.human_decisions
        ):
            return request
        new_system = append_to_system_message(
            request.system_message,
            REBUTTAL_AGENT_PROMPT.format(status=state.status_text()),
        )
        return request.override(system_message=new_system)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._modify_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._modify_request(request))

    def _blocked_tool_message(self, request: ToolCallRequest) -> ToolMessage:
        messages = list((request.state or {}).get("messages", []))
        state = rebuild_rebuttal_state(messages)
        if state.stopped:
            message = f"BLOCKED: {state.status_text()}"
        elif state.can_finalize:
            message = (
                "BLOCKED: finalization is already cleared; execution would "
                "invalidate it"
            )
        else:
            message = (
                "BLOCKED: request execute clearance from rebuttal-agent before "
                "using execution-capable tools"
            )
        return ToolMessage(
            content=make_record(kind="status", message=message),
            tool_call_id=request.tool_call["id"],
            name=request.tool_call.get("name", "unknown_tool"),
            status="error",
        )

    def _should_block_tool(self, request: ToolCallRequest) -> bool:
        name = request.tool_call.get("name", "")
        args = request.tool_call.get("args") or {}
        if not _tool_is_execution_capable(name, args):
            return False
        messages = list((request.state or {}).get("messages", []))
        state = rebuild_rebuttal_state(messages)
        if not research_review_required(messages) and not (
            state.decisions or state.errors or state.human_decisions
        ):
            return False
        return not state.can_execute

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        if self._should_block_tool(request):
            return self._blocked_tool_message(request)
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        if self._should_block_tool(request):
            return self._blocked_tool_message(request)
        return await handler(request)


def create_rebuttal_agent_middleware(
    *,
    reviewer_model: Any,
    workspace_dir: str,
    memory_dir: str | None = None,
    enable_its_domain_references: bool = False,
) -> RebuttalAgentMiddleware:
    from pathlib import Path

    from ..rebuttal.references import DomainEMAReferenceProvider
    from ..rebuttal.reviewer import load_traffic_ood_review_guidance

    provider = None
    guidance = ""
    if enable_its_domain_references:
        if memory_dir is None:
            raise ValueError("memory_dir is required for Domain-EMA references")
        provider = DomainEMAReferenceProvider(
            memory_dir=Path(memory_dir),
            workspace_dir=Path(workspace_dir),
        )
        guidance = load_traffic_ood_review_guidance()
    return RebuttalAgentMiddleware(
        RebuttalAgent(
            reviewer_model,
            workspace_dir,
            reference_provider=provider,
            domain_guidance=guidance,
        )
    )
