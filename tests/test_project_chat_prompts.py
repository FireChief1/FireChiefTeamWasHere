"""Prompt contract tests for Project Chat agents."""

from __future__ import annotations

from typing import cast

from app.agents.project_chat_responder import ProjectChatResponderAgent
from app.agents.project_chat_router import ProjectChatRouterAgent
from app.llm.pool import Capability, LLMPool


def test_router_prompt_keeps_semantic_routing_with_model():
    agent = ProjectChatRouterAgent(cast(LLMPool, object()))
    prompt = agent.system_prompt()

    assert agent.capability == Capability.CHAT
    assert "do not rely on exact keywords" in prompt
    assert "concrete product action" in prompt
    assert "Use path_info/action path_info for location questions" in prompt
    assert "Use status/action project_status for progress" in prompt
    assert "Use status/action current_time for clock" in prompt
    assert "Use conversation/action calculate for simple arithmetic" in prompt
    assert "Use help/action assistant_capabilities" in prompt
    assert "terse request that names an artifact to make" in prompt
    assert "Do not downgrade concrete artifact requests to project_analysis" in prompt


def test_responder_prompt_includes_project_identity_context():
    agent = ProjectChatResponderAgent(cast(LLMPool, object()))
    prompt = agent.system_prompt()

    assert agent.capability == Capability.CHAT
    assert "project name and folder path" in prompt
    assert "Do not invent the current time or date" in prompt
    assert "Do not say you inspected files" in prompt
    assert "previous task/status context as history only" in prompt
    assert "not your full ability boundary" in prompt
