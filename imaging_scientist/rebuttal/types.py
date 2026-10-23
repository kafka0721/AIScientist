"""Structured protocol returned by the independent rebuttal agent."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..memory.types import EMAHints


class ReviewAction(StrEnum):
    """Action for which the main agent requests scientific clearance."""

    EXECUTE = "execute"
    FINALIZE = "finalize"


class ReviewCheck(StrEnum):
    """Scientific checks selected internally by the rebuttal agent."""

    HYPOTHESIS = "hypothesis"
    EXPERIMENT_DESIGN = "experiment_design"
    RESULTS_EVIDENCE = "results_evidence"


class HumanNextStep(StrEnum):
    """Human-selected action after reading the rebuttal-agent opinion."""

    PROCEED = "proceed"
    REVISE = "revise"
    STOP = "stop"


class Verdict(StrEnum):
    PASS = "pass"
    REVISE = "revise"
    KILL = "kill"


class Severity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class FailureType(StrEnum):
    DIRECTION = "direction"
    IMPLEMENTATION = "implementation"
    EVALUATION = "evaluation"
    NONE = "none"


class RebuttalAttack(BaseModel):
    """One evidence-grounded attack raised by the rebuttal agent."""

    claim: str = Field(min_length=1)
    flaw: str = Field(min_length=1)
    minimal_falsifier: str = Field(min_length=1)
    severity: Severity


class RebuttalDecision(BaseModel):
    """Unified clearance decision returned by the rebuttal agent."""

    requested_action: ReviewAction
    verdict: Verdict
    checks_applied: list[ReviewCheck] = Field(default_factory=list)
    attacks: list[RebuttalAttack] = Field(default_factory=list)
    failure_type: FailureType = FailureType.NONE
    required_revisions: list[str] = Field(default_factory=list)
    ema_hints: list[str] = Field(default_factory=list)
    ema_hints_structured: EMAHints | None = None
    surviving_hypotheses: list[str] = Field(default_factory=list)
    pass_criteria: list[str] = Field(default_factory=list)
    optimization_suggestions: list[str] = Field(default_factory=list)
    iteration_plan: list[str] = Field(default_factory=list)
    memory_references_considered: list[str] = Field(default_factory=list)
    memory_conflicts: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_clearance_contract(self) -> "RebuttalDecision":
        """Reject decisions that did not perform the required internal checks."""
        required_checks = {
            ReviewCheck.HYPOTHESIS,
            ReviewCheck.EXPERIMENT_DESIGN,
        }
        if self.requested_action == ReviewAction.FINALIZE:
            required_checks.add(ReviewCheck.RESULTS_EVIDENCE)

        if self.verdict == Verdict.PASS:
            if self.required_revisions:
                raise ValueError("pass verdict cannot require revisions")
            if any(attack.severity == Severity.CRITICAL for attack in self.attacks):
                raise ValueError("pass verdict cannot contain critical attacks")
            missing = required_checks - set(self.checks_applied)
            if missing:
                names = ", ".join(sorted(check.value for check in missing))
                raise ValueError(f"pass verdict omitted required checks: {names}")
            if not self.surviving_hypotheses:
                raise ValueError("pass verdict requires a falsifiable hypothesis")
            if self.requested_action == ReviewAction.FINALIZE:
                if not self.pass_criteria:
                    raise ValueError("finalization pass requires pass criteria")
                if not self.optimization_suggestions:
                    raise ValueError(
                        "finalization pass requires optimization suggestions"
                    )
        elif self.verdict == Verdict.REVISE and not self.required_revisions:
            raise ValueError("revise verdict requires at least one revision")
        if (
            self.requested_action == ReviewAction.FINALIZE
            and self.verdict != Verdict.PASS
            and not self.iteration_plan
        ):
            raise ValueError(
                "failed finalization review requires an iteration plan"
            )
        return self

    def resolved_ema_hints(self) -> EMAHints | None:
        """Return the best available Domain-EMA routing signal."""
        if self.ema_hints_structured is not None:
            return self.ema_hints_structured
        for raw in self.ema_hints:
            if not isinstance(raw, str):
                continue
            candidate = raw.strip()
            if not (candidate.startswith("{") and candidate.endswith("}")):
                continue
            import json

            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                try:
                    return EMAHints.model_validate(payload)
                except Exception:  # noqa: BLE001
                    continue
        if self.failure_type == FailureType.DIRECTION:
            return EMAHints(write_MI_negative=True)
        if self.failure_type == FailureType.IMPLEMENTATION:
            return EMAHints(write_ME_debug=True)
        if (
            self.verdict == Verdict.PASS
            and self.requested_action == ReviewAction.FINALIZE
        ):
            return EMAHints(write_MI_positive=True)
        return None


class HumanRebuttalDecision(BaseModel):
    """Human decision made after reviewing the agent's opinion."""

    requested_action: ReviewAction
    next_step: HumanNextStep
    review_summary: str = Field(min_length=1)
    instructions: str = ""

    @model_validator(mode="after")
    def validate_instructions(self) -> "HumanRebuttalDecision":
        if self.next_step == HumanNextStep.REVISE and not self.instructions.strip():
            raise ValueError("revise decision requires modification instructions")
        return self


class RebuttalRecord(BaseModel):
    """Authenticated wire envelope returned by the agent-owned review tool."""

    tag: Literal["witaiscientist.rebuttal_agent.v3"] = (
        "witaiscientist.rebuttal_agent.v3"
    )
    kind: Literal["review", "review_error", "human_decision", "status"]
    requested_action: ReviewAction | None = None
    decision: RebuttalDecision | None = None
    human_decision: HumanRebuttalDecision | None = None
    error: str = ""
    message: str

    @model_validator(mode="after")
    def validate_record(self) -> "RebuttalRecord":
        if self.kind == "review":
            if self.decision is None:
                raise ValueError("review record requires an agent decision")
            if self.requested_action != self.decision.requested_action:
                raise ValueError("record action does not match decision action")
        elif self.kind == "review_error":
            if self.requested_action is None or not self.error:
                raise ValueError("review_error requires an action and error")
        elif self.kind == "human_decision":
            if self.human_decision is None:
                raise ValueError("human_decision record requires a decision")
            if self.requested_action != self.human_decision.requested_action:
                raise ValueError("record action does not match human decision")
        elif any((self.decision, self.human_decision, self.error)):
            raise ValueError("status record cannot contain decisions or errors")
        return self


REBUTTAL_RECORD_TAG = "witaiscientist.rebuttal_agent.v3"
