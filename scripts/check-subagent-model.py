"""Run the real task tool with a stale child binding and the selected live model."""

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["WITAISCIENTIST_CONFIG_PATH"] = str(ROOT / "user-config/config.yaml")

from deepagents import create_deep_agent
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import imaging_scientist.imaging_scientist as agent_module
from imaging_scientist.config import get_effective_config


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class ModelRecorder(AsyncCallbackHandler):
    def __init__(self):
        self.models = []

    async def on_llm_end(self, response, **kwargs):
        for group in response.generations:
            for generation in group:
                metadata = getattr(getattr(generation, "message", None), "response_metadata", {})
                if metadata.get("model_name"):
                    self.models.append(metadata["model_name"])


async def main():
    cfg = replace(get_effective_config(), memory_profile_enabled=False,
                  memory_observations_enabled=False, memory_workers_enabled=False,
                  memory_skill_synthesis_enabled=False)
    agent_module.refresh_runtime_config(cfg)
    # This parent is deterministic so the diagnostic cannot start unrelated
    # work. The child performs one real gateway call with the selected model.
    parent = ToolModel(responses=[AIMessage(content="", tool_calls=[{
        "name": "task", "id": "model-routing-check", "args": {
            "subagent_type": "general-purpose",
            "description": "Connection test only. Reply exactly OK. Do not call tools or read/write files.",
        }}]), AIMessage(content="Diagnostic completed")])
    stale = ToolModel(responses=[AIMessage(content="STALE_MODEL_USED")])
    subs = [{"name": "general-purpose", "description": "Model check", "system_prompt": "Reply OK without tools.", "tools": [], "model": stale}]
    agent_module._inject_subagent_middleware(subs, cfg=cfg, chat_model=stale, workspace_dir=ROOT)
    graph = create_deep_agent(model=parent, subagents=subs)
    recorder = ModelRecorder()
    result = await asyncio.wait_for(graph.ainvoke(
        {"messages": [HumanMessage(content="Run the connection test")]},
        config={"configurable": {"use_active_model": True}, "recursion_limit": 10, "callbacks": [recorder]},
    ), timeout=150)
    child = next(message for message in result["messages"] if isinstance(message, ToolMessage) and message.name == "task")
    assert child.content and "STALE_MODEL_USED" not in str(child.content), child.content
    assert recorder.models and all(model == cfg.model for model in recorder.models), recorder.models
    report = {"status": "passed", "selected_model": cfg.model, "returned_models": recorder.models,
              "stale_binding_bypassed": True, "child_response": child.content}
    (ROOT / "artifacts/subagent-model-live-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    asyncio.run(main())
