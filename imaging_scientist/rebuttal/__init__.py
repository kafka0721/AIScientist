"""Independent rebuttal reviewer and hard-gate protocol."""

from ..memory.types import EMAHints
from .agent import RebuttalAgent, build_rebuttal_agent
from .external_evidence import (
    ExternalEvidenceItem,
    ExternalEvidenceManifest,
    ExternalEvidenceScope,
)
from .references import (
    DomainEMAReferenceProvider,
    RebuttalReference,
    format_domain_ema_references,
)
from .reviewer import EvidenceError, RebuttalReviewer, resolve_evidence_paths
from .state import (
    RebuttalAgentState,
    latest_ema_hints_from_messages,
    rebuild_rebuttal_state,
)
from .types import (
    FailureType,
    HumanNextStep,
    HumanRebuttalDecision,
    RebuttalAttack,
    RebuttalDecision,
    RebuttalRecord,
    ReviewAction,
    ReviewCheck,
    Severity,
    Verdict,
)

__all__ = [
    "DomainEMAReferenceProvider",
    "EMAHints",
    "EvidenceError",
    "ExternalEvidenceItem",
    "ExternalEvidenceManifest",
    "ExternalEvidenceScope",
    "FailureType",
    "HumanNextStep",
    "HumanRebuttalDecision",
    "RebuttalAgent",
    "RebuttalAgentState",
    "RebuttalAttack",
    "RebuttalDecision",
    "RebuttalRecord",
    "RebuttalReference",
    "RebuttalReviewer",
    "ReviewAction",
    "ReviewCheck",
    "Severity",
    "Verdict",
    "build_rebuttal_agent",
    "format_domain_ema_references",
    "latest_ema_hints_from_messages",
    "rebuild_rebuttal_state",
    "resolve_evidence_paths",
]
