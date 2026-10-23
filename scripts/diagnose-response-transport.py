"""Trace TLS and HTTP phases without logging credentials, payloads or replies."""
import argparse
import asyncio
import json
import os
import ssl
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import truststore

ROOT = Path(__file__).resolve().parents[1]
os.environ['WITAISCIENTIST_CONFIG_PATH'] = str(ROOT / 'user-config/config.yaml')
truststore.inject_into_ssl()
from imaging_scientist.config import get_effective_config, apply_config_to_env
from imaging_scientist.llm.gateway_transport import gateway_ssl_context


def causes(exc):
    output, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        output.append({'type': type(exc).__name__, 'errno': getattr(exc, 'errno', None),
                       'winerror': getattr(exc, 'winerror', None),
                       'ssl_reason': getattr(exc, 'reason', None) if isinstance(exc, ssl.SSLError) else None})
        exc = exc.__cause__ or exc.__context__
    return output


async def probe(client, base, key, model, profile, attempt, args):
    start = time.monotonic()
    result = dict(profile=profile, attempt=attempt, kind=args.kind,
                  fresh=args.fresh, long=args.long, padding=args.padding,
                  repetitions=args.repetitions, engine=args.engine, pace=args.pace, pinned_ip=args.ip,
                  explicit_local_proxy=args.local_proxy,
                  events=[], response_bytes=0)

    async def trace(event, info):
        # Never serialize info (contains request headers and possibly secrets).
        if any(name in event for name in ['connect_tcp', 'start_tls', 'send_request', 'receive_response']):
            entry = {'event': event, 'seconds': round(time.monotonic() - start, 3)}
            if 'exception' in info:
                entry['causes'] = causes(info['exception'])
            if event == 'connection.start_tls.complete':
                stream = info.get('return_value')
                tls = stream.get_extra_info('ssl_object') if stream else None
                if tls:
                    entry['tls'] = tls.version()
                    entry['cipher'] = tls.cipher()[0]
                if stream:
                    entry['remote'] = stream.get_extra_info('server_addr')
            result['events'].append(entry)

    if args.kind == 'control':
        request = client.build_request('GET', base + '/models', extensions={'trace': trace})
    else:
        content = 'Diagnostic. Reply only OK. Do not use tools.'
        if args.long:
            content += '\nIgnore this synthetic reference:\n' + ('sample alpha beta gamma delta 0123456789.\n' * args.repetitions)
        payload = {'model': model, 'messages': [{'role': 'user', 'content': content}], 'stream': True}
        body = json.dumps(payload).encode() + b' ' * args.padding
        request = client.build_request('POST', base + '/chat/completions', content=body,
                                       headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, extensions={'trace': trace})
        result['request_bytes'] = len(request.content)
        if args.engine == 'curl':
            with tempfile.TemporaryDirectory(prefix='gateway-probe-') as directory:
                payload_path = Path(directory) / 'payload.json'
                payload_path.write_bytes(body)
                config = '\n'.join([
                    'url = ' + json.dumps(base + '/chat/completions'),
                    'header = ' + json.dumps('Authorization: Bearer ' + key),
                    'header = "Content-Type: application/json"',
                    'data-binary = ' + json.dumps('@' + payload_path.as_posix()),
                ])
                command = ['C:/Windows/System32/curl.exe', '--noproxy', '*', '--silent', '--show-error',
                           '--http1.1', '--connect-timeout', '20', '--max-time', '120', '--config', '-',
                           '--write-out', '\nMETRICS %{http_code} %{time_appconnect} %{time_starttransfer} %{size_upload}']
                if profile == 'tls12':
                    command += ['--tlsv1.2', '--tls-max', '1.2']
                if args.ip:
                    command += ['--resolve', f'{urlsplit(base).hostname}:443:{args.ip}']
                process = await asyncio.to_thread(subprocess.run, command, input=config, text=True,
                                                  capture_output=True, timeout=125,
                                                  creationflags=subprocess.CREATE_NO_WINDOW)
            content, _, metrics = process.stdout.rpartition('\nMETRICS ')
            result.update(curl_exit=process.returncode, curl_metrics=metrics.strip(), response_bytes=len(content))
            for line in content.splitlines():
                if line.startswith('data: ') and line[6:] != '[DONE]':
                    for choice in json.loads(line[6:]).get('choices', []):
                        if choice.get('finish_reason'):
                            result['finish_reason'] = choice['finish_reason']
            result['ok'] = process.returncode == 0 and result.get('finish_reason') == 'stop'
            result['seconds'] = round(time.monotonic() - start, 3)
            print(json.dumps(result), flush=True)
            return result
        if args.pace:
            class PacedBody(httpx.AsyncByteStream):
                async def __aiter__(self):
                    for offset in range(0, len(body), 8192):
                        yield body[offset:offset + 8192]
                        await asyncio.sleep(0.01)
            request.stream = PacedBody()
    if args.ip:
        original_host = request.url.host
        request.url = request.url.copy_with(host=args.ip)
        request.headers['Host'] = original_host
        request.extensions['sni_hostname'] = original_host
    try:
        response = await client.send(request, stream=True)
        result['http_status'] = response.status_code
        result['header_seconds'] = round(time.monotonic() - start, 3)
        try:
            if args.kind == 'model' and response.status_code == 200:
                async for line in response.aiter_lines():
                    result['response_bytes'] += len(line)
                    if line.startswith('data: ') and line[6:] != '[DONE]':
                        item = json.loads(line[6:])
                        for choice in item.get('choices', []):
                            if choice.get('finish_reason'):
                                result['finish_reason'] = choice['finish_reason']
                result['ok'] = result.get('finish_reason') == 'stop'
            else:
                result['response_bytes'] = len(await response.aread())
                result['ok'] = args.kind == 'control'
        finally:
            await response.aclose()
    except Exception as exc:
        result.update(ok=False, causes=causes(exc))
    result['seconds'] = round(time.monotonic() - start, 3)
    print(json.dumps(result), flush=True)
    return result


async def main(args):
    cfg = get_effective_config()
    apply_config_to_env(cfg)
    base = os.environ['CUSTOM_OPENAI_BASE_URL'].rstrip('/')
    key = os.environ['CUSTOM_OPENAI_API_KEY']
    profiles = args.profiles.split(',')

    async def series(profile):
        context = gateway_ssl_context()
        if profile == 'tls12':
            context = ssl.create_default_context()
            context.maximum_version = ssl.TLSVersion.TLSv1_2
        kwargs = dict(verify=context, trust_env=False, timeout=httpx.Timeout(120, connect=20),
                      limits=httpx.Limits(max_keepalive_connections=0 if args.fresh else 20, keepalive_expiry=60))
        if args.local_proxy:
            kwargs['proxy'] = 'http://127.0.0.1:7890'
        async with httpx.AsyncClient(**kwargs) as client:
            rows = []
            for attempt in range(1, args.rounds + 1):
                rows.append(await probe(client, base, key, cfg.model, profile, attempt, args))
            return rows

    report = dict(time=datetime.now().astimezone().isoformat(), host=urlsplit(base).hostname,
                  model=cfg.model, truststore=True, proxy=args.local_proxy,
                  results=[row for series_rows in await asyncio.gather(*(series(p) for p in profiles)) for row in series_rows])
    name = f"response-diagnostic-{args.engine}-{args.kind}-{'long' if args.long else 'short'}-{'fresh' if args.fresh else 'reuse'}-{datetime.now():%H%M%S}.json"
    (ROOT / 'artifacts' / name).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'artifact': name, 'passed': sum(row['ok'] for row in report['results']), 'total': len(report['results'])}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', choices=['control', 'model'], default='control')
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--profiles', default='x25519,tls12')
    parser.add_argument('--fresh', action='store_true')
    parser.add_argument('--long', action='store_true')
    parser.add_argument('--padding', type=int, default=0)
    parser.add_argument('--repetitions', type=int, default=5000)
    parser.add_argument('--engine', choices=['httpx', 'curl'], default='httpx')
    parser.add_argument('--pace', action='store_true')
    parser.add_argument('--ip', choices=['172.67.74.19', '104.26.6.67', '104.26.7.67'])
    parser.add_argument('--local-proxy', action='store_true')
    asyncio.run(main(parser.parse_args()))
