import asyncio
import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from imaging_scientist.llm import gateway_transport as gt


@pytest.fixture
def profile(monkeypatch):
    config = SimpleNamespace(gateway_tls_profile="x25519", gateway_proxy="")
    monkeypatch.setattr("imaging_scientist.config.get_effective_config", lambda: config)
    return config


@pytest.mark.asyncio
async def test_read_failure_logs_actual_phase_without_replay_or_secret(monkeypatch, caplog):
    original_trace = AsyncMock()
    request = httpx.Request("POST", "https://example.com", content=b"secret prompt",
                           headers={"authorization": "Bearer SECRET"}, extensions={"trace": original_trace})
    calls = []

    async def send(self, request, **kwargs):
        calls.append(request)
        await request.extensions['trace']('http11.receive_response_headers.failed', {'secret': 'SECRET'})
        underlying = OSError('SECRET network message')
        underlying.winerror = 64
        raise httpx.ReadError('SECRET') from underlying

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    async with gt.AsyncGatewayClient() as client:
        with pytest.raises(httpx.ReadError):
            await client.send(request)
    assert len(calls) == 1
    assert request.extensions['trace'] is original_trace
    original_trace.assert_awaited_once()
    assert 'receive_response_headers.failed' in caplog.text
    assert 'winerror=64' in caplog.text and 'bytes=13' in caplog.text
    assert 'SECRET' not in caplog.text and 'secret prompt' not in caplog.text


@pytest.mark.asyncio
async def test_explicit_proxy_routes_sync_and_async_clients(profile, monkeypatch):
    # Exercise CONNECT routing, including when another environment proxy exists.
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    paths = []

    class Proxy(BaseHTTPRequestHandler):
        def do_CONNECT(self):
            paths.append(self.path)
            self.send_response(502)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    profile.gateway_proxy = f'http://127.0.0.1:{server.server_port}'
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:1')
    try:
        with gt.GatewayClient(**gt.gateway_client_kwargs()) as client:
            with pytest.raises(httpx.ProxyError):
                client.get('https://example.invalid/test')
        async with gt.AsyncGatewayClient(**gt.gateway_client_kwargs()) as client:
            with pytest.raises(httpx.ProxyError):
                await client.get('https://example.invalid/test')
        assert paths == ['example.invalid:443', 'example.invalid:443']
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_invalid_proxy_does_not_leak_credentials(profile):
    profile.gateway_proxy = 'socks5://SECRET:password@localhost:7890'
    with pytest.raises(ValueError, match='gateway_proxy') as error:
        gt.gateway_client_kwargs()
    assert 'SECRET' not in str(error.value)


@pytest.mark.parametrize("use_truststore", [False, True])
def test_tls_keeps_verification_and_uses_small_clienthello(profile, monkeypatch, use_truststore):
    if use_truststore:
        import truststore

        # LangGraph injects this class into ssl before importing the graph.
        monkeypatch.setattr(ssl, "SSLContext", truststore.SSLContext)
    ctx = gt.gateway_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    tls = ctx.wrap_bio(incoming, outgoing, server_hostname="example.com")
    with pytest.raises(ssl.SSLWantReadError):
        tls.do_handshake()
    assert len(outgoing.read()) < 1000


def test_invalid_tls_profile_fails_closed(profile):
    profile.gateway_tls_profile = "insecure"
    with pytest.raises(ValueError):
        gt.gateway_ssl_context()


def test_sync_retries_connection_before_sending_body(monkeypatch):
    request = httpx.Request("POST", "https://example.com", content=b"once")
    send = Mock(side_effect=[httpx.ConnectError("failed"), httpx.Response(200)])
    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(gt.time, "sleep", Mock())
    with gt.GatewayClient() as client:
        assert client.send(request).status_code == 200
    assert send.call_count == 2


@pytest.mark.parametrize("error", [httpx.ReadError, httpx.ReadTimeout, httpx.WriteError, httpx.PoolTimeout])
def test_sync_does_not_replay_uncertain_or_consumed_request(monkeypatch, error):
    send = Mock(side_effect=error("failed"))
    monkeypatch.setattr(httpx.Client, "send", send)
    with gt.GatewayClient() as client, pytest.raises(error):
        client.send(httpx.Request("POST", "https://example.com"))
    assert send.call_count == 1


@pytest.mark.asyncio
async def test_async_connection_retry_has_finite_budget_and_safe_logging(monkeypatch, caplog):
    send = AsyncMock(side_effect=httpx.ConnectError("SECRET-BEARER"))
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    delay = AsyncMock()
    monkeypatch.setattr(gt.asyncio, "sleep", delay)
    async with gt.AsyncGatewayClient() as client:
        with pytest.raises(httpx.ConnectError):
            await client.send(httpx.Request("POST", "https://example.com"))
    assert send.call_count == 2
    assert delay.call_count == 1
    assert "ConnectError" in caplog.text and "SECRET-BEARER" not in caplog.text


@pytest.mark.asyncio
async def test_async_recovers_without_retrying_partial_stream(monkeypatch):
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"first token"
            raise httpx.ReadError("stream disconnected")

    response = httpx.Response(200, stream=BrokenStream())
    send = AsyncMock(side_effect=[httpx.ConnectTimeout("tls"), response])
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    monkeypatch.setattr(gt.asyncio, "sleep", AsyncMock())
    async with gt.AsyncGatewayClient() as client:
        result = await client.send(httpx.Request("POST", "https://example.com"), stream=True)
        chunks = []
        with pytest.raises(httpx.ReadError):
            async for chunk in result.aiter_bytes():
                chunks.append(chunk)
    assert chunks == [b"first token"]
    assert send.call_count == 2


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed(monkeypatch):
    send = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    async with gt.AsyncGatewayClient() as client:
        with pytest.raises(asyncio.CancelledError):
            await client.send(httpx.Request("POST", "https://example.com"))
    assert send.call_count == 1


def test_factory_preserves_caller_clients_and_timeout(profile):
    sync, async_ = object(), object()
    kwargs = dict(http_client=sync, http_async_client=async_, timeout=7, max_retries=0)
    gt.configure_gateway_model(kwargs)
    assert kwargs == dict(http_client=sync, http_async_client=async_, timeout=7, max_retries=0)


@pytest.mark.asyncio
async def test_actual_model_factory_wires_both_clients(profile, monkeypatch):
    from imaging_scientist.llm import get_chat_model

    monkeypatch.setenv("CUSTOM_OPENAI_API_KEY", "test")
    monkeypatch.setenv("CUSTOM_OPENAI_BASE_URL", "https://example.com/v1")
    model = get_chat_model(model="gpt-6-astra", provider="custom-openai")
    try:
        assert isinstance(model.root_client._client, gt.GatewayClient)
        assert isinstance(model.root_async_client._client, gt.AsyncGatewayClient)
        assert model.root_async_client.timeout.connect == 20
        assert model.root_async_client.timeout.read == 300
        assert model.root_async_client.max_retries == 2
    finally:
        model.root_client.close()
        await model.root_async_client.close()
