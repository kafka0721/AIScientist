"""Probe the configured model without printing credentials or user content."""

import asyncio
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["WITAISCIENTIST_CONFIG_PATH"] = str(ROOT / "user-config/config.yaml")

from imaging_scientist.config import get_effective_config, apply_config_to_env
from imaging_scientist.llm import get_chat_model


async def main():
    cfg = get_effective_config()
    apply_config_to_env(cfg)
    print(json.dumps({"model": cfg.model, "provider": cfg.provider,
                      "auxiliary_model": cfg.auxiliary_model or "follows main",
                      "proxy_env_present": [key for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY") if os.environ.get(key)]}), flush=True)
    model = get_chat_model(model=cfg.model, provider=cfg.provider, max_retries=0, timeout=45)
    results = []
    for attempt in range(2):
        started = time.monotonic()
        try:
            response = await model.ainvoke("Connection check. Reply only OK.")
            result = {"attempt": attempt + 1, "status": "success", "returned_model": response.response_metadata.get("model_name"), "has_content": bool(response.content)}
        except Exception as exc:
            chain = []
            current = exc
            while current is not None and len(chain) < 8:
                chain.append({"type": type(current).__name__, "errno": getattr(current, "errno", None), "detail": str(current)[:350] if type(current).__name__ in {"ConnectError", "ConnectTimeout", "ProxyError", "RemoteProtocolError", "SSLError", "OSError"} else None})
                current = current.__cause__ or current.__context__
            result = {"attempt": attempt + 1, "status": "error", "causes": chain}
        result["seconds"] = round(time.monotonic() - started, 2)
        results.append(result)
        print(json.dumps(result), flush=True)
    (ROOT / "artifacts/model-connection-check.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
