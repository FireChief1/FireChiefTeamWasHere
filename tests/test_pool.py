"""Tests for the capability-aware LLM pool."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

import app.llm.pool as pool_module
from app.llm.pool import (
    Capability,
    LLMNode,
    LLMPool,
    NoHealthyNodeError,
    build_default_pool,
)


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


def test_pick_node_does_not_fall_back_for_vision_requests():
    pool = LLMPool(nodes=[_node("fallback", [Capability.FALLBACK])])

    with pytest.raises(NoHealthyNodeError):
        pool.pick_node(Capability.VISION)


def test_pick_node_raises_when_no_node_is_usable():
    pool = LLMPool(nodes=[_node("coder", [Capability.CODER], healthy=False)])
    with pytest.raises(NoHealthyNodeError):
        pool.pick_node(Capability.CODER)


def test_is_degraded_false_when_all_capabilities_are_served():
    pool = LLMPool(
        nodes=[
            _node(
                "mac",
                [
                    Capability.CHAT,
                    Capability.CODER,
                    Capability.REASONER,
                    Capability.FALLBACK,
                ],
            )
        ]
    )
    assert pool.is_degraded is False


def test_is_degraded_true_when_a_capability_has_no_usable_node():
    pool = LLMPool(
        nodes=[
            _node("chat", [Capability.CHAT]),
            _node("coder", [Capability.CODER], healthy=False),
            _node("reasoner", [Capability.REASONER]),
        ]
    )
    assert pool.is_degraded is True


def test_is_degraded_true_when_chat_capability_has_no_usable_node():
    pool = LLMPool(
        nodes=[
            _node("coder", [Capability.CODER]),
            _node("reasoner", [Capability.REASONER]),
        ]
    )

    assert pool.is_degraded is True


def test_is_degraded_ignores_missing_optional_vision_capability():
    pool = LLMPool(
        nodes=[
            _node("chat", [Capability.CHAT]),
            _node("coder", [Capability.CODER]),
            _node("reasoner", [Capability.REASONER]),
        ]
    )

    assert pool.is_degraded is False


class _CountingModel:
    """Fake ChatOllama that counts ainvoke calls."""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages):  # noqa: ANN001 - test stub
        self.calls += 1
        return type("Resp", (), {"content": "ok"})()


async def test_warm_up_runs_once_and_is_idempotent(monkeypatch):
    pool = LLMPool(nodes=[_node("coder", [Capability.CODER])])
    model = _CountingModel()
    monkeypatch.setattr(pool, "_chat_model", lambda node, temperature: model)

    await pool.warm_up()
    await pool.warm_up()
    await pool.warm_up()

    assert model.calls == 1
    assert pool._warmed is True


async def test_warm_up_skips_lazy_nodes():
    pool = LLMPool(nodes=[_node("vision", [Capability.VISION])])
    pool.nodes[0].warm_up = False

    await pool.warm_up()

    assert pool._warmed is True


class _Schema(BaseModel):
    ok: bool = True


class _FlakyStructured:
    """Fake structured runnable: fails on the first ainvoke, then succeeds."""

    def __init__(self) -> None:
        self.calls: list[list] = []

    async def ainvoke(self, messages):  # noqa: ANN001 - test stub
        self.calls.append(list(messages))
        if len(self.calls) == 1:
            raise ValueError("could not coerce to schema")
        return _Schema(ok=True)


class _FakeStructuredModel:
    def __init__(self, structured: _FlakyStructured) -> None:
        self._structured = structured

    def with_structured_output(self, schema):  # noqa: ANN001 - test stub
        return self._structured


async def test_astructured_adds_repair_feedback_on_retry(monkeypatch):
    pool = LLMPool(nodes=[_node("coder", [Capability.CODER])])
    structured = _FlakyStructured()
    monkeypatch.setattr(
        pool, "_chat_model", lambda node, temperature: _FakeStructuredModel(structured)
    )

    async def _instant_sleep(_seconds):  # noqa: ANN001 - avoid real backoff delay
        return None

    monkeypatch.setattr(pool_module.asyncio, "sleep", _instant_sleep)

    result = await pool.astructured(
        [SystemMessage(content="sys"), HumanMessage(content="task")],
        capability=Capability.CODER,
        schema=_Schema,
    )

    assert result.ok is True
    assert len(structured.calls) == 2
    # First attempt: just the two original messages.
    assert len(structured.calls[0]) == 2
    # Retry: original messages plus one grounded repair note referencing the error.
    assert len(structured.calls[1]) == 3
    assert "could not be parsed" in structured.calls[1][-1].content
    assert "could not coerce to schema" in structured.calls[1][-1].content


async def test_ensure_recent_health_throttles_probes(monkeypatch):
    pool = LLMPool(nodes=[_node("coder", [Capability.CODER])])
    calls = {"count": 0}

    async def _fake_probe():
        calls["count"] += 1

    clock = {"now": 1000.0}
    monkeypatch.setattr(pool, "health_check_once", _fake_probe)
    monkeypatch.setattr(pool_module.time, "monotonic", lambda: clock["now"])

    await pool.ensure_recent_health()  # first call probes
    await pool.ensure_recent_health()  # within interval -> skipped
    assert calls["count"] == 1

    clock["now"] += pool.health_interval + 1
    await pool.ensure_recent_health()  # interval elapsed -> probes again
    assert calls["count"] == 2


def test_build_default_pool_splits_chat_from_coder(monkeypatch):
    monkeypatch.setattr(pool_module.settings, "ollama_base_url", "http://localhost:11434")
    monkeypatch.setattr(pool_module.settings, "chat_model", "qwen2.5:14b")
    monkeypatch.setattr(pool_module.settings, "coder_model", "qwen2.5-coder:14b")
    monkeypatch.setattr(pool_module.settings, "reasoner_model", "qwen2.5-coder:14b")
    monkeypatch.setattr(pool_module.settings, "fallback_model", "qwen2.5-coder:14b")
    monkeypatch.setattr(pool_module.settings, "vision_model", "qwen2.5vl:7b")

    pool = build_default_pool()
    nodes_by_model = {node.model: node for node in pool.nodes}

    assert nodes_by_model["qwen2.5:14b"].capabilities == {Capability.CHAT}
    assert nodes_by_model["qwen2.5-coder:14b"].capabilities == {
        Capability.CODER,
        Capability.REASONER,
        Capability.FALLBACK,
    }
    assert nodes_by_model["qwen2.5vl:7b"].capabilities == {Capability.VISION}
    assert nodes_by_model["qwen2.5vl:7b"].warm_up is False


def test_build_default_pool_fallback_is_an_independent_node(monkeypatch):
    monkeypatch.setattr(pool_module.settings, "ollama_base_url", "http://localhost:11434")
    monkeypatch.setattr(pool_module.settings, "chat_model", "qwen2.5:14b")
    monkeypatch.setattr(pool_module.settings, "coder_model", "qwen2.5-coder:14b")
    monkeypatch.setattr(pool_module.settings, "reasoner_model", "qwen2.5-coder:14b")
    monkeypatch.setattr(pool_module.settings, "fallback_model", "qwen2.5:14b")
    monkeypatch.setattr(pool_module.settings, "vision_model", "")

    pool = build_default_pool()
    nodes_by_model = {node.model: node for node in pool.nodes}

    # Fallback rides on the chat node, NOT the coder node, so it survives an
    # open coder circuit.
    assert Capability.FALLBACK in nodes_by_model["qwen2.5:14b"].capabilities
    assert Capability.FALLBACK not in nodes_by_model["qwen2.5-coder:14b"].capabilities


def test_coder_falls_back_to_an_independent_node_when_coder_circuit_opens():
    pool = LLMPool(
        nodes=[
            _node("coder", [Capability.CODER, Capability.REASONER], failures=3),
            _node("chat", [Capability.CHAT, Capability.FALLBACK]),
        ]
    )
    # Coder circuit is open; without an independent fallback node this would
    # raise NoHealthyNodeError.
    assert pool.pick_node(Capability.CODER).name == "chat"
