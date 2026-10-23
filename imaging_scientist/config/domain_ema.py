"""Domain-EMA control surface — projection of ``ImagingScientistConfig`` fields.

Mirrors the ``MemoryControls`` pattern in ``config.settings``: the persistent
config holds a small set of flat fields (``domain_ema_enabled``, ...) and this
module builds a typed projection on demand. Consumers (memory worker
middleware, ``/domain-status`` command, distiller) depend on this projection
so we can evolve the config schema without breaking their signatures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..memory.types import DomainKind

if TYPE_CHECKING:
    from .settings import ImagingScientistConfig


# Sensible defaults for DCS reference targets (see docs/DCS-*).
DEFAULT_TASK_TYPES: tuple[str, ...] = ("predict", "control", "joint")
DEFAULT_MIN_POSITIVE: int = 5
DEFAULT_MIN_NEGATIVE: int = 3
DEFAULT_MIN_STRATEGY: int = 10
DEFAULT_STALE_DAYS: int = 90
DEFAULT_WRITE_THRESHOLD: float = 0.2


@dataclass(frozen=True)
class DCSTargetsConfig:
    """Per-domain reference denominators for the DCS composite score."""

    task_types: tuple[str, ...] = DEFAULT_TASK_TYPES
    fingerprint_buckets: tuple[str, ...] = ()
    min_positive: int = DEFAULT_MIN_POSITIVE
    min_negative: int = DEFAULT_MIN_NEGATIVE
    min_strategy: int = DEFAULT_MIN_STRATEGY
    stale_days_threshold: int = DEFAULT_STALE_DAYS
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "cov": 0.25,
            "bal": 0.20,
            "qual": 0.20,
            "util": 0.20,
            "fresh": 0.15,
        }
    )


@dataclass(frozen=True)
class DomainEMAControls:
    """Runtime flags gating Domain-EMA writes and retrieval bias.

    ``enabled=False`` is the safe default — legacy projects continue to write
    only generic observations and never see Domain-EMA middleware fire.
    """

    enabled: bool = False
    domain: DomainKind = DomainKind.GENERIC
    write_threshold_strategy: float = DEFAULT_WRITE_THRESHOLD
    dcs_targets: DCSTargetsConfig = field(default_factory=DCSTargetsConfig)

    @classmethod
    def from_config(cls, config: "ImagingScientistConfig") -> "DomainEMAControls":
        """Project the persisted flat config into a typed control object."""
        raw_domain = getattr(config, "domain_ema_domain", "") or "generic"
        try:
            domain = DomainKind(raw_domain)
        except ValueError:
            domain = DomainKind.GENERIC

        threshold = getattr(
            config, "domain_ema_write_threshold", DEFAULT_WRITE_THRESHOLD
        )
        if not isinstance(threshold, (int, float)) or threshold < 0 or threshold > 1:
            threshold = DEFAULT_WRITE_THRESHOLD

        return cls(
            enabled=bool(getattr(config, "domain_ema_enabled", False)),
            domain=domain,
            write_threshold_strategy=float(threshold),
        )
