"""Read-only TLS/HTTP probes; no API key or model-generation requests."""
import asyncio
import json
import socket
import shutil
import ssl
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

HOST = 'api.shuaiapi.com'
ROOT = Path(__file__).resolve().parents[1]


def causes(exc):
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        chain.append(dict(type=type(exc).__name__, detail=str(exc)[:300],
                          errno=getattr(exc, 'errno', None)))
        exc = exc.__cause__ or exc.__context__
    return chain


def tls_probe(ip, family):
    result = dict(kind='pinned_ip_tls', ip=ip)
    started = time.monotonic()
    try:
        with socket.socket(family, socket.SOCK_STREAM) as raw:
            raw.settimeout(18)
            raw.connect((ip, 443))
            result['tcp_seconds'] = round(time.monotonic() - started, 3)
            with ssl.create_default_context().wrap_socket(raw, server_hostname=HOST) as tls:
                result.update(ok=True, tls=tls.version())
    except Exception as exc:
        result.update(ok=False, causes=causes(exc))
    result['seconds'] = round(time.monotonic() - started, 3)
    return result


async def http_probe(attempt, trust_env=True):
    result = dict(kind='default_httpx' if trust_env else 'direct_httpx', attempt=attempt, events=[])
    started = time.monotonic()

    async def trace(event, info):
        if any(word in event for word in ('connect_tcp', 'start_tls', 'receive_response_headers')):
            entry = dict(event=event, seconds=round(time.monotonic() - started, 3))
            if 'exception' in info:
                entry['causes'] = causes(info['exception'])
            result['events'].append(entry)

    try:
        async with httpx.AsyncClient(timeout=20, trust_env=trust_env) as client:
            async with client.stream('GET', f'https://{HOST}/v1/models', extensions={'trace': trace}) as response:
                result.update(ok=True, http_status=response.status_code)
    except Exception as exc:
        result.update(ok=False, causes=causes(exc))
    result['seconds'] = round(time.monotonic() - started, 3)
    return result


async def main():
    if '--record-logs' in sys.argv:
        direct = json.loads((ROOT / 'artifacts/gateway-direct-http-diagnostic.json').read_text(encoding='utf-8'))
        failures = sum(not row['ok'] for row in direct)
        note = f'''# 中转连接异常定位记录

时间：{datetime.now().astimezone().isoformat()}

对 api.shuaiapi.com 做无密钥、无模型生成的只读 TLS/HTTP 测试。
固定 IP 两轮：104.26.6.67 一次握手失败一次成功；104.26.7.67 两次失败；172.67.74.19 两次成功。
随后使用平台同款 httpx/anyio 直连（trust_env=False），共 {len(direct)} 次，其中 {failures} 次失败。
失败链：SSLEOFError(UNEXPECTED_EOF_WHILE_READING) → EndOfStream → httpcore.ConnectError → httpx.ConnectError。
失败点明确为 connection.start_tls，TCP 已连接，约 15.5 秒时 TLS 握手被提前结束，尚未发送 HTTP 模型请求。
成功完成握手的无密钥 /v1/models 探测返回 HTTP 403；这里只验证传输可达，不作为模型授权成功证据。
未修改平台网络、模型或重试配置。早前两次带密钥短模型测试成功，是独立的模型可用性证据。

结论：已复现本机至中转入口的间歇性 TLS 握手提前断开，能解释同一任务有成功调用记录又报连接失败。
与早前平台 start_tls 的错误栈及约 16 秒重试间隔相吻合；最新历史失败未保留完整异常链，无法逐请求一一证明。
不能据此确定断开由本机安全软件、网络中间设备、运营商还是中转 CDN 边缘触发，也不能认定某 IP 永久失效。
论文进度与 Domain 记忆不受本次只读测试影响。

原始证据：E:/AIScientist/artifacts/gateway-transport-diagnostic.json
直连证据：E:/AIScientist/artifacts/gateway-direct-http-diagnostic.json
'''
        for directory in ['development', 'memory']:
            (Path('E:/data') / directory / '2026-09-19_gateway_tls_diagnosis.md').write_text(note, encoding='utf-8')
        evidence = Path('E:/data/development/gateway_tls_diagnosis')
        evidence.mkdir(exist_ok=True)
        for name in ['gateway-transport-diagnostic.json', 'gateway-direct-http-diagnostic.json']:
            shutil.copy2(ROOT / 'artifacts' / name, evidence / name)
        print(json.dumps(dict(recorded=True, direct_attempts=len(direct), tls_failures=failures)))
        return
    if '--direct-only' in sys.argv:
        results = []
        for attempt in range(1, 5):
            result = await http_probe(attempt, trust_env=False)
            results.append(result)
            print(json.dumps(result), flush=True)
        (ROOT / 'artifacts/gateway-direct-http-diagnostic.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        return
    addresses = sorted({(x[0], x[4][0]) for x in socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)})
    results = []
    for iteration in range(2):
        batch = await asyncio.gather(*(asyncio.to_thread(tls_probe, ip, family) for family, ip in addresses))
        for result in batch:
            result['round'] = iteration + 1
            results.append(result)
            print(json.dumps(result), flush=True)
    for attempt in range(1, 5):
        result = await http_probe(attempt)
        results.append(result)
        print(json.dumps(result), flush=True)
    target = ROOT / 'artifacts/gateway-transport-diagnostic.json'
    target.write_text(json.dumps(dict(timestamp=datetime.now().astimezone().isoformat(), host=HOST, results=results), indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
