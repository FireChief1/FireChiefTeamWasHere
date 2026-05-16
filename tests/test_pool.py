"""Tests for the capability-aware LLM pool."""

from __future__ import annotations

import pytest

from app.llm.pool import Capability, LLMNode, LLMPool, NoHealthyNodeError


def _node(name, capabilities, *, healthy=True, failures=0):
    """Build an LLMNode for testing."""
    return LLMNode(
        name=name,
        base_url="http://localhost:11434",
        model="test-model",
        capabilities=set(capabilities),
        is_healthy=healthy,
        failure_count=failures,
    )


def test_llmnode_is_usable_when_healthy_and_circuit_closed():
    node = _node("n", [Capability.CODER])
    assert node.is_usable(circuit_threshold=3) is True


def test_llmnode_not_usable_when_unhealthy():
    node = _node("n", [Capability.CODER], healthy=False)
    assert node.is_usable(circuit_threshold=3) is False


def test_llmnode_not_usable_when_circuit_open():
    node = _node("n", [Capability.CODER], failures=3)
    assert node.is_usable(circuit_threshold=3) is False


def test_pool_requires_at_least_one_node():
    with pytest.raises(ValueError):
        LLMPool(nodes=[])


def test_pick_node_returns_a_node_with_the_capability():
    pool = LLMPool(
        nodes=[
            _node("coder", [Capability.CODER]),
            _node("reasoner", [Capability.REASONER]),
        ]
    )
    assert pool.pick_node(Capability.CODER).name == "coder"
    assert pool.pick_node(Capability.REASONER).name == "reasoner"


def test_pick_node_prefers_the_least_failed_candidate():
    pool = LLMPool(
        nodes=[
            _node("busy", [Capability.CODER], failures=2),
            _node("fresh", [Capability.CODER], failures=0),
        ]
    )
    assert pool.pick_node(Capability.CODER).name == "fresh"


def test_pick_node_falls_back_when_the_capability_is_unavailable():
    pool = LLMPool(
        nodes=[
            _node("coder", [Capability.CODER], healthy=False),
            _node("fallback", [Capability.FALLBACK]),
        ]
    )
    assert pool.pick_node(Capability.CODER).name == "fallback"


def test_pick_node_raises_when_no_node_is_usable():
    pool = LLMPool(nodes=[_node("coder", [Capability.CODER], healthy=False)])
    with pytest.raises(NoHealthyNodeError):
        pool.pick_node(Capability.CODER)


def test_is_degraded_false_when_all_capabilities_are_served():
    pool = LLMPool(
        nodes=[
            _node(
                "mac",
                [Capability.CODER, Capability.REASONER, Capability.FALLBACK],
            )
        ]
    )
    assert pool.is_degraded is False


def test_is_degraded_true_when_a_capability_has_no_usable_node():
    pool = LLMPool(
        nodes=[
            _node("coder", [Capability.CODER], healthy=False),
            _node("reasoner", [Capability.REASONER]),
        ]
    )
    assert pool.is_degraded is True
