"""Rebuttal-agent to Domain-EMA integration tests."""

from __future__ import annotations

import json

import yaml
from langchain_core.messages import ToolMessage

from imaging_scientist.memory.types import EMAHints
from imaging_scientist.rebuttal import (
    RebuttalAgentState,
    latest_ema_hints_from_messages,
)
from imaging_scientist.rebuttal.state import make_record
from imaging_scientist.rebuttal.types import (
    FailureType,
    RebuttalDecision,
    RebuttalRecord,
    ReviewAction,
    ReviewCheck,
    Verdict,
)


def _decision(action: ReviewAction, verdict: Verdict, **overrides):
    payload = {
        "requested_action": action,
        "verdict": verdict,
        "summary": "test",
    }
    if verdict == Verdict.PASS:
        checks = [ReviewCheck.HYPOTHESIS, ReviewCheck.EXPERIMENT_DESIGN]
        if action == ReviewAction.FINALIZE:
            checks.append(ReviewCheck.RESULTS_EVIDENCE)
            payload["pass_criteria"] = ["Registered threshold met."]
            payload["optimization_suggestions"] = ["Run another seed."]
        payload["checks_applied"] = checks
        payload["surviving_hypotheses"] = ["H1"]
    elif verdict == Verdict.REVISE:
        payload["required_revisions"] = ["fix"]
    payload.update(overrides)
    return RebuttalDecision(**payload)


class TestResolvedEMAHints:
    def test_structured_takes_precedence(self):
        decision = _decision(
            ReviewAction.EXECUTE,
            Verdict.REVISE,
            ema_hints=["irrelevant"],
            ema_hints_structured=EMAHints(
                write_ME_debug=True,
                debug_note="hi",
            ),
        )
        hints = decision.resolved_ema_hints()
        assert hints is not None
        assert hints.write_ME_debug is True
        assert hints.debug_note == "hi"

    def test_json_string_fallback(self):
        decision = _decision(
            ReviewAction.EXECUTE,
            Verdict.REVISE,
            ema_hints=[json.dumps({"write_MI_negative": True})],
        )
        hints = decision.resolved_ema_hints()
        assert hints is not None and hints.write_MI_negative is True

    def test_direction_failure_infers_negative_hint(self):
        decision = _decision(
            ReviewAction.EXECUTE,
            Verdict.KILL,
            failure_type=FailureType.DIRECTION,
        )
        hints = decision.resolved_ema_hints()
        assert hints is not None and hints.write_MI_negative is True

    def test_implementation_failure_infers_debug_hint(self):
        decision = _decision(
            ReviewAction.EXECUTE,
            Verdict.REVISE,
            failure_type=FailureType.IMPLEMENTATION,
        )
        hints = decision.resolved_ema_hints()
        assert hints is not None and hints.write_ME_debug is True

    def test_finalization_pass_infers_positive_hint(self):
        decision = _decision(ReviewAction.FINALIZE, Verdict.PASS)
        hints = decision.resolved_ema_hints()
        assert hints is not None and hints.write_MI_positive is True


class TestAgentStateLatestHints:
    def test_no_decisions_returns_none(self):
        assert RebuttalAgentState().latest_ema_hints() is None

    def test_finalization_decision_takes_precedence(self):
        state = RebuttalAgentState()
        execute = _decision(
            ReviewAction.EXECUTE,
            Verdict.REVISE,
            ema_hints_structured=EMAHints(write_ME_debug=True),
        )
        final = _decision(ReviewAction.FINALIZE, Verdict.PASS)
        state.apply(
            RebuttalRecord(
                kind="review",
                requested_action=ReviewAction.EXECUTE,
                decision=execute,
                message="done",
            )
        )
        state.apply(
            RebuttalRecord(
                kind="review",
                requested_action=ReviewAction.FINALIZE,
                decision=final,
                message="done",
            )
        )
        hints = state.latest_ema_hints()
        assert hints is not None
        assert hints.write_MI_positive is True
        assert hints.write_ME_debug is False


def test_agent_record_replays_to_ema_hints():
    decision = _decision(
        ReviewAction.EXECUTE,
        Verdict.KILL,
        failure_type=FailureType.DIRECTION,
    )
    message = ToolMessage(
        name="request_rebuttal_review",
        tool_call_id="review-1",
        content=make_record(
            kind="review",
            requested_action=ReviewAction.EXECUTE,
            decision=decision,
            message="done",
        ),
    )
    hints = latest_ema_hints_from_messages([message])
    assert hints is not None and hints.write_MI_negative is True


class TestSubagentYamlIntegrity:
    def test_domain_memory_tools_remain_configured(self):
        expected = {
            "research.yaml": "research-agent",
            "planner.yaml": "planner-agent",
            "code.yaml": "code-agent",
        }
        for filename, agent_name in expected.items():
            with open(
                f"imaging_scientist/subagents/{filename}",
                encoding="utf-8",
            ) as stream:
                data = yaml.safe_load(stream)
            assert "search_domain_memory" in data[agent_name]["tools"]


def test_source_context_reads_rebuttal_agent_hints(monkeypatch):
    from imaging_scientist.memory.source_context import _resolve_domain_context
    from imaging_scientist.memory.types import MemorySourceType

    class _Cfg:
        domain_ema_enabled = True
        domain_ema_domain = "its"
        domain_ema_write_threshold = 0.2

    monkeypatch.setattr(
        "imaging_scientist.config.get_effective_config",
        lambda: _Cfg(),
    )
    decision = _decision(
        ReviewAction.EXECUTE,
        Verdict.KILL,
        failure_type=FailureType.DIRECTION,
    )
    message = ToolMessage(
        name="request_rebuttal_review",
        tool_call_id="review-1",
        content=make_record(
            kind="review",
            requested_action=ReviewAction.EXECUTE,
            decision=decision,
            message="done",
        ),
    )
    domain, hints = _resolve_domain_context(
        state={"messages": [message]},
        source_type=MemorySourceType.SUBAGENT,
    )
    assert domain == "its"
    assert hints is not None and hints.write_MI_negative is True
