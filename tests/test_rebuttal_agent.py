"""Tests for unified rebuttal-agent review and its enforcement adapter."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from blockbuster import BlockBuster
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError

from imaging_scientist.middleware.rebuttal_agent import RebuttalAgentMiddleware
from imaging_scientist.rebuttal import (
    EvidenceError,
    HumanNextStep,
    HumanRebuttalDecision,
    RebuttalAgent,
    RebuttalAttack,
    RebuttalDecision,
    ReviewAction,
    ReviewCheck,
    Severity,
    Verdict,
    rebuild_rebuttal_state,
    resolve_evidence_paths,
)
from imaging_scientist.rebuttal.state import make_record


def _pass(action: ReviewAction) -> RebuttalDecision:
    checks = [ReviewCheck.HYPOTHESIS, ReviewCheck.EXPERIMENT_DESIGN]
    if action == ReviewAction.FINALIZE:
        checks.append(ReviewCheck.RESULTS_EVIDENCE)
    kwargs = {}
    if action == ReviewAction.FINALIZE:
        kwargs = {
            "pass_criteria": ["Primary metric exceeds the registered threshold."],
            "optimization_suggestions": ["Evaluate one additional seed."],
        }
    return RebuttalDecision(
        requested_action=action,
        verdict=Verdict.PASS,
        checks_applied=checks,
        surviving_hypotheses=["Method A improves metric M over baseline B."],
        summary="Clearance granted.",
        **kwargs,
    )


def _review_message(action: ReviewAction) -> ToolMessage:
    return ToolMessage(
        name="request_rebuttal_review",
        tool_call_id=f"review-{action.value}",
        content=make_record(
            kind="review",
            requested_action=action,
            decision=_pass(action),
            message="passed",
        ),
    )


def _human_decision_message(
    action: ReviewAction,
    next_step: HumanNextStep = HumanNextStep.PROCEED,
    instructions: str = "",
) -> ToolMessage:
    decision = HumanRebuttalDecision(
        requested_action=action,
        next_step=next_step,
        review_summary="Agent review presented to the human.",
        instructions=instructions,
    )
    return ToolMessage(
        name="confirm_rebuttal_next_step",
        tool_call_id=f"human-{action.value}",
        content=make_record(
            kind="human_decision",
            requested_action=action,
            human_decision=decision,
            message="human decided",
        ),
    )


def _research_messages(*actions: ReviewAction):
    messages = [
        HumanMessage(content="Run an experiment to test this model hypothesis.")
    ]
    messages.extend(_review_message(action) for action in actions)
    return messages


def test_pass_requires_all_agent_internal_checks():
    with pytest.raises(ValidationError, match="omitted required checks"):
        RebuttalDecision(
            requested_action=ReviewAction.FINALIZE,
            verdict=Verdict.PASS,
            checks_applied=[
                ReviewCheck.HYPOTHESIS,
                ReviewCheck.EXPERIMENT_DESIGN,
            ],
            surviving_hypotheses=["H"],
            summary="Missing result review.",
        )


def test_pass_with_critical_attack_is_invalid():
    with pytest.raises(ValidationError):
        RebuttalDecision(
            requested_action=ReviewAction.EXECUTE,
            verdict=Verdict.PASS,
            checks_applied=[
                ReviewCheck.HYPOTHESIS,
                ReviewCheck.EXPERIMENT_DESIGN,
            ],
            attacks=[
                RebuttalAttack(
                    claim="No leakage",
                    flaw="The test set is used for model selection.",
                    minimal_falsifier="Use a held-out validation set.",
                    severity=Severity.CRITICAL,
                )
            ],
            surviving_hypotheses=["H"],
            summary="Invalid pass.",
        )


def test_state_rebuilds_unified_clearances():
    messages = _research_messages(ReviewAction.EXECUTE)
    messages.append(_human_decision_message(ReviewAction.EXECUTE))
    messages.append(_review_message(ReviewAction.FINALIZE))
    messages.append(_human_decision_message(ReviewAction.FINALIZE))
    state = rebuild_rebuttal_state(messages)
    assert state.can_execute is False
    assert state.can_finalize is True


def test_new_agent_review_invalidates_previous_human_decision():
    messages = _research_messages(ReviewAction.EXECUTE)
    messages.append(_human_decision_message(ReviewAction.EXECUTE))
    assert rebuild_rebuttal_state(messages).can_execute is True

    messages.append(_review_message(ReviewAction.EXECUTE))
    state = rebuild_rebuttal_state(messages)
    assert state.can_execute is False
    assert ReviewAction.EXECUTE not in state.human_decisions


def test_final_review_closes_previous_execution_authorization():
    messages = _research_messages(ReviewAction.EXECUTE)
    messages.append(_human_decision_message(ReviewAction.EXECUTE))
    messages.append(_review_message(ReviewAction.FINALIZE))
    state = rebuild_rebuttal_state(messages)
    assert state.can_execute is False
    assert state.can_finalize is False
    assert state.status_text().startswith("awaiting human decision on final review")


def test_iteration_requires_fresh_execute_review_and_human_proceed():
    messages = _research_messages(ReviewAction.EXECUTE)
    messages.append(_human_decision_message(ReviewAction.EXECUTE))
    messages.append(_review_message(ReviewAction.FINALIZE))
    messages.append(
        _human_decision_message(
            ReviewAction.FINALIZE,
            HumanNextStep.REVISE,
            "Run the proposed robustness experiment.",
        )
    )
    assert rebuild_rebuttal_state(messages).can_execute is False

    messages.append(_review_message(ReviewAction.EXECUTE))
    assert rebuild_rebuttal_state(messages).can_execute is False
    messages.append(_human_decision_message(ReviewAction.EXECUTE))
    state = rebuild_rebuttal_state(messages)
    assert state.can_execute is True
    assert ReviewAction.FINALIZE not in state.decisions


def test_human_revision_is_retained_as_next_step_instructions():
    messages = _research_messages(ReviewAction.EXECUTE)
    messages.append(
        _human_decision_message(
            ReviewAction.EXECUTE,
            HumanNextStep.REVISE,
            "Add a leakage-free baseline and rerun power analysis.",
        )
    )
    state = rebuild_rebuttal_state(messages)
    assert state.can_execute is False
    assert (
        state.human_decisions[ReviewAction.EXECUTE].instructions
        == "Add a leakage-free baseline and rerun power analysis."
    )


def test_final_pass_requires_pass_criteria():
    with pytest.raises(ValidationError, match="pass criteria"):
        RebuttalDecision(
            requested_action=ReviewAction.FINALIZE,
            verdict=Verdict.PASS,
            checks_applied=list(ReviewCheck),
            surviving_hypotheses=["H"],
            optimization_suggestions=["Run another seed."],
            summary="Evidence passes.",
        )


def test_final_pass_requires_optimization_suggestions():
    with pytest.raises(ValidationError, match="optimization suggestions"):
        RebuttalDecision(
            requested_action=ReviewAction.FINALIZE,
            verdict=Verdict.PASS,
            checks_applied=list(ReviewCheck),
            surviving_hypotheses=["H"],
            pass_criteria=["Primary endpoint exceeds threshold."],
            summary="Evidence passes.",
        )


def test_failed_final_review_requires_iteration_plan():
    with pytest.raises(ValidationError, match="iteration plan"):
        RebuttalDecision(
            requested_action=ReviewAction.FINALIZE,
            verdict=Verdict.REVISE,
            checks_applied=list(ReviewCheck),
            required_revisions=["Correct the evaluation split."],
            summary="Evidence does not pass.",
        )


def test_new_user_turn_resets_old_clearance():
    messages = [
        *_research_messages(ReviewAction.EXECUTE),
        HumanMessage(content="Run another experiment on a new dataset."),
    ]
    assert rebuild_rebuttal_state(messages).can_execute is False


def test_finalization_evidence_requires_metrics_provenance_and_report(tmp_path):
    (tmp_path / "metrics.json").write_text("{}", encoding="utf-8")
    (tmp_path / "report.md").write_text("# Draft", encoding="utf-8")
    with pytest.raises(EvidenceError, match=r"provenance\.json"):
        resolve_evidence_paths(
            tmp_path,
            ["metrics.json", "report.md"],
            requested_action=ReviewAction.FINALIZE,
        )


def test_evidence_cannot_escape_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(EvidenceError, match="escapes workspace"):
        resolve_evidence_paths(
            workspace,
            [str(outside)],
            requested_action=ReviewAction.EXECUTE,
        )


async def test_agent_offloads_evidence_io_under_blockbuster(tmp_path):
    evidence = tmp_path / "evidence.md"
    evidence.write_text("A falsifiable hypothesis and plan.", encoding="utf-8")
    graph = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value={"structured_response": _pass(ReviewAction.EXECUTE)}
        )
    )
    agent = RebuttalAgent(object(), tmp_path, graph=graph)
    blocker = BlockBuster(scanned_modules=["imaging_scientist"])

    blocker.activate()
    try:
        decision = await agent.areview(
            requested_action=ReviewAction.EXECUTE,
            submission="Hypothesis and complete experiment plan.",
            evidence_paths=["evidence.md"],
        )
    finally:
        blocker.deactivate()

    assert decision.verdict == Verdict.PASS
    payload = graph.ainvoke.call_args.args[0]["messages"][0].content
    assert "REQUESTED ACTION: execute" in payload


def test_agent_factory_builds_restricted_structured_graph():
    compiled = MagicMock()
    with patch(
        "imaging_scientist.rebuttal.agent.create_agent", return_value=compiled
    ) as create:
        agent = RebuttalAgent(object(), ".")

    assert agent.graph is compiled
    kwargs = create.call_args.kwargs
    assert kwargs["name"] == "rebuttal-agent"
    assert kwargs["tools"] == []
    assert kwargs["response_format"] == RebuttalDecision.model_json_schema()


class _FailingAgent:
    async def areview(self, **_kwargs):
        raise RuntimeError("review transport failed")


async def test_agent_failure_is_logged_and_fails_closed(caplog):
    middleware = RebuttalAgentMiddleware(_FailingAgent())
    review_tool = next(
        tool for tool in middleware.tools if tool.name == "request_rebuttal_review"
    )
    with caplog.at_level(
        logging.ERROR,
        logger="imaging_scientist.middleware.rebuttal_agent",
    ):
        result = await review_tool.coroutine(
            requested_action=ReviewAction.EXECUTE,
            submission="A hypothesis and plan.",
            evidence_paths=[],
            runtime=None,
        )
    assert "Rebuttal agent failed closed (action=execute)" in caplog.text
    assert "review_error" in result


def test_human_decision_tool_gets_next_step_from_interrupt_response():
    middleware = RebuttalAgentMiddleware(MagicMock())
    decision_tool = next(
        tool for tool in middleware.tools if tool.name == "confirm_rebuttal_next_step"
    )
    messages = _research_messages(ReviewAction.EXECUTE)
    runtime = SimpleNamespace(state={"messages": messages})
    with patch(
        "imaging_scientist.middleware.rebuttal_agent.interrupt",
        return_value={
            "status": "answered",
            "answers": ["revise", "Add a stronger baseline."],
        },
    ):
        result = decision_tool.func(
            requested_action=ReviewAction.EXECUTE,
            tool_call_id="decision-call",
            runtime=runtime,
        )
    record = rebuild_rebuttal_state(
        [
            *messages,
            ToolMessage(
                name="confirm_rebuttal_next_step",
                tool_call_id="decision-call",
                content=result,
            ),
        ]
    )
    assert (
        record.human_decisions[ReviewAction.EXECUTE].next_step == HumanNextStep.REVISE
    )
    assert (
        record.human_decisions[ReviewAction.EXECUTE].instructions
        == "Add a stronger baseline."
    )


def test_human_decision_tool_schema_does_not_accept_model_selected_decision():
    middleware = RebuttalAgentMiddleware(MagicMock())
    decision_tool = next(
        tool for tool in middleware.tools if tool.name == "confirm_rebuttal_next_step"
    )
    properties = decision_tool.tool_call_schema.model_json_schema()["properties"]
    assert set(properties) == {"requested_action"}


def _middleware() -> RebuttalAgentMiddleware:
    return RebuttalAgentMiddleware(MagicMock())


def _request(name: str, messages, args=None):
    return SimpleNamespace(
        tool_call={
            "name": name,
            "args": args or {},
            "id": "call-1",
            "type": "tool_call",
        },
        state={"messages": messages},
        runtime=SimpleNamespace(state={"messages": messages}, config={}),
    )


def test_execution_is_blocked_without_agent_clearance():
    middleware = _middleware()
    request = _request("execute", _research_messages())
    handler = MagicMock()
    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    handler.assert_not_called()


def test_chinese_research_request_is_blocked_without_clearance():
    middleware = _middleware()
    messages = [HumanMessage(content="请开展实验，验证这个模型假设。")]
    request = _request("execute", messages)
    handler = MagicMock()
    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    handler.assert_not_called()


def test_execution_runs_after_agent_clearance():
    middleware = _middleware()
    messages = _research_messages(ReviewAction.EXECUTE)
    messages.append(_human_decision_message(ReviewAction.EXECUTE))
    request = _request(
        "execute",
        messages,
    )
    expected = ToolMessage(content="ok", tool_call_id="call-1", name="execute")
    handler = MagicMock(return_value=expected)
    assert middleware.wrap_tool_call(request, handler) is expected


def test_agent_pass_without_human_decision_still_blocks_execution():
    middleware = _middleware()
    request = _request(
        "execute",
        _research_messages(ReviewAction.EXECUTE),
    )
    handler = MagicMock()
    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    handler.assert_not_called()


def test_human_revision_decision_blocks_execution():
    middleware = _middleware()
    messages = _research_messages(ReviewAction.EXECUTE)
    messages.append(
        _human_decision_message(
            ReviewAction.EXECUTE,
            HumanNextStep.REVISE,
            "Strengthen the baseline comparison.",
        )
    )
    handler = MagicMock()
    result = middleware.wrap_tool_call(_request("execute", messages), handler)
    assert isinstance(result, ToolMessage)
    handler.assert_not_called()


def test_ordinary_chat_is_not_blocked():
    middleware = _middleware()
    request = _request("execute", [HumanMessage(content="List this directory.")])
    expected = ToolMessage(content="ok", tool_call_id="call-1", name="execute")
    handler = MagicMock(return_value=expected)
    assert middleware.wrap_tool_call(request, handler) is expected


@pytest.mark.parametrize(
    "prompt",
    [
        "请阅读论文 TransportationGames - Benchmarking Transportation Knowledge.pdf 并生成蒸馏候选。",
        "Summarize Benchmarking the Capabilities of Large Language Models in Transportation System Engineering.",
        "Read this paper and draft a plan to reproduce the experiment.",
        "请整理评测论文，生成实验计划。不要运行实验。",
        "Do not run an experiment. Read the benchmark paper and write notes.",
    ],
)
def test_literature_preparation_does_not_require_experiment_clearance(prompt):
    middleware = _middleware()
    request = _request("execute", [HumanMessage(content=prompt)])
    handler = MagicMock(return_value=ToolMessage(content="ok", tool_call_id="call-1"))
    assert middleware.wrap_tool_call(request, handler) is handler.return_value


@pytest.mark.parametrize(
    "prompt",
    [
        "Read the benchmark paper; then run an experiment on this model.",
        "请阅读论文，然后开展实验验证模型。",
        "Please benchmark this model on the dataset.",
        "Can you reproduce the paper results?",
        "I want to run experiments on this model.",
        "Read the paper and run an experiment on this model.",
        "请复现这篇论文的实验。",
    ],
)
def test_explicit_experiment_is_still_gated_even_with_literature_context(prompt):
    request = _request("execute", [HumanMessage(content=prompt)])
    handler = MagicMock()
    assert _middleware().wrap_tool_call(request, handler).status == "error"
    handler.assert_not_called()


def test_actual_distillation_prompt_is_not_an_experiment_request():
    from pathlib import Path

    from imaging_scientist.middleware.rebuttal_agent import research_review_required

    prompt = (
        Path(__file__).parents[1] / "docs/交通综述与评测-论文蒸馏提示词.md"
    ).read_text(encoding="utf-8")
    assert not research_review_required([HumanMessage(content=prompt)])


def test_literature_does_not_inject_experiment_approval_prompt():
    request = SimpleNamespace(
        messages=[HumanMessage(content="Read Benchmarking LLMs paper.")]
    )
    assert _middleware()._modify_request(request) is request


def test_existing_review_stop_is_not_ignored_for_literature_wording():
    messages = [HumanMessage(content="Read the benchmark paper.")]
    messages.extend(
        [
            _review_message(ReviewAction.EXECUTE),
            _human_decision_message(ReviewAction.EXECUTE, HumanNextStep.STOP),
        ]
    )
    handler = MagicMock()
    assert (
        _middleware().wrap_tool_call(_request("execute", messages), handler).status
        == "error"
    )
    handler.assert_not_called()


async def test_async_literature_execution_is_not_blocked():
    handler = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id="call-1"))
    request = _request(
        "execute", [HumanMessage(content="Read the Benchmarking paper.")]
    )
    assert await _middleware().awrap_tool_call(request, handler) is handler.return_value


def test_final_response_does_not_trigger_status_tool_loop():
    middleware = _middleware()
    messages = _research_messages(ReviewAction.EXECUTE)
    messages.append(_human_decision_message(ReviewAction.EXECUTE))
    messages.append(AIMessage("done"))
    # Execution is protected at tool-call time. Adding a status call after a
    # normal assistant response cannot grant clearance and can loop forever.
    assert middleware.after_model({"messages": messages}, MagicMock()) is None
