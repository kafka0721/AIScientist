from unittest.mock import AsyncMock, patch

import httpx
import pytest

from imaging_scientist.llm.gateway_catalog import discover_gateway_models


@pytest.fixture(autouse=True)
def clear_catalog_cache():
    from imaging_scientist.llm.gateway_catalog import _catalog_cache
    _catalog_cache.clear()
    yield
    _catalog_cache.clear()


async def test_transient_failure_preserves_key_scoped_catalog():
    with patch("imaging_scientist.llm.gateway_catalog._fetch_gateway_models", new_callable=AsyncMock) as fetch:
        fetch.return_value = (["gpt-6-astra"], None)
        with patch("imaging_scientist.llm.gateway_catalog.time.monotonic", return_value=100):
            await discover_gateway_models("https://gateway.example/v1", "key-a")
        fetch.return_value = (None, "timeout")
        with patch("imaging_scientist.llm.gateway_catalog.time.monotonic", return_value=200):
            names, warning = await discover_gateway_models("https://gateway.example/v1", "key-a")
            assert names == ["gpt-6-astra"]
            assert warning
            assert (await discover_gateway_models("https://gateway.example/v1", "key-b"))[0] is None
        fetch.return_value = (None, "HTTP 401")
        with patch("imaging_scientist.llm.gateway_catalog.time.monotonic", return_value=201):
            assert (await discover_gateway_models("https://gateway.example/v1", "key-a"))[0] is None


async def test_catalog_uses_configured_key_and_preserves_exact_ids():
    response = httpx.Response(200, json={"data": [{"id": "gpt-6-astra"}, {"id": "gpt-5.6-sol"}, {"id": "gpt-6-astra"}]})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response) as get:
        names, warning = await discover_gateway_models("https://gateway.example/v1/", "test-secret")
    assert names == ["gpt-6-astra", "gpt-5.6-sol"]
    assert warning is None
    get.assert_awaited_once_with("https://gateway.example/v1/models", headers={"Authorization": "Bearer test-secret"})


@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_catalog_errors_do_not_expose_response(status):
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=httpx.Response(status, text="secret")):
        names, warning = await discover_gateway_models("https://gateway.example/v1", "secret")
    assert names is None
    assert str(status) in warning
    assert "secret" not in warning


async def test_empty_catalog_is_not_replaced_by_static_models():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=httpx.Response(200, json={"data": []})):
        assert await discover_gateway_models("https://gateway.example/v1", "secret") == ([], None)


async def test_webui_replaces_custom_reference_list_in_both_endpoints():
    from types import SimpleNamespace
    from imaging_scientist.langgraph_dev.http import _webui_model_entries, _runtime_config_with_models

    cfg = SimpleNamespace(provider="custom-openai", model="gpt-6-astra",
                          custom_openai_base_url="https://gateway.example/v1",
                          custom_openai_api_key="test-secret")
    with patch("imaging_scientist.llm.gateway_catalog.discover_gateway_models", new_callable=AsyncMock,
               return_value=(["gpt-6-astra", "gpt-5.6-sol"], None)):
        entries, warning = await _webui_model_entries(cfg)
        payload = await _runtime_config_with_models(cfg)
    assert warning is None
    assert [e[0] for e in entries if e[2] == "custom-openai"] == ["gpt-6-astra", "gpt-5.6-sol"]
    assert [e["name"] for e in payload["models"] if e["provider"] == "custom-openai"] == ["gpt-6-astra", "gpt-5.6-sol"]
