"""LangChain tool wrapper for local PDF ingestion.

Lives in tools/ so it plugs into tool_registry alongside think_tool /
search_domain_memory. Reads PDFs strictly within the workspace sandbox and
returns a JSON envelope so callers can distinguish success from error
without parsing prose.

Design mirrors ``tools/domain_memory.py``: pure additive, no imports from
memory/rebuttal/agent internals.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.tools import tool
from pypdf import PdfReader
from pypdf.errors import EmptyFileError, PdfReadError

from imaging_scientist import paths as _paths

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 100_000
MAX_INPUT_BYTES = 25 * 1024 * 1024
MAX_PAGES_DEFAULT = 200
TRUNCATION_MARKER = "\n[...truncated at {n} chars]"


class WorkspacePathError(ValueError):
    """Raised when an input path escapes or misses the workspace sandbox."""


def _resolve_workspace_path(raw: str) -> Path:
    """Resolve ``raw`` under the active workspace root; reject any escape.

    Mirrors the 3-branch algorithm from ``rebuttal/reviewer.py:57-88`` so
    virtual-absolute POSIX paths (for instance ``/papers/foo.pdf``) work on
    Windows without leaking outside the workspace.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise WorkspacePathError("path must be a non-empty string")
    root = _paths._active_workspace.resolve()
    candidate_str = raw.strip()
    path = Path(candidate_str)
    is_virtual_absolute = candidate_str.startswith(("/", "\\")) and not path.drive
    if is_virtual_absolute:
        candidate = (root / candidate_str.lstrip("/\\")).resolve()
    elif path.is_absolute():
        candidate = path.resolve()
    else:
        candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise WorkspacePathError(f"path escapes workspace: {raw}")
    return candidate


def _parse_page_range(spec: str | None, total: int) -> tuple[int, int]:
    """Return a 0-based half-open ``(start, end)`` slice for ``pages[start:end]``.

    Accepts ``"1-5"`` (1-based inclusive), ``"3"`` (single page), or ``"7-"``
    (from page N to end). ``None`` means all pages up to ``MAX_PAGES_DEFAULT``.
    """
    if total <= 0:
        return (0, 0)
    if spec is None or not spec.strip():
        return (0, min(total, MAX_PAGES_DEFAULT))
    raw = spec.strip()
    if "-" in raw:
        left, _, right = raw.partition("-")
        try:
            start = int(left) if left else 1
            end = int(right) if right else total
        except ValueError as exc:
            raise WorkspacePathError(f"invalid page_range: {spec!r}") from exc
    else:
        try:
            start = end = int(raw)
        except ValueError as exc:
            raise WorkspacePathError(f"invalid page_range: {spec!r}") from exc
    if start < 1 or end < start:
        raise WorkspacePathError(f"invalid page_range: {spec!r}")
    start_idx = start - 1
    end_idx = min(end, total)
    return (start_idx, end_idx)


def _extract_pages(reader: PdfReader, start: int, end: int) -> tuple[int, str]:
    """Iterate pages[start:end] and join with per-page markers."""
    chunks: list[str] = []
    pages_read = 0
    for page_idx in range(start, end):
        page = reader.pages[page_idx]
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — one bad page must not kill the doc
            text = ""
        chunks.append(f"--- page {page_idx + 1} ---\n{text}")
        pages_read += 1
    return pages_read, "\n\n".join(chunks)


def _truncate(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + TRUNCATION_MARKER.format(n=cap)


def _error_envelope(message: str, total_pages: int = 0) -> str:
    return json.dumps(
        {
            "pages_read": 0,
            "total_pages": total_pages,
            "text": "",
            "error": message,
        },
        ensure_ascii=False,
    )


@tool(parse_docstring=True)
def read_pdf(
    path: str,
    page_range: str | None = None,
    max_chars: int = MAX_OUTPUT_CHARS,
) -> str:
    """Extract text from a PDF under the workspace.

    Use this to consume papers dropped in ``workspace/papers/`` (for instance
    arXiv preprints) so downstream reasoning can cite specifics. Returns a
    JSON envelope so the caller can distinguish success from error without
    parsing prose.

    Args:
        path: Workspace-relative or virtual-absolute path (for instance
            "papers/dcrnn.pdf" or "/papers/dcrnn.pdf"). Rejected if it
            escapes the workspace root.
        page_range: Optional inclusive range string (for instance "1-5",
            "3", or "7-"). None means all pages up to 200.
        max_chars: Cap on extracted text characters (default 100000, hard
            max 100000). Truncation is marked in the output.

    Returns:
        JSON string with keys pages_read, total_pages, text, and an
        optional error field on failure.
    """
    try:
        candidate = _resolve_workspace_path(path)
    except WorkspacePathError as exc:
        return _error_envelope(str(exc))

    try:
        if not candidate.is_file():
            return _error_envelope(f"file not found: {path}")
        size = candidate.stat().st_size
        if size > MAX_INPUT_BYTES:
            return _error_envelope(
                f"pdf exceeds size limit ({size} > {MAX_INPUT_BYTES})"
            )

        try:
            reader = PdfReader(str(candidate), strict=False)
        except (PdfReadError, EmptyFileError) as exc:
            return _error_envelope(f"invalid or corrupt pdf: {exc}")

        if getattr(reader, "is_encrypted", False):
            return _error_envelope("pdf is encrypted; decryption not supported")

        total_pages = len(reader.pages)
        try:
            start, end = _parse_page_range(page_range, total_pages)
        except WorkspacePathError as exc:
            return _error_envelope(str(exc), total_pages=total_pages)

        pages_read, joined = _extract_pages(reader, start, end)
        cap = max(1, min(int(max_chars), MAX_OUTPUT_CHARS))
        text = _truncate(joined, cap)

        return json.dumps(
            {
                "pages_read": pages_read,
                "total_pages": total_pages,
                "text": text,
            },
            ensure_ascii=False,
        )
    except Exception as exc:  # noqa: BLE001 — tool must never crash the caller
        logger.exception("read_pdf failed for path=%s: %s", path, exc)
        return _error_envelope(f"unexpected read failure: {type(exc).__name__}: {exc}")
