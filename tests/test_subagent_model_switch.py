"""Exercise model selection through the real synchronous task tool graph."""

from dataclasses import replace

import pytest
from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import imaging_scientist.imaging_scientist as agent_module
from imaging_scientist.config import ImagingScientistConfig
from imaging_scientist.middleware.configurable_model import ConfigurableModelMiddleware


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.parametrize("async_mode", [False, True])
async def test_existing_parent_and_child_follow_model_changes(monkeypatch, tmp_path, async_mode):
    stale = ToolModel(responses=[AIMessage(content="WRONG: boot-time model")])
    cfg = ImagingScientistConfig(
        model="gpt-6-astra", provider="custom-openai",
        memory_profile_enabled=False, memory_observations_enabled=False,
        memory_workers_enabled=False, memory_skill_synthesis_enabled=False,
    )
    monkeypatch.setattr(agent_module, "_config", cfg)
    monkeypatch.setattr(agent_module, "_runtime_config_revision", 0)
    chosen = {}
    for name in ("gpt-6-astra", "next-selected-model"):
        chosen[name] = ToolModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "task", "args": {"subagent_type": "general-purpose", "description": "Return the marker"},
                "id": f"delegate-{name}",
            }]),
            AIMessage(content=f"child used {name}"),
            AIMessage(content=f"parent used {name}"),
        ])
    monkeypatch.setattr("imaging_scientist.llm.get_chat_model", lambda model, provider: chosen[model])
    subs = [{"name": "general-purpose", "description": "Helper", "system_prompt": "Return marker", "tools": []}]
    agent_module._inject_subagent_middleware(subs, cfg=cfg, chat_model=stale, workspace_dir=tmp_path)
    graph = create_deep_agent(model=stale, subagents=subs, middleware=[ConfigurableModelMiddleware()])
    # Reuse the same compiled graph after a selection change: restarting the
    # graph would hide the stale subagent regression.
    for revision, name in enumerate(chosen):
        monkeypatch.setattr(agent_module, "_config", replace(cfg, model=name))
        monkeypatch.setattr(agent_module, "_runtime_config_revision", revision)
        kwargs = {"config": {"configurable": {"use_active_model": True}, "recursion_limit": 12}}
        state = {"messages": [HumanMessage(content="Delegate to the helper")]}
        result = await graph.ainvoke(state, **kwargs) if async_mode else graph.invoke(state, **kwargs)
        child = next(m for m in result["messages"] if isinstance(m, ToolMessage) and m.name == "task")
        assert child.content == f"child used {name}"
        assert result["messages"][-1].content == f"parent used {name}"

