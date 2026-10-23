"""Unit tests for the ``read_pdf`` tool (sandbox + extraction + error paths)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from imaging_scientist import paths as _paths
from imaging_scientist.tools.read_pdf import (
    MAX_OUTPUT_CHARS,
    TRUNCATION_MARKER,
    read_pdf,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_pdf(
    dest: Path, page_texts: list[str], *, encrypt_password: str | None = None
) -> Path:
    """Build a synthetic PDF at ``dest`` with one page per string.

    Uses pypdf.PdfWriter.add_blank_page + a manual /Contents stream because
    pypdf does not ship a high-level text-drawing API. The extracted-text
    output will not match ``page_texts`` byte-for-byte but each page's tag
    (e.g. "PAGE-1", "PAGE-2") will round-trip via extract_text().
    """
    writer = PdfWriter()
    for tag in page_texts:
        page = writer.add_blank_page(width=200, height=200)
        # Inject a minimal /Contents stream that draws the tag as text.
        from pypdf.generic import (
            ArrayObject,
            DecodedStreamObject,
            NameObject,
            NumberObject,
        )

        stream = DecodedStreamObject()
        # PDF operators: BT begin-text, /F1 font, Tf size, Td position, Tj text, ET end
        payload = f"BT /F1 12 Tf 10 100 Td ({tag}) Tj ET".encode("latin-1")
        stream.set_data(payload)
        page[NameObject("/Contents")] = stream
        # Provide a Helvetica font resource under /Resources so extractors accept it.
        from pypdf.generic import DictionaryObject

        font_dict = DictionaryObject()
        font_dict[NameObject("/F1")] = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        resources = DictionaryObject()
        resources[NameObject("/Font")] = font_dict
        page[NameObject("/Resources")] = resources
        page[NameObject("/MediaBox")] = ArrayObject(
            [NumberObject(0), NumberObject(0), NumberObject(200), NumberObject(200)]
        )
    if encrypt_password:
        writer.encrypt(user_password=encrypt_password)
    with dest.open("wb") as fh:
        writer.write(fh)
    return dest


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Point _active_workspace at a fresh tmp dir for each test."""
    monkeypatch.setattr(_paths, "_active_workspace", tmp_path)
    (tmp_path / "papers").mkdir()
    return tmp_path


def _invoke(**kwargs):
    """Call the LangChain tool wrapper and parse its JSON envelope."""
    raw = read_pdf.invoke(kwargs)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExtraction:
    def test_read_pdf_extracts_text(self, workspace):
        _make_pdf(workspace / "papers/sample.pdf", ["PAGE-A", "PAGE-B", "PAGE-C"])
        result = _invoke(path="papers/sample.pdf")
        assert result.get("error") is None, result
        assert result["pages_read"] == 3
        assert result["total_pages"] == 3
        assert "PAGE-A" in result["text"]
        assert "PAGE-B" in result["text"]
        assert "PAGE-C" in result["text"]
        # Each page must carry its own marker for downstream section-aware reasoning.
        assert "--- page 1 ---" in result["text"]
        assert "--- page 3 ---" in result["text"]

    def test_read_pdf_page_range_single(self, workspace):
        _make_pdf(
            workspace / "papers/multi.pdf", ["PAGE-1", "PAGE-2", "PAGE-3", "PAGE-4"]
        )
        result = _invoke(path="papers/multi.pdf", page_range="2-2")
        assert result["pages_read"] == 1
        assert "PAGE-2" in result["text"]
        assert "PAGE-1" not in result["text"]
        assert "PAGE-3" not in result["text"]

    def test_read_pdf_page_range_open_ended(self, workspace):
        _make_pdf(
            workspace / "papers/multi.pdf", ["PAGE-1", "PAGE-2", "PAGE-3", "PAGE-4"]
        )
        result = _invoke(path="papers/multi.pdf", page_range="3-")
        assert result["pages_read"] == 2
        assert "PAGE-3" in result["text"]
        assert "PAGE-4" in result["text"]

    def test_virtual_absolute_path(self, workspace):
        _make_pdf(workspace / "papers/virt.pdf", ["VIRT-A"])
        result = _invoke(path="/papers/virt.pdf")
        assert result.get("error") is None
        assert "VIRT-A" in result["text"]


class TestSandbox:
    def test_rejects_workspace_escape(self, workspace):
        result = _invoke(path="../secret.pdf")
        assert result.get("error"), result
        assert "escapes workspace" in result["error"]

    def test_rejects_empty_path(self, workspace):
        result = _invoke(path="   ")
        assert result.get("error"), result
        assert "non-empty" in result["error"]

    def test_missing_file(self, workspace):
        result = _invoke(path="papers/does-not-exist.pdf")
        assert result.get("error"), result
        assert "not found" in result["error"]


class TestErrorPaths:
    def test_encrypted_pdf(self, workspace):
        _make_pdf(
            workspace / "papers/locked.pdf", ["SECRET"], encrypt_password="hunter2"
        )
        result = _invoke(path="papers/locked.pdf")
        assert result.get("error"), result
        assert "encrypted" in result["error"]

    def test_non_pdf_bytes(self, workspace):
        (workspace / "papers/junk.pdf").write_bytes(b"this is not a pdf")
        result = _invoke(path="papers/junk.pdf")
        assert result.get("error"), result
        # pypdf raises PdfReadError → we tag it as "invalid or corrupt pdf"
        assert (
            "invalid or corrupt pdf" in result["error"]
            or "unexpected read failure" in result["error"]
        )

    def test_invalid_page_range(self, workspace):
        _make_pdf(workspace / "papers/multi.pdf", ["PAGE-1", "PAGE-2"])
        result = _invoke(path="papers/multi.pdf", page_range="abc")
        assert result.get("error"), result
        assert "page_range" in result["error"]


class TestOutputCap:
    def test_max_chars_truncation(self, workspace):
        # Build a PDF whose extracted text is comfortably > 200 chars.
        pages = [f"CHUNK-{i:03d}" for i in range(60)]
        _make_pdf(workspace / "papers/big.pdf", pages)
        result = _invoke(path="papers/big.pdf", max_chars=200)
        # Truncated output = 200 chars body + marker suffix
        assert result.get("error") is None, result
        expected_marker = TRUNCATION_MARKER.format(n=200)
        assert result["text"].endswith(expected_marker)
        assert len(result["text"]) == 200 + len(expected_marker)

    def test_hard_cap_overrides_caller(self, workspace):
        # Caller asks for 10x the hard max — the tool must clamp.
        pages = [f"CHUNK-{i:03d}" for i in range(60)]
        _make_pdf(workspace / "papers/big.pdf", pages)
        result = _invoke(path="papers/big.pdf", max_chars=MAX_OUTPUT_CHARS * 10)
        # Whatever comes out must fit inside the hard cap plus one marker.
        assert len(result["text"]) <= MAX_OUTPUT_CHARS + len(
            TRUNCATION_MARKER.format(n=MAX_OUTPUT_CHARS)
        )
