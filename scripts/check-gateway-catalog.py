"""Read-only check; prints model IDs, never credentials or response bodies."""
import asyncio
import os

os.environ["WITAISCIENTIST_CONFIG_PATH"] = "E:/AIScientist/user-config/config.yaml"

from imaging_scientist.config import load_config
from imaging_scientist.llm.gateway_catalog import discover_gateway_models


async def main():
    cfg = load_config()
    names, warning = await discover_gateway_models(cfg.custom_openai_base_url, cfg.custom_openai_api_key)
    print({"warning": warning, "count": len(names) if names is not None else None,
           "matching_ids": [n for n in names or [] if "gpt-5.6" in n or "gpt-6" in n]})


asyncio.run(main())
