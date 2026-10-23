"""Verified TLS and bounded, pre-request connection recovery for gateways."""
from __future__ import annotations

import asyncio
import logging
import inspect
import ssl
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)
GATEWAY_TIMEOUT = httpx.Timeout(connect=20, read=300, write=60, pool=30)


def gateway_ssl_context() -> ssl.SSLContext:
    from ..config import get_effective_config

    profile = get_effective_config().gateway_tls_profile
    context = ssl.create_default_context()
    if profile == "x25519":
        # Keep TLS 1.2/1.3 and certificate/hostname verification. Avoid the
        # OpenSSL 3.5 default hybrid key share that fails on some network paths.
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        curve_context = context
        if type(context).__module__ == "truststore._api":
            # LangGraph injects truststore.SSLContext. Its inherited
            # set_ecdh_curve changes the unused wrapper, not the context used
            # by wrap_bio/wrap_socket. Configure only this instance's backing
            # context; keep truststore's OS certificate verification intact.
            # Fail explicitly if a future truststore version changes this API.
            curve_context = getattr(context, "_ctx", None)
            if not callable(getattr(curve_context, "set_ecdh_curve", None)):
                raise RuntimeError("Unsupported truststore context for x25519 TLS profile")
        curve_context.set_ecdh_curve("X25519")
    elif profile != "default":
        raise ValueError("gateway_tls_profile must be default or x25519")
    return context


def _log_connection_error(error: Exception, retry: bool, *, phase: str = "unknown", size: int = -1, elapsed: float = 0) -> None:
    names, seen = [], set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = type(current).__name__
        code = getattr(current, "winerror", None)
        names.append(f"{name}(winerror={code})" if isinstance(code, int) else name)
        current = current.__cause__ or current.__context__
    # Never log requests, headers, URLs, credentials, or exception text.
    logger.warning("Gateway transport failed; retry=%s; phase=%s; bytes=%s; seconds=%.2f; causes=%s",
                   retry, phase, size, elapsed, " -> ".join(names))


class _RequestTrace:
    """Retain only transport phases, never trace info containing credentials."""

    def __init__(self, request: httpx.Request):
        self.started = time.monotonic()
        self.phase = "pool"
        length = request.headers.get("content-length", "")
        self.size = int(length) if length.isdecimal() and len(length) < 16 else -1
        self.previous = request.extensions.get("trace")

    def observe(self, event: str) -> None:
        phases = ("connect_tcp", "start_tls", "send_request_headers", "send_request_body",
                  "receive_response_headers", "receive_response_body")
        for phase in phases:
            if event.endswith((f".{phase}.started", f".{phase}.complete", f".{phase}.failed")):
                self.phase = phase + "." + event.rsplit(".", 1)[-1]

    def sync(self, event: str, info: dict) -> None:
        self.observe(event)
        if self.previous:
            self.previous(event, info)

    async def async_(self, event: str, info: dict) -> None:
        self.observe(event)
        if self.previous:
            result = self.previous(event, info)
            if inspect.isawaitable(result):
                await result

    def log(self, error: Exception, retry: bool) -> None:
        _log_connection_error(error, retry, phase=self.phase, size=self.size,
                              elapsed=time.monotonic() - self.started)

    def restore(self, request: httpx.Request) -> None:
        if self.previous is None:
            request.extensions.pop("trace", None)
        else:
            request.extensions["trace"] = self.previous


class GatewayClient(httpx.Client):
    def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        for attempt in range(2):
            trace = _RequestTrace(request)
            request.extensions["trace"] = trace.sync
            try:
                return super().send(request, **kwargs)
            except httpx.TransportError as error:
                retry = attempt == 0 and isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout))
                trace.log(error, retry)
                if not retry:
                    raise
                time.sleep(1)
            finally:
                trace.restore(request)
        raise AssertionError("unreachable")


class AsyncGatewayClient(httpx.AsyncClient):
    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        for attempt in range(2):
            trace = _RequestTrace(request)
            request.extensions["trace"] = trace.async_
            try:
                return await super().send(request, **kwargs)
            except httpx.TransportError as error:
                retry = attempt == 0 and isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout))
                trace.log(error, retry)
                if not retry:
                    raise
                await asyncio.sleep(1)
            finally:
                trace.restore(request)
        raise AssertionError("unreachable")


def gateway_client_kwargs() -> dict[str, Any]:
    from ..config import get_effective_config

    kwargs = dict(verify=gateway_ssl_context(), timeout=GATEWAY_TIMEOUT,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20,
                                   keepalive_expiry=60))
    proxy = getattr(get_effective_config(), "gateway_proxy", "").strip()
    if proxy:
        from urllib.parse import urlsplit

        try:
            parsed = urlsplit(proxy)
            valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname) and parsed.port is not None
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("gateway_proxy must be an HTTP(S) proxy URL with host and port")
        kwargs.update(proxy=proxy, trust_env=False)
    return kwargs


def configure_gateway_model(kwargs: dict[str, Any]) -> None:
    """Use the same policy for sync, async, main, auxiliary and child models.

    Retry only failures while establishing a connection. Read/write failures,
    partial streams, cancellation and HTTP errors are not replayed here. The
    SDK retains its two retries (including 429/5xx): at most six connection
    attempts in total. Explicit caller clients and settings take precedence.
    """
    kwargs.setdefault("timeout", GATEWAY_TIMEOUT)
    kwargs.setdefault("max_retries", 2)
    if kwargs.get("openai_proxy"):
        return  # LangChain forbids supplying both proxy and custom clients.
    if kwargs.get("http_client") is None:
        kwargs["http_client"] = GatewayClient(**gateway_client_kwargs())
    if kwargs.get("http_async_client") is None:
        kwargs["http_async_client"] = AsyncGatewayClient(**gateway_client_kwargs())
