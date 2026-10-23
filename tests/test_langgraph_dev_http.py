"""Smoke test for the /api/models route mounted via langgraph.json's
``http`` field. We test the FastAPI app directly — no need to spin up
langgraph dev.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from starlette.testclient import TestClient

from imaging_scientist.config import ImagingScientistConfig
from imaging_scientist.langgraph_dev.http import app

client = TestClient(app)


def test_get_models_returns_entries_and_default():
    mock_cfg = ImagingScientistConfig(
        model="claude-sonnet-4-6", provider="custom-anthropic"
    )
    with patch(
        "imaging_scientist.langgraph_dev.http.load_config", return_value=mock_cfg
    ):
        resp = client.get("/api/models")
    assert resp.status_code == 200
    body = resp.json()
    assert "entries" in body
    assert "default" in body
    assert body["default"] == {
        "name": "claude-sonnet-4-6",
        "provider": "custom-anthropic", "interface": "Anthropic-compatible Messages API",
    }
    assert isinstance(body["entries"], list)
    assert len(body["entries"]) > 0
    # Every entry has the three required keys
    for entry in body["entries"]:
        assert set(entry.keys()) == {"name", "model_id", "provider", "interface"}
        assert isinstance(entry["name"], str)
        assert entry["name"]
        assert isinstance(entry["model_id"], str)
        assert entry["model_id"]
        assert isinstance(entry["provider"], str)
        assert entry["provider"]


def test_entries_preserve_registry_order():
    """The picker uses position-in-list to rank providers per short name —
    the JSON must preserve the order returned by ``list_models_by_provider``.

    Stubs ``load_config`` to keep the assertion focused on
    registry order rather than implicitly depending on the ambient
    deploy config.
    """
    from imaging_scientist.llm.models import list_models_by_provider, provider_interface

    expected = [
        {"name": n, "model_id": m, "provider": p, "interface": provider_interface(p)}
        for n, m, p in list_models_by_provider()
    ]
    mock_cfg = ImagingScientistConfig()
    with patch(
        "imaging_scientist.langgraph_dev.http.load_config", return_value=mock_cfg
    ):
        resp = client.get("/api/models")
    assert resp.json()["entries"] == expected


def test_default_passes_through_arbitrary_config_pair():
    """If config.yaml names a (name, provider) pair that isn't in the
    registry (typo, retired model), still report it as default — the
    picker labels it as the active selection regardless.
    """
    mock_cfg = ImagingScientistConfig(model="some-retired-name", provider="some-provider")
    with patch(
        "imaging_scientist.langgraph_dev.http.load_config", return_value=mock_cfg
    ):
        resp = client.get("/api/models")
    assert resp.json()["default"] == {
        "name": "some-retired-name",
        "provider": "some-provider", "interface": "Provider-specific API",
    }


def test_ollama_models_appended_when_base_url_configured():
    """Mirrors the TUI ``/model`` picker: when ``ollama_base_url`` is set,
    locally-pulled Ollama models are appended after the static registry
    as ``provider: "ollama"`` entries.
    """
    mock_cfg = ImagingScientistConfig(
        model="claude-sonnet-4-6",
        provider="custom-anthropic",
        ollama_base_url="http://localhost:11434",
    )

    async def fake_discover(_base_url, *, timeout):
        return ["llama3:8b", "mistral:7b"]

    with (
        patch(
            "imaging_scientist.langgraph_dev.http.load_config",
            return_value=mock_cfg,
        ),
        patch(
            "imaging_scientist.llm.ollama_discovery.discover_ollama_models",
            new=fake_discover,
        ),
    ):
        body = client.get("/api/models").json()

    # Assert the response is the static registry followed by the discovered
    # Ollama suffix — robust to future static Ollama entries in the registry.
    from imaging_scientist.llm.models import list_models_by_provider, provider_interface

    static_entries = [
        {"name": n, "model_id": m, "provider": p, "interface": provider_interface(p)}
        for n, m, p in list_models_by_provider()
    ]
    discovered_entries = [
        {"name": "llama3:8b", "model_id": "llama3:8b", "provider": "ollama", "interface": "Ollama native /api/chat"},
        {"name": "mistral:7b", "model_id": "mistral:7b", "provider": "ollama", "interface": "Ollama native /api/chat"},
    ]
    assert body["entries"][: len(static_entries)] == static_entries
    assert body["entries"][len(static_entries) :] == discovered_entries
    # TUI's "Custom Ollama model…" sentinel is a widget-specific affordance —
    # it must not appear on the HTTP surface.
    assert not any(e["model_id"] == "__custom_ollama__" for e in body["entries"])


def test_ollama_discovery_skipped_when_base_url_absent():
    """No Ollama discovery should happen when ``ollama_base_url`` is unset —
    matches the ``/model`` picker's gating. The probe function should never
    be called in that case.
    """
    mock_cfg = ImagingScientistConfig(
        model="claude-sonnet-4-6", provider="custom-anthropic"
    )
    calls: list[str | None] = []

    async def spy_discover(base_url, *, timeout):
        calls.append(base_url)
        return []

    with (
        patch(
            "imaging_scientist.langgraph_dev.http.load_config",
            return_value=mock_cfg,
        ),
        patch(
            "imaging_scientist.llm.ollama_discovery.discover_ollama_models",
            new=spy_discover,
        ),
    ):
        body = client.get("/api/models").json()

    assert calls == []
    # Response is exactly the static registry — no Ollama additions whatsoever.
    from imaging_scientist.llm.models import list_models_by_provider, provider_interface

    assert body["entries"] == [
        {"name": n, "model_id": m, "provider": p, "interface": provider_interface(p)}
        for n, m, p in list_models_by_provider()
    ]


def test_runtime_config_reads_saved_profile_not_stale_environment(monkeypatch):
    """A previous .env key must not make the WebUI profile appear to revert."""
    saved = ImagingScientistConfig(
        provider="openai", model="gpt-5", openai_api_key="saved-key-1234"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "stale-environment-key")

    with patch("imaging_scientist.langgraph_dev.http.load_config", return_value=saved):
        response = client.get("/api/runtime-config")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-5"
    assert body["keyConfigured"] is True
    assert body["apiKeyHint"].endswith("1234")
    assert "stale-environment-key" not in body["apiKeyHint"]


def test_runtime_config_update_preserves_saved_key_and_syncs_live_provider_env(monkeypatch):
    """A model-only change must keep the selected provider's saved key live."""
    saved = ImagingScientistConfig(
        provider="openai", model="gpt-4.1", openai_api_key="saved-key-1234"
    )
    persisted: list[ImagingScientistConfig] = []
    monkeypatch.setenv("OPENAI_API_KEY", "old-environment-key")

    with (
        patch("imaging_scientist.langgraph_dev.http.load_config", return_value=saved),
        patch(
            "imaging_scientist.langgraph_dev.http.save_config",
            side_effect=persisted.append,
        ),
        patch("imaging_scientist.imaging_scientist.refresh_runtime_config") as refresh,
    ):
        response = client.put(
            "/api/runtime-config", json={"provider": "openai", "model": "gpt-5"}
        )

    assert response.status_code == 200
    assert persisted and persisted[0].model == "gpt-5"
    assert persisted[0].openai_api_key == "saved-key-1234"
    assert os.environ["OPENAI_API_KEY"] == "saved-key-1234"
    refresh.assert_called_once_with(persisted[0])
