"""Validate and import literature candidates without synthetic experiment signals."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .observations.store import (
    record_domain_observation_file,
    search_domain_observations,
)
from .project import resolve_project_id
from .types import DistillationRole, DomainFrontmatterModel, DomainKind, MemoryType

MAX_BYTES = 5 * 1024 * 1024
MAX_CANDIDATES = 200


def workspace_path(workspace: Path, raw: str) -> Path:
    """Resolve real or virtual workspace paths, including Windows drives."""
    root = workspace.resolve()
    path = Path(raw)
    if raw.startswith(("/", "\\")) and not path.drive:
        path = root / raw.lstrip("/\\")
    elif not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path escapes workspace: {raw}")
    return path


class LiteratureCandidate(BaseModel):
    """Required provenance; optional/existing fields are retained in the body."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=120)
    domain: DomainKind
    role: DistillationRole
    task_type: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=2000)
    conclusion: str = Field(min_length=1)
    applicable_conditions: str = Field(min_length=1)
    inapplicable_conditions: str = Field(min_length=1)
    source_paths: list[str] = Field(min_length=1)
    evidence_location: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    evidence_type: str = Field(min_length=1)
    why_reusable: str = Field(min_length=1)

    @field_validator("source_paths")
    @classmethod
    def nonempty_sources(cls, value: list[str]) -> list[str]:
        if any(not path.strip() for path in value):
            raise ValueError("source_paths must contain non-empty paths")
        return value


def _disposition(candidate: LiteratureCandidate) -> tuple[str, DistillationRole, str]:
    """Conservative routing: proposals and secondary direction claims stay pending."""
    evidence = candidate.evidence_type
    if evidence in {
        "survey_identified_gap",
        "hypothesis",
        "inference",
        "author_suggestion",
    }:
        return (
            "deferred",
            candidate.role,
            "Open question or proposal; not established experience.",
        )
    if evidence == "methodological_warning":
        return (
            "ready",
            DistillationRole.STRATEGY,
            "Methodological caution is a reusable strategy.",
        )
    if evidence not in {
        "survey_reported",
        "benchmark_result",
        "method_protocol",
        "case_analysis",
        "survey_framework",
        "methodological_warning",
    }:
        return (
            "deferred",
            candidate.role,
            "Unsupported evidence type; review before import.",
        )
    if candidate.role != DistillationRole.STRATEGY and evidence not in {
        "benchmark_result",
        "case_analysis",
    }:
        return (
            "deferred",
            candidate.role,
            "Direction needs direct evidence; secondary claim retained as candidate.",
        )
    return (
        "ready",
        candidate.role,
        "Literature prior only; source claims not independently verified.",
    )


def import_literature_candidates(
    *,
    workspace: Path,
    memory_dir: Path,
    path: str,
    dry_run: bool = True,
    expected_domain: DomainKind = DomainKind.ITS,
) -> dict[str, Any]:
    """Preflight all rows, then idempotently persist eligible literature priors.

    Structural validation is not source verification. Original candidate JSON,
    source hashes and applicability are kept verbatim for subsequent review.
    The importer never edits the source JSONL or invents experiment metadata.
    """
    workspace = workspace.resolve()
    source = workspace_path(workspace, path)
    if source.stat().st_size > MAX_BYTES:
        raise ValueError("candidate file exceeds 5 MiB")
    source_bytes = source.read_bytes()
    batch_hash = hashlib.sha256(source_bytes).hexdigest()[:16]
    lines = [
        line for line in source_bytes.decode("utf-8-sig").splitlines() if line.strip()
    ]
    if not lines or len(lines) > MAX_CANDIDATES:
        raise ValueError("candidate file must contain 1–200 non-empty JSONL rows")
    project_id = resolve_project_id(workspace)
    rows: list[dict[str, Any]] = []
    prepared: list[tuple[LiteratureCandidate, dict[str, Any], str, str]] = []
    seen: set[str] = set()
    hash_cache: dict[Path, str] = {}
    candidates: list[LiteratureCandidate] = []
    for number, line in enumerate(lines, 1):
        row: dict[str, Any] = {"line": number, "status": "invalid"}
        rows.append(row)
        try:
            candidate = LiteratureCandidate.model_validate_json(line)
            candidates.append(candidate)
            row.update(
                id=candidate.id,
                original_role=candidate.role.value,
                task_type=candidate.task_type,
            )
            if candidate.id in seen:
                raise ValueError(f"duplicate candidate id: {candidate.id}")
            seen.add(candidate.id)
            if candidate.domain != expected_domain:
                raise ValueError("candidate domain does not match configured domain")
            sources = []
            for raw in candidate.source_paths:
                pdf = workspace_path(workspace, raw)
                if pdf.suffix.lower() != ".pdf" or not pdf.is_file():
                    raise ValueError(f"source PDF is missing: {raw}")
                if pdf not in hash_cache:
                    with pdf.open("rb") as stream:
                        hash_cache[pdf] = hashlib.file_digest(
                            stream, "sha256"
                        ).hexdigest()
                sources.append(
                    {
                        "path": pdf.relative_to(workspace.resolve()).as_posix(),
                        "sha256": hash_cache[pdf],
                    }
                )
            status, role, reason = _disposition(candidate)
            row.update(status=status, role=role.value, reason=reason)
            if status != "ready":
                continue
            evidence = json.dumps(
                {
                    "sources": sources,
                    "location": candidate.evidence_location,
                    "text": candidate.evidence_text,
                    "type": candidate.evidence_type,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            body = (
                "Literature prior — not a locally reproduced experiment.\n"
                "Evidence status: source_unverified. Check the cited PDF before use.\n"
                "Utility status: unscored (0 is a storage/ranking floor, not a measured result).\n"
                "Leakage risk: unknown; no experimental provenance is available.\n"
                "Direction claims apply only to the cited conditions, not to an entire method family.\n\n"
                f"Import classification: {role.value}. {reason}\n\n"
                "## Original candidate\n"
                + json.dumps(
                    candidate.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            prepared.append((candidate, row, body, evidence))
        except (ValueError, OSError) as exc:
            row.update(status="invalid", reason=str(exc))

    # Validate the complete batch before creating any memory files.
    validation_failed = any(row["status"] == "invalid" for row in rows)
    if not dry_run and not validation_failed:
        for candidate, row, body, evidence in prepared:
            role = DistillationRole(row["role"])
            try:
                result = record_domain_observation_file(
                    memory_dir=memory_dir,
                    project_id=project_id,
                    domain=DomainFrontmatterModel(
                        domain=candidate.domain,
                        role=role,
                        task_type=candidate.task_type,
                        utility_score=0.0,
                        evidence_source="literature",
                        evidence_status="source_unverified",
                        evidence_id=f"literature:{project_id}:{candidate.id}",
                    ),
                    memory_type=MemoryType.PROCEDURAL
                    if role == DistillationRole.STRATEGY
                    else MemoryType.SEMANTIC,
                    summary=f"[Literature/{candidate.id}; cited conditions only; unverified] {candidate.summary}",
                    observation=body,
                    why_it_matters=candidate.why_reusable,
                    evidence=evidence,
                    source_agent="literature-import",
                    source_session_id=f"literature-import:{batch_hash}",
                )
                # Store paths use the agent's /memories/ mount.
                physical = memory_dir / result["path"].removeprefix(
                    "/memories/"
                ).lstrip("/")
                row.update(
                    result,
                    physical_path=str(physical),
                    readback_verified=False,
                    retrieval_verified=False,
                )
                stored = physical.read_text(encoding="utf-8")
                if body not in stored or evidence not in stored:
                    raise ValueError(
                        "stored candidate differs; review existing memory before replacing it"
                    )
                hits = search_domain_observations(
                    memory_dir=memory_dir,
                    domain=candidate.domain,
                    project_id=project_id,
                    query=candidate.id,
                    limit=20,
                )
                verified = any(
                    hit["observation_id"] == result["observation_id"] for hit in hits
                )
                row.update(
                    result,
                    status="created" if result["created"] else "existing",
                    physical_path=str(physical),
                    readback_verified=True,
                    retrieval_verified=verified,
                )
                if not verified:
                    row["status"] = "verification_failed"
            except (ValueError, OSError) as exc:
                row.update(status="error", reason=str(exc))
    return {
        "dry_run": dry_run,
        "validation_failed": validation_failed,
        "candidate_count": len(lines),
        "project_id": project_id,
        "counts": dict(Counter(row["status"] for row in rows)),
        "task_types": dict(Counter(c.task_type for c in candidates)),
        "original_roles": dict(Counter(c.role.value for c in candidates)),
        "evidence_notice": "Structural checks and retrieval verification do not verify paper claims.",
        "rows": rows,
    }
