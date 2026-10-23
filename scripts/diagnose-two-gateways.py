"""Compare independent TLS clients without API credentials or generation."""
import asyncio
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

HOSTS = ['api.shuaiapi.com', 'sub.micuapi.ai']
ROOT = Path(__file__).resolve().parents[1]


def chain(exc):
    result, seen = [], set()
    while exc and id(exc) not in seen:
        seen.add(id(exc))
        result.append({'type': type(exc).__name__, 'detail': str(exc)[:200]})
        exc = exc.__cause__ or exc.__context__
    return result


def tls(host, ip, tls12=False, curve=None):
    start = time.monotonic()
    result = dict(client='python_ssl_tls13_x25519' if curve else ('python_ssl_tls12' if tls12 else 'python_ssl'), host=host, ip=ip)
    try:
        with socket.create_connection((ip, 443), timeout=18) as sock:
            result['tcp_seconds'] = round(time.monotonic() - start, 3)
            context = ssl.create_default_context()
            if tls12:
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.maximum_version = ssl.TLSVersion.TLSv1_2
            if curve:
                context.minimum_version = ssl.TLSVersion.TLSv1_3
                context.set_ecdh_curve(curve)
            incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
            memory_tls = context.wrap_bio(incoming, outgoing, server_side=False, server_hostname=host)
            try:
                memory_tls.do_handshake()
            except ssl.SSLWantReadError:
                pass
            result['clienthello_bytes'] = len(outgoing.read())
            with context.wrap_socket(sock, server_hostname=host) as stream:
                result.update(ok=True, tls=stream.version())
    except Exception as exc:
        result.update(ok=False, causes=chain(exc))
    result['seconds'] = round(time.monotonic() - start, 3)
    return result


def curl(host, ip):
    start = time.monotonic()
    p = subprocess.run([
        'C:/Windows/System32/curl.exe', '--noproxy', '*', '--silent', '--show-error',
        '--connect-timeout', '18', '--max-time', '22', '--output', 'NUL',
        '--resolve', f'{host}:443:{ip}', '--write-out', '%{http_code} %{time_appconnect}',
        f'https://{host}/v1/models'
    ], capture_output=True, text=True, timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
    return dict(client='windows_curl', host=host, ip=ip, ok=p.returncode == 0,
                code=p.returncode, result=p.stdout.strip(), error=p.stderr[:300],
                seconds=round(time.monotonic() - start, 3))


async def direct(host, attempt):
    start = time.monotonic()
    result = dict(client='httpx_direct', host=host, attempt=attempt, events=[])
    async def trace(event, info):
        if 'start_tls' in event or 'connect_tcp' in event:
            e = dict(event=event, seconds=round(time.monotonic() - start, 3))
            if 'exception' in info:
                e['causes'] = chain(info['exception'])
            result['events'].append(e)
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=20) as client:
            async with client.stream('GET', f'https://{host}/v1/models', extensions={'trace': trace}) as response:
                result.update(ok=True, status=response.status_code)
    except Exception as exc:
        result.update(ok=False, causes=chain(exc))
    result['seconds'] = round(time.monotonic() - start, 3)
    return result


async def main():
    if '--inspect-client' in sys.argv:
        os.environ['WITAISCIENTIST_CONFIG_PATH'] = str(ROOT / 'user-config/config.yaml')
        from imaging_scientist.config import get_effective_config, apply_config_to_env
        from imaging_scientist.llm import get_chat_model
        from importlib.metadata import version
        from urllib.parse import urlsplit
        cfg = get_effective_config()
        apply_config_to_env(cfg)
        model = get_chat_model(model=cfg.model, provider=cfg.provider)
        result = dict(model=cfg.model, host=urlsplit(str(model.openai_api_base)).hostname,
                      sdk_retries=model.root_async_client.max_retries,
                      timeout=str(model.root_async_client.timeout),
                      ssl=ssl.OPENSSL_VERSION,
                      versions={name: version(name) for name in ['openai', 'httpx', 'httpcore', 'anyio', 'langchain-openai']})
        (ROOT / 'artifacts/model-client-settings-audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
        await model.root_async_client.close()
        model.root_client.close()
        return
    if '--model-compare' in sys.argv:
        os.environ['WITAISCIENTIST_CONFIG_PATH'] = str(ROOT / 'user-config/config.yaml')
        from imaging_scientist.config import get_effective_config, apply_config_to_env
        from imaging_scientist.llm import get_chat_model
        cfg = get_effective_config()
        apply_config_to_env(cfg)
        results = []
        print(json.dumps(dict(model=cfg.model, provider=cfg.provider)), flush=True)
        for attempt in range(1, 4):
            for tls12 in [False, True]:
                context = ssl.create_default_context()
                if tls12:
                    if '--x25519' in sys.argv:
                        context.minimum_version = ssl.TLSVersion.TLSv1_3
                        context.set_ecdh_curve('X25519')
                    else:
                        context.minimum_version = ssl.TLSVersion.TLSv1_2
                        context.maximum_version = ssl.TLSVersion.TLSv1_2
                alternative = 'TLS1.3-X25519' if '--x25519' in sys.argv else 'TLS1.2'
                result = dict(attempt=attempt, mode=alternative if tls12 else 'default', chunks=0, content_chars=0)
                started = time.monotonic()
                try:
                    async with httpx.AsyncClient(verify=context, trust_env=False, timeout=httpx.Timeout(45, connect=20)) as client:
                        model = get_chat_model(model=cfg.model, provider=cfg.provider, http_async_client=client, timeout=httpx.Timeout(45, connect=20), max_retries=0)
                        async for chunk in model.astream('Diagnostic connection test. Reply only OK.'):
                            result['chunks'] += 1
                            result['content_chars'] += len(chunk.content)
                            if chunk.response_metadata.get('finish_reason'):
                                result['finish_reason'] = chunk.response_metadata['finish_reason']
                        result['ok'] = bool(result['content_chars'])
                except Exception as exc:
                    result.update(ok=False, causes=[{'type': x['type']} for x in chain(exc)])
                result['seconds'] = round(time.monotonic() - started, 3)
                results.append(result)
                print(json.dumps(result), flush=True)
        filename = 'gateway-stream-x25519-comparison.json' if '--x25519' in sys.argv else 'gateway-stream-model-comparison.json'
        (ROOT / 'artifacts' / filename).write_text(json.dumps(results, indent=2), encoding='utf-8')
        return
    pairs = [(host, ip) for host in HOSTS for ip in sorted({x[4][0] for x in socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)})]
    if '--tls13-groups' in sys.argv:
        results = []
        selected = [(host, next(ip for h, ip in pairs if h == host)) for host in HOSTS]
        for round_number in range(1, 4):
            batch = await asyncio.gather(*(asyncio.to_thread(tls, host, ip, False, curve) for host, ip in selected for curve in [None, 'X25519']))
            for result in batch:
                result['round'] = round_number
                results.append(result)
                print(json.dumps(result), flush=True)
        (ROOT / 'artifacts/two-gateway-tls13-groups.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        return
    if '--tls-version' in sys.argv:
        results = []
        selected = [(host, next(ip for h, ip in pairs if h == host)) for host in HOSTS]
        for round_number in range(1, 3):
            batch = await asyncio.gather(*(asyncio.to_thread(tls, host, ip, version) for host, ip in selected for version in [False, True]))
            for result in batch:
                result['round'] = round_number
                results.append(result)
                print(json.dumps(result), flush=True)
        (ROOT / 'artifacts/two-gateway-tls-version.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        return
    results = []
    for test in [tls, curl]:
        batch = await asyncio.gather(*(asyncio.to_thread(test, host, ip) for host, ip in pairs))
        for result in batch:
            results.append(result)
            print(json.dumps(result), flush=True)
    for attempt in range(1, 4):
        batch = await asyncio.gather(*(direct(host, attempt) for host in HOSTS))
        for result in batch:
            results.append(result)
            print(json.dumps(result), flush=True)
    target = ROOT / 'artifacts/two-gateway-diagnostic.json'
    target.write_text(json.dumps(dict(time=datetime.now().astimezone().isoformat(), results=results), indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
