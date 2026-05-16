"""Capability-aware LLM backend pool.

The pool routes generation requests to healthy LLM nodes based on the
requested capability (coding, reasoning, or fallback). It provides health
checks, a per-node circuit breaker, retry with exponential backoff, and a
graceful degraded mode.

In the single-machine core deployment there is one node whose model serves
every capability. Adding worker machines is a configuration change handled by
the pool factory and does not affect any code in this module.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

import httpx
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_ollama import ChatOllama
from loguru import logger
from pydantic import BaseModel

from app.config import settings

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")


class LLMPoolError(Exception):
    """Base exception for LLM pool failures."""


class NoHealthyNodeError(LLMPoolError):
    """Raised when no node can serve a requested capability."""


class LLMCallError(LLMPoolError):
    """Raised when an LLM call fails after all retries are exhausted."""


class Capability(StrEnum):
    """A role-based capability that an LLM node can serve."""

    CODER = "coder"
    REASONER = "reasoner"
    FALLBACK = "fallback"


@dataclass
class LLMNode:
    """A single LLM backend: one model served by one Ollama instance.

    Attributes:
        name: Human-readable identifier, used in logs.
        base_url: The Ollama server URL.
        model: The Ollama model tag served by this node.
        capabilities: The set of capabilities this node can serve.
        is_healthy: Reachability state, maintained by the health check.
        failure_count: Consecutive call failures; drives the circuit breaker.
    """

    name: str
    base_url: str
    model: str
    capabilities: set[Capability]
    is_healthy: bool = True
    failure_count: int = 0

    def is_usable(self, circuit_threshold: int) -> bool:
        """Return True if the node is reachable and its circuit is closed."""
        return self.is_healthy and self.failure_count < circuit_threshold


class LLMPool:
    """Routes LLM requests to healthy nodes by capability.

    Args:
        nodes: The LLM nodes to register. Must contain at least one node.
    """

    def __init__(self, nodes: list[LLMNode]) -> None:
        if not nodes:
            raise ValueError("LLMPool requires at least one node")
        self.nodes = nodes
        self.circuit_threshold = settings.circuit_breaker_threshold
        self.max_retries = settings.max_retries
        self.health_interval = settings.health_check_interval
        self._http = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            timeout=httpx.Timeout(
                settings.request_timeout, connect=settings.connect_timeout
            ),
        )

    # --- node selection ---

    def pick_node(self, capability: Capability) -> LLMNode:
        """Select a usable node for the given capability.

        Prefers a node that natively serves the capability. Falls back to any
        node that serves FALLBACK if no dedicated node is available.

        Args:
            capability: The capability the caller needs.

        Returns:
            The least-failed usable node for the capability.

        Raises:
            NoHealthyNodeError: If no node can serve the request at all.
        """
        candidates = [
            n
            for n in self.nodes
            if capability in n.capabilities and n.is_usable(self.circuit_threshold)
        ]
        if candidates:
            return min(candidates, key=lambda n: n.failure_count)

        fallback = [
            n
            for n in self.nodes
            if Capability.FALLBACK in n.capabilities
            and n.is_usable(self.circuit_threshold)
        ]
        if fallback:
            logger.warning(f"no dedicated node for {capability.value}; using fallback")
            return min(fallback, key=lambda n: n.failure_count)

        raise NoHealthyNodeError(
            f"no healthy node for capability {capability.value}"
        )

    @property
    def is_degraded(self) -> bool:
        """True if a specialized capability has no dedicated usable node."""
        for cap in (Capability.CODER, Capability.REASONER):
            served = any(
                cap in n.capabilities and n.is_usable(self.circuit_threshold)
                for n in self.nodes
            )
            if not served:
                return True
        return False

    # --- generation ---

    async def agenerate(
        self,
        messages: list[BaseMessage],
        *,
        capability: Capability,
        temperature: float = 0.2,
    ) -> str:
        """Generate a plain-text completion for the given messages.

        Args:
            messages: The conversation to send to the model.
            capability: The capability required for this request.
            temperature: Sampling temperature.

        Returns:
            The model's text response.

        Raises:
            LLMCallError: If the call fails after all retries.
            NoHealthyNodeError: If no node can serve the capability.
        """

        async def run(model: ChatOllama) -> str:
            response = await model.ainvoke(messages)
            return str(response.content)

        return await self._execute(capability, temperature, run)

    async def astructured(
        self,
        messages: list[BaseMessage],
        *,
        capability: Capability,
        schema: type[T],
        temperature: float = 0.2,
    ) -> T:
        """Generate a response validated against a Pydantic schema.

        Args:
            messages: The conversation to send to the model.
            capability: The capability required for this request.
            schema: The Pydantic model the response must conform to.
            temperature: Sampling temperature.

        Returns:
            An instance of `schema` populated by the model.

        Raises:
            LLMCallError: If the call fails after all retries.
            NoHealthyNodeError: If no node can serve the capability.
        """

        async def run(model: ChatOllama) -> T:
            structured = model.with_structured_output(schema)
            result = await structured.ainvoke(messages)
            return result  # type: ignore[return-value]

        return await self._execute(capability, temperature, run)

    async def _execute(
        self,
        capability: Capability,
        temperature: float,
        run: Callable[[ChatOllama], Awaitable[R]],
    ) -> R:
        """Run `run` against a picked node, with retry and circuit breaker.

        On each attempt a node is picked fresh, so a failing node is skipped
        once its circuit opens. A successful call resets the node's failure
        count.
        """
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            node = self.pick_node(capability)
            model = self._chat_model(node, temperature)
            try:
                result = await run(model)
                node.failure_count = 0
                return result
            except Exception as exc:  # noqa: BLE001 - failures feed the breaker
                last_error = exc
                node.failure_count += 1
                if node.failure_count >= self.circuit_threshold:
                    logger.error(f"node {node.name} circuit opened")
                logger.warning(
                    f"call to {node.name} failed "
                    f"(attempt {attempt + 1}/{self.max_retries}): {exc}"
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(min(2**attempt, 10))
        raise LLMCallError(
            f"all {self.max_retries} attempts failed for {capability.value}"
        ) from last_error

    def _chat_model(self, node: LLMNode, temperature: float) -> ChatOllama:
        """Build a ChatOllama client configured for the given node."""
        return ChatOllama(
            model=node.model,
            base_url=node.base_url,
            temperature=temperature,
        )

    # --- lifecycle ---

    async def warm_up(self) -> None:
        """Load each node's model into memory with a trivial prompt.

        Run once at startup so the first real request does not pay the
        cold-start cost of loading a model into VRAM.
        """
        for node in self.nodes:
            try:
                model = self._chat_model(node, temperature=0.0)
                await model.ainvoke([HumanMessage(content="ok")])
                node.is_healthy = True
                logger.info(f"warmed up {node.name} ({node.model})")
            except Exception as exc:  # noqa: BLE001
                node.is_healthy = False
                logger.error(f"warm-up failed for {node.name}: {exc}")

    async def health_check_once(self) -> None:
        """Probe every node once and update its health state."""
        for node in self.nodes:
            try:
                response = await self._http.get(
                    f"{node.base_url}/api/tags", timeout=3.0
                )
                response.raise_for_status()
                if not node.is_healthy:
                    logger.info(f"node {node.name} recovered")
                node.is_healthy = True
                node.failure_count = 0
            except Exception:  # noqa: BLE001
                if node.is_healthy:
                    logger.warning(f"node {node.name} is unreachable")
                node.is_healthy = False

    async def run_health_loop(self) -> None:
        """Continuously probe node health. Intended to run as a background task."""
        while True:
            await asyncio.sleep(self.health_interval)
            await self.health_check_once()

    async def aclose(self) -> None:
        """Release the shared HTTP client."""
        await self._http.aclose()


def build_default_pool() -> LLMPool:
    """Build the single-machine core pool.

    One node runs the coder model and serves every capability. To scale out,
    add worker nodes here with dedicated capabilities; no other code in the
    system needs to change.

    Returns:
        A pool with the single-machine core configuration.
    """
    core_node = LLMNode(
        name="mac",
        base_url=settings.ollama_base_url,
        model=settings.coder_model,
        capabilities={Capability.CODER, Capability.REASONER, Capability.FALLBACK},
    )
    return LLMPool(nodes=[core_node])


_pool: LLMPool | None = None


def get_pool() -> LLMPool:
    """Return the process-wide LLM pool, building it on first use."""
    global _pool
    if _pool is None:
        _pool = build_default_pool()
    return _pool


def set_pool(pool: LLMPool) -> None:
    """Replace the process-wide pool. Intended for tests."""
    global _pool
    _pool = pool
