"""Custom HTTP routes mounted alongside the langgraph dev server.

The langgraph-api host supports a top-level ``http`` key in
``langgraph.json`` that names an ASGI app to mount on the same
process as the graph. We use it to surface the registry the WebUI's
``/model`` picker needs.

Why this lives here and not as a separate sidecar: the WebUI talks to
``ImagingSci deploy``'s langgraph endpoint anyway, so one origin keeps the
WebUI's fetch logic simple — no CORS dance, no extra port to configure.

Why Starlette and not FastAPI: ``langgraph_api`` already depends on
Starlette; adding FastAPI would pull in pydantic v1-vs-v2 reconciliation
the deploy doesn't need. The one route here has no input model, just a
JSON body, so the lower-level surface is sufficient.

Lightweight by design — module-level imports stick to ``config``,
``llm.models`` (registry only; no chat-model construction), and
Starlette itself. Nothing on this surface should pull the agent into
memory.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from imaging_scientist.config import load_config, save_config
from imaging_scientist.llm.models import list_model_picker_entries, provider_interface


# Public WebUI updates are constrained to these LLM connection fields. This is
# intentionally not a generic YAML editor: it prevents unrelated deployment
# settings from being changed through an unauthenticated local browser route.
_PROVIDER_FIELDS: dict[str, dict[str, str | None]] = {
    "anthropic": {
        "key": "anthropic_api_key", "key_env": "ANTHROPIC_API_KEY",
        "base": "anthropic_base_url", "base_env": "ANTHROPIC_BASE_URL",
    },
    "openai": {
        "key": "openai_api_key", "key_env": "OPENAI_API_KEY",
        "base": "openai_base_url", "base_env": "OPENAI_BASE_URL",
    },
    "nvidia": {"key": "nvidia_api_key", "key_env": "NVIDIA_API_KEY", "base": None, "base_env": None},
    "google-genai": {"key": "google_api_key", "key_env": "GOOGLE_API_KEY", "base": None, "base_env": None},
    "minimax": {"key": "minimax_api_key", "key_env": "MINIMAX_API_KEY", "base": "minimax_base_url", "base_env": "MINIMAX_BASE_URL"},
    "siliconflow": {"key": "siliconflow_api_key", "key_env": "SILICONFLOW_API_KEY", "base": None, "base_env": None},
    "openrouter": {"key": "openrouter_api_key", "key_env": "OPENROUTER_API_KEY", "base": None, "base_env": None},
    "deepseek": {"key": "deepseek_api_key", "key_env": "DEEPSEEK_API_KEY", "base": None, "base_env": None},
    "zhipu": {"key": "zhipu_api_key", "key_env": "ZHIPU_API_KEY", "base": None, "base_env": None},
    "zhipu-code": {"key": "zhipu_api_key", "key_env": "ZHIPU_API_KEY", "base": None, "base_env": None},
    "volcengine": {"key": "volcengine_api_key", "key_env": "VOLCENGINE_API_KEY", "base": None, "base_env": None},
    "dashscope": {"key": "dashscope_api_key", "key_env": "DASHSCOPE_API_KEY", "base": None, "base_env": None},
    "dashscope-code": {"key": "dashscope_api_key", "key_env": "DASHSCOPE_API_KEY", "base": None, "base_env": None},
    "moonshot": {"key": "moonshot_api_key", "key_env": "MOONSHOT_API_KEY", "base": None, "base_env": None},
    "kimi-coding": {"key": "kimi_api_key", "key_env": "KIMI_API_KEY", "base": None, "base_env": None},
    "custom-openai": {"key": "custom_openai_api_key", "key_env": "CUSTOM_OPENAI_API_KEY", "base": "custom_openai_base_url", "base_env": "CUSTOM_OPENAI_BASE_URL"},
    "custom-anthropic": {"key": "custom_anthropic_api_key", "key_env": "CUSTOM_ANTHROPIC_API_KEY", "base": "custom_anthropic_base_url", "base_env": "CUSTOM_ANTHROPIC_BASE_URL"},
    "ollama": {"key": None, "key_env": None, "base": "ollama_base_url", "base_env": "OLLAMA_BASE_URL"},
}


def _masked_key(value: str) -> str | None:
    """Return a non-reversible indicator for an existing credential."""
    if not value:
        return None
    return "*" * min(8, max(4, len(value) - 4)) + value[-4:]


def _runtime_config_payload(cfg: Any) -> dict[str, Any]:
    provider = str(cfg.provider)
    provider_fields = _PROVIDER_FIELDS.get(provider)
    if provider_fields is None:
        return {
            "provider": provider,
            "model": str(cfg.model),
            "keyConfigured": False,
            "apiKeyHint": None,
            "baseUrl": "",
            "baseUrlSupported": False,
            "newRequestsUseUpdatedConfig": True,
        }
    key_field = provider_fields["key"]
    key_env = provider_fields["key_env"]
    base_field = provider_fields["base"]
    # This response represents the profile saved by the WebUI.  Do not read
    # the process environment here: it may contain a .env value from before a
    # user changed this profile, which made the dialog appear to revert on a
    # page refresh.  API keys remain write-only; only this masked indicator is
    # returned to the browser.
    key_value = str(getattr(cfg, key_field, "") or "") if key_field else ""
    return {
        "provider": provider,
        "model": str(cfg.model),
        "keyConfigured": bool(key_value),
        "apiKeyHint": _masked_key(key_value),
        "baseUrl": str(getattr(cfg, base_field, "") or "") if base_field else "",
        "baseUrlSupported": bool(base_field),
        "newRequestsUseUpdatedConfig": True,
    }


async def _runtime_config_with_models(cfg: Any) -> dict[str, Any]:
    """Attach the backend's provider-aware model registry to a safe payload."""
    payload = _runtime_config_payload(cfg)
    entries, warning = await _webui_model_entries(cfg)
    payload["catalogWarning"] = warning
    payload["models"] = [
        {"name": name, "modelId": model_id, "provider": provider}
        for name, model_id, provider in entries
    ]
    return payload


async def _webui_model_entries(cfg: Any):
    from imaging_scientist.llm.gateway_catalog import discover_gateway_models

    entries = await list_model_picker_entries(
        getattr(cfg, "ollama_base_url", None), include_custom_ollama=False,
    )
    base = getattr(cfg, "custom_openai_base_url", "") or ""
    key = getattr(cfg, "custom_openai_api_key", "") or ""
    warning = None
    if base or cfg.provider == "custom-openai":
        names, warning = await discover_gateway_models(base, key)
        if names is not None:
            entries = [(name, name, "custom-openai") for name in names] + [
                entry for entry in entries if entry[2] != "custom-openai"
            ]
    return entries, warning


def _read_string(
    body: dict[str, Any],
    name: str,
    *,
    required: bool = False,
    maximum: int = 4096,
) -> str | None:
    if name not in body:
        if required:
            raise ValueError(f"{name} is required")
        return None
    value = body[name]
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{name} is required")
    if len(value) > maximum:
        raise ValueError(f"{name} is too long")
    return value


async def get_runtime_config(_request: Request) -> JSONResponse:
    """Return the saved WebUI API profile without exposing its API key."""
    cfg = await asyncio.to_thread(load_config)
    return JSONResponse(await _runtime_config_with_models(cfg))


async def put_runtime_config(request: Request) -> JSONResponse:
    """Persist and apply a narrow LLM API update in the running process."""
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("request body must be an object")
        provider = _read_string(body, "provider", required=True, maximum=64)
        model = _read_string(body, "model", required=True, maximum=256)
        assert provider is not None and model is not None
        provider_fields = _PROVIDER_FIELDS.get(provider)
        if provider_fields is None:
            raise ValueError("unsupported provider")
        api_key = _read_string(body, "apiKey", maximum=4096)
        base_url = _read_string(body, "baseUrl", maximum=2048)
        if base_url and not base_url.startswith(("http://", "https://")):
            raise ValueError("baseUrl must start with http:// or https://")
        if base_url is not None and not provider_fields["base"]:
            raise ValueError("this provider does not support a custom base URL")

        file_cfg = await asyncio.to_thread(load_config)
        updates: dict[str, str] = {"provider": provider, "model": model}
        key_field = provider_fields["key"]
        base_field = provider_fields["base"]
        # An empty password field means "leave the stored key unchanged".
        if api_key:
            if not key_field:
                raise ValueError("this provider does not use an API key")
            updates[str(key_field)] = api_key
        if base_url is not None and base_field:
            updates[str(base_field)] = base_url.rstrip("/")
        new_cfg = replace(file_cfg, **updates)
        await asyncio.to_thread(save_config, new_cfg)

        # The standard loader is set-if-unset to respect shell configuration.
        # A change made in this local WebUI is explicit, so apply the saved
        # value for its selected provider to the live process as well.  Using
        # ``new_cfg`` (rather than only request fields) preserves an existing
        # per-provider key when the user changes just the model.
        key_env = provider_fields["key_env"]
        if key_env and key_field:
            key_value = str(getattr(new_cfg, key_field, "") or "")
            if key_value:
                os.environ[str(key_env)] = key_value
            else:
                os.environ.pop(str(key_env), None)
        base_env = provider_fields["base_env"]
        if base_env and base_field:
            saved_base_url = str(getattr(new_cfg, base_field, "") or "")
            if saved_base_url:
                os.environ[str(base_env)] = saved_base_url
            else:
                os.environ.pop(str(base_env), None)

        from imaging_scientist.imaging_scientist import refresh_runtime_config

        refresh_runtime_config(new_cfg)
        return JSONResponse(await _runtime_config_with_models(new_cfg))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except Exception:
        # Do not reflect provider-library errors; they can include endpoint or
        # credential-adjacent values supplied by the user.
        return JSONResponse(
            {"error": "Could not update API configuration."}, status_code=500
        )


async def get_models(_request: Request) -> JSONResponse:
    """Return the model registry as ``{entries, default}``.

    ``entries`` preserves the registry order so the WebUI picker can
    rank providers per short name the same way the backend would.
    Mirrors the TUI ``/model`` picker by appending locally-pulled
    Ollama models when ``ollama_base_url`` is configured — same
    ``discover_ollama_models()`` call, same 1.5-s timeout, same
    fail-soft semantics (the probe returns ``[]`` on any error, never
    raises). The TUI's "Custom Ollama model…" sentinel is intentionally
    omitted: that's a widget-specific input affordance, not part of
    the registry surface.

    ``default`` reflects the WebUI's saved connection profile
    (``config.yaml``'s ``model`` / ``provider`` — what ``/model reset``
    would land on). Returned even when the configured pair isn't in
    the registry, so the picker can still label it.

    Uses ``load_config()`` so the picker and the API-configuration dialog use
    one durable source after a page refresh.  The active runtime is updated
    from the same config by ``put_runtime_config()``.
    """
    cfg = await asyncio.to_thread(load_config)
    model_entries, warning = await _webui_model_entries(cfg)
    entries = [
        {"name": name, "model_id": model_id, "provider": provider,
         "interface": provider_interface(provider)}
        for name, model_id, provider in model_entries
    ]
    return JSONResponse(
        {
            "entries": entries,
            "catalogWarning": warning,
            "default": {"name": cfg.model, "provider": cfg.provider,
                         "interface": provider_interface(cfg.provider)},
        }
    )


app = Starlette(
    routes=[
        Route("/api/models", get_models, methods=["GET"]),
        Route("/api/runtime-config", get_runtime_config, methods=["GET"]),
        Route("/api/runtime-config", put_runtime_config, methods=["PUT"]),
    ]
)
