"""Minimal clearance state derived from rebuttal-agent tool records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..memory.types import EMAHints
from .types import (
    HumanNextStep,
    HumanRebuttalDecision,
    REBUTTAL_RECORD_TAG,
    ReviewAction,
    RebuttalDecision,
    RebuttalRecord,
)

REBUTTAL_REVIEW_TOOL = "request_rebuttal_review"
REBUTTAL_HUMAN_DECISION_TOOL = "confirm_rebuttal_next_step"
REBUTTAL_RECORD_TOOLS = {
    REBUTTAL_REVIEW_TOOL,
    REBUTTAL_HUMAN_DECISION_TOOL,
}


@dataclass
class RebuttalAgentState:
    """Latest agent decisions for the current user turn."""

    decisions: dict[ReviewAction, RebuttalDecision] = field(default_factory=dict)
    human_decisions: dict[ReviewAction, HumanRebuttalDecision] = field(
        default_factory=dict
    )
    errors: dict[ReviewAction, str] = field(default_factory=dict)

    def apply(self, record: RebuttalRecord) -> None:
        action = record.requested_action
        if action is None:
            return
        if record.kind == "review" and record.decision is not None:
            if action == ReviewAction.EXECUTE:
                # A new iteration makes every previous final review stale.
                self.decisions.pop(ReviewAction.FINALIZE, None)
                self.human_decisions.pop(ReviewAction.FINALIZE, None)
                self.errors.pop(ReviewAction.FINALIZE, None)
            else:
                # Once result review starts, the completed run's execution
                # permission cannot authorize another iteration.
                self.human_decisions.pop(ReviewAction.EXECUTE, None)
            self.decisions[action] = record.decision
            self.human_decisions.pop(action, None)
            self.errors.pop(action, None)
        elif record.kind == "review_error" and record.error:
            self.errors[action] = record.error
            self.human_decisions.pop(action, None)
        elif record.kind == "human_decision" and record.human_decision is not None:
            self.human_decisions[action] = record.human_decision

    @property
    def stopped(self) -> bool:
        return any(
            decision.next_step == HumanNextStep.STOP
            for decision in self.human_decisions.values()
        )

    @property
    def can_execute(self) -> bool:
        decision = self.decisions.get(ReviewAction.EXECUTE)
        human = self.human_decisions.get(ReviewAction.EXECUTE)
        return (
            not self.stopped
            and decision is not None
            and human is not None
            and human.next_step == HumanNextStep.PROCEED
            and not self.can_finalize
        )

    @property
    def can_finalize(self) -> bool:
        decision = self.decisions.get(ReviewAction.FINALIZE)
        human = self.human_decisions.get(ReviewAction.FINALIZE)
        return (
            not self.stopped
            and decision is not None
            and human is not None
            and human.next_step == HumanNextStep.PROCEED
        )

    def status_text(self) -> str:
        if self.stopped:
            return "stopped by human decision"
        if self.can_finalize:
            return "finalization approved by human after rebuttal review"
        finalize = self.decisions.get(ReviewAction.FINALIZE)
        finalize_human = self.human_decisions.get(ReviewAction.FINALIZE)
        if finalize is not None and finalize_human is None:
            return (
                "awaiting human decision on final review: "
                f"{finalize.verdict.value}; {finalize.summary}"
            )
        if (
            finalize_human is not None
            and finalize_human.next_step == HumanNextStep.REVISE
        ):
            return f"human requested result revision: {finalize_human.instructions}"
        execute = self.decisions.get(ReviewAction.EXECUTE)
        execute_human = self.human_decisions.get(ReviewAction.EXECUTE)
        if execute is not None and execute_human is None:
            return (
                "awaiting human decision on execute review: "
                f"{execute.verdict.value}; {execute.summary}"
            )
        if execute_human is not None and execute_human.next_step == HumanNextStep.REVISE:
            return f"human requested plan revision: {execute_human.instructions}"
        if execute is None:
            suffix = ""
            if ReviewAction.EXECUTE in self.errors:
                suffix = f"; last error: {self.errors[ReviewAction.EXECUTE]}"
            return "execution clearance required" + suffix
        suffix = ""
        if ReviewAction.FINALIZE in self.errors:
            suffix = f"; last error: {self.errors[ReviewAction.FINALIZE]}"
        return "execution cleared; finalization clearance required" + suffix

    def latest_ema_hints(self) -> EMAHints | None:
        for action in (ReviewAction.FINALIZE, ReviewAction.EXECUTE):
            decision = self.decisions.get(action)
            if decision is not None:
                hints = decision.resolved_ema_hints()
                if hints is not None:
                    return hints
        return None


def parse_rebuttal_record(content: Any) -> RebuttalRecord | None:
    """Parse only records carrying the current agent protocol tag."""
    if not isinstance(content, str):
        return None
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("tag") != REBUTTAL_RECORD_TAG:
        return None
    try:
        return RebuttalRecord.model_validate(data)
    except Exception:
        return None


def _current_turn(messages: list[Any]) -> list[Any]:
    human_indices = [
        index
        for index, message in enumerate(messages)
        if getattr(message, "type", None) == "human"
    ]
    return messages[human_indices[-1] :] if human_indices else messages


def rebuild_rebuttal_state(messages: Iterable[Any]) -> RebuttalAgentState:
    """Rebuild current-turn clearance from authentic agent tool results."""
    state = RebuttalAgentState()
    for message in _current_turn(list(messages)):
        if getattr(message, "name", None) not in REBUTTAL_RECORD_TOOLS:
            continue
        record = parse_rebuttal_record(getattr(message, "content", None))
        if record is not None:
            state.apply(record)
    return state


def make_record(
    *,
    kind: str,
    requested_action: ReviewAction | None = None,
    decision: RebuttalDecision | None = None,
    human_decision: HumanRebuttalDecision | None = None,
    error: str = "",
    message: str,
) -> str:
    return RebuttalRecord(
        kind=kind,
        requested_action=requested_action,
        decision=decision,
        human_decision=human_decision,
        error=error,
        message=message,
    ).model_dump_json()


def latest_ema_hints_from_messages(messages: Iterable[Any]) -> EMAHints | None:
    return rebuild_rebuttal_state(messages).latest_ema_hints()
