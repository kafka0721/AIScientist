"""Exercise the production model factory and sequential streaming requests."""
import asyncio
import json
import os
import time
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ['WITAISCIENTIST_CONFIG_PATH'] = str(ROOT / 'user-config/config.yaml')
if '--truststore' in sys.argv:
    import truststore
    truststore.inject_into_ssl()
from imaging_scientist.config import get_effective_config, apply_config_to_env
from imaging_scientist.llm import get_chat_model
from imaging_scientist.llm.gateway_transport import AsyncGatewayClient, GatewayClient


async def main():
    if '--runtime' in sys.argv:
        import psutil
        from urllib.parse import urlsplit
        pid = int((ROOT / '.imaging-scientist-runtime/langgraph_dev.pid').read_text().strip())
        result = []
        for process in [psutil.Process(pid), *psutil.Process(pid).children(recursive=True)]:
            env = process.environ()
            proxies = {}
            for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy']:
                if env.get(key):
                    u = urlsplit(env[key])
                    proxies[key] = dict(scheme=u.scheme, host=u.hostname, port=u.port)
            result.append(dict(pid=process.pid, proxies=proxies,
                               config_path=env.get('WITAISCIENTIST_CONFIG_PATH')))
        print(json.dumps(result), flush=True)
        return
    cfg = get_effective_config()
    apply_config_to_env(cfg)
    results = []
    for attempt in range(6):
        # A new model/connection each time exercises the failing handshake path.
        model = get_chat_model(model=cfg.model, provider=cfg.provider)
        assert isinstance(model.root_client._client, GatewayClient)
        assert isinstance(model.root_async_client._client, AsyncGatewayClient)
        started = time.monotonic()
        result = dict(attempt=attempt+1, chunks=0, chars=0)
        try:
            async for chunk in model.astream('Connection verification. Reply only OK.'):
                result['chunks'] += 1
                result['chars'] += len(chunk.content)
                if chunk.response_metadata.get('finish_reason'):
                    result['finish_reason'] = chunk.response_metadata['finish_reason']
            result['passed'] = result['chars'] > 0 and result.get('finish_reason') == 'stop'
        except Exception as error:
            result.update(passed=False, error=type(error).__name__)
        finally:
            await model.root_async_client.close()
            model.root_client.close()
        result['seconds'] = round(time.monotonic()-started, 2)
        results.append(result)
        print(json.dumps(result), flush=True)
    report = dict(time=datetime.now().astimezone().isoformat(), model=cfg.model,
                  truststore_injected='--truststore' in sys.argv,
                  tls_profile=cfg.gateway_tls_profile, results=results,
                  passed=all(row['passed'] for row in results))
    filename = 'gateway-repair-truststore-live.json' if '--truststore' in sys.argv else 'gateway-repair-live.json'
    (ROOT / 'artifacts' / filename).write_text(json.dumps(report, indent=2), encoding='utf-8')
    assert report['passed'], 'See gateway-repair-live.json'


asyncio.run(main())
