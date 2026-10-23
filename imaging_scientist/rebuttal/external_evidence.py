"""Validation for traceable evidence collected through web or MCP tools."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExternalEvidenceScope(BaseModel):
    """Applicability axes used to assess whether an external source transfers."""

    model_config = ConfigDict(extra="forbid")

    city: str | None = None
    dataset: str | None = None
    event_types: list[str] = Field(default_factory=list)
    prediction_horizons: list[int] = Field(default_factory=list)
    model_family: str | None = None


class ExternalEvidenceItem(BaseModel):
    """One attributable external finding, distinct from current-run evidence."""

    model_config = ConfigDict(extra="forbid")

    source_type: Literal["literature", "weather", "holiday", "incident"]
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    retrieved_at: datetime
    query: str = Field(min_length=1)
    scope: ExternalEvidenceScope
    finding: str = Field(min_length=1)
    limitations: str = Field(min_length=1)

    @field_validator("title", "url", "query", "finding", "limitations")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an absolute http(s) URL")
        return value


class ExternalEvidenceManifest(BaseModel):
    """Versioned collection passed to the rebuttal agent as read-only evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    evidence: list[ExternalEvidenceItem] = Field(min_length=1)


def validate_external_evidence_file(path: Path) -> ExternalEvidenceManifest:
    """Parse and validate a formal external-evidence manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid external evidence JSON: {path.name}") from exc
    return ExternalEvidenceManifest.model_validate(payload)
