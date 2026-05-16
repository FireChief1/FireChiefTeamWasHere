"""Tests for the node error boundary decorator."""

from __future__ import annotations

from typing import Any

from app.graph.error_boundary import node_error_boundary
from app.graph.state import AgentState


async def test_error_boundary_passes_through_a_successful_node():
    @node_error_boundary
    async def ok_node(state: AgentState) -> dict[str, Any]:
        return {"plan": ["step one"]}

    result = await ok_node({"task": "x"})
    assert result == {"plan": ["step one"]}


async def test_error_boundary_catches_an_exception_and_aborts():
    @node_error_boundary
    async def bad_node(state: AgentState) -> dict[str, Any]:
        raise RuntimeError("boom")

    result = await bad_node({"task": "x"})
    assert result["should_abort"] is True
    assert result["status"] == "FAILED"
    assert "boom" in result["node_error"]


async def test_error_boundary_skips_a_node_when_already_aborting():
    ran = False

    @node_error_boundary
    async def node(state: AgentState) -> dict[str, Any]:
        nonlocal ran
        ran = True
        return {"plan": []}

    result = await node({"task": "x", "should_abort": True})
    assert result == {}
    assert ran is False
