"""Read a configured gateway's key-scoped catalog without invoking models."""

from __future__ import annotations

import httpx
import hashlib
import time
import asyncio
import logging

# Isolate catalogs by endpoint AND credential (groups are key-scoped).
# Keep only a bounded, short-lived in-memory cache, never credentials on disk.
_catalog_cache: dict[str, tuple[float, list[str]]] = {}


async def discover_gateway_models(base_url: str, api_key: str) -> tuple[list[str] | None, str | None]:
    scope = hashlib.sha256((base_url.rstrip("/") + "\0" + api_key).encode()).hexdigest()
    cached = _catalog_cache.get(scope)
    if cached and time.monotonic() - cached[0] < 60:
        return list(cached[1]), None
    names, warning = await _fetch_gateway_models(base_url, api_key)
    if names is not None:
        if len(_catalog_cache) >= 32:
            _catalog_cache.pop(next(iter(_catalog_cache)))
        _catalog_cache[scope] = (time.monotonic(), names)
        return list(names), None
    if warning and any(f"HTTP {code}" in warning for code in (401, 403)):
        _catalog_cache.pop(scope, None)
        return None, warning
    if cached and time.monotonic() - cached[0] < 86400:
        return list(cached[1]), "中转站目录暂时无法刷新，继续显示该密钥最近成功获取的模型列表。"
    return names, warning


async def _fetch_gateway_models(base_url: str, api_key: str) -> tuple[list[str] | None, str | None]:
    if not base_url or not api_key:
        return None, "中转站未配置地址或密钥，当前显示本地参考列表。"
    try:
        # Keep credentials on the configured origin; never follow redirects.
        from .gateway_transport import gateway_client_kwargs

        kwargs = await asyncio.to_thread(gateway_client_kwargs)
        kwargs.update(timeout=15, follow_redirects=False)
        client = httpx.AsyncClient(**kwargs)
        async with client:
            response = await client.get(
                base_url.rstrip("/") + "/models",
                headers={"Authorization": "Bearer " + api_key},
            )
        if response.status_code != 200:
            return None, f"中转站模型目录返回 HTTP {response.status_code}，当前显示本地参考列表。"
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ValueError("Invalid catalog")
        names = list(dict.fromkeys(
            item["id"] for item in data["data"]
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
        ))
        if data["data"] and not names:
            raise ValueError("Invalid entries")
        return names, None
    except Exception as exc:
        logging.getLogger(__name__).warning("Gateway catalog request failed (%s)", type(exc).__name__)
        # Never expose response bodies, credentials, or exception request URLs.
        return None, "无法读取中转站模型目录，当前显示本地参考列表；可手动输入模型 ID。"
