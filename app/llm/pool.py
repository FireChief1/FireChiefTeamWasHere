"""Capability-aware LLM backend pool.

The pool routes generation requests to healthy LLM nodes based on the
requested capability (chat, coding, reasoning, vision, or fallback). It
provides health checks, a per-node circuit breaker, retry with exponential
backoff, and a graceful degraded mode.

In the single-machine core deployment, configured model tags are grouped into
Ollama nodes by model. Adding worker machines is a configuration change handled
by the pool factory and does not affect any code in this module.
"""

from __future__ import annotations

import asyncio
import time
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

    CHAT = "chat"
    CODER = "coder"
    REASONER = "reasoner"
    VISION = "vision"
    FALLBACK = "fallback"


@dataclass
class LLMNode:
    """A single LLM backend: one model served by one Ollama instance.

    Attributes:
        name: Human-readable identifier, used in logs.
        base_url: The Ollama server URL.
        model: The Ollama model tag served by this node.
        capabilities: The set of capabilities this node can serve.
        warm_up: Whether startup should proactively load the model into memory.
        is_healthy: Reachability state, maintained by the health check.
        failure_count: Consecutive call failures; drives the circuit breaker.
    """

    name: str
    base_url: str
    model: str
    capabilities: set[Capability]
    warm_up: bool = True
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
        self._http_limits = httpx.Limits(
            max_connections=20, max_keepalive_connections=10
        )
        self._http_timeout = httpx.Timeout(
            settings.request_timeout, connect=settings.connect_timeout
        )
        # The local API server runs each request in its own asyncio.run() loop,
        # so the HTTP client is created lazily and rebound whenever the running
        # loop changes. A client bound to a closed loop is unusable.
        self._http: httpx.AsyncClient | None = None
        self._http_loop: asyncio.AbstractEventLoop | None = None
        # Whether the one-time startup warm-up pass has already run.
        self._warmed = False
        # Monotonic timestamp of the last throttled health probe.
        self._last_health_check = 0.0

    def _get_http(self) -> httpx.AsyncClient:
        """Return an HTTP client bound to the running loop.

        Recreates the client whenever the running event loop differs from the
        one the current client was built on, so a persistent pool stays usable
        across the API server's per-request asyncio.run() loops.
        """
        loop = asyncio.get_running_loop()
        if self._http is None or self._http.is_closed or self._http_loop is not loop:
            self._http = httpx.AsyncClient(
                limits=self._http_limits, timeout=self._http_timeout
            )
            self._http_loop = loop
        return self._http

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

        if capability != Capability.VISION:
            fallback = [
                n
                for n in self.nodes
                if Capability.FALLBACK in n.capabilities
                and n.is_usable(self.circuit_threshold)
            ]
            if fallback:
                logger.warning(
                    f"no dedicated node for {capability.value}; using fallback"
                )
                return min(fallback, key=lambda n: n.failure_count)

        raise NoHealthyNodeError(
            f"no healthy node for capability {capability.value}"
        )

    @property
    def is_degraded(self) -> bool:
        """True if a specialized capability has no dedicated usable node."""
        for cap in (Capability.CHAT, Capability.CODER, Capability.REASONER):
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

    async def agenerate_with_image(
        self,
        prompt: str,
        *,
        image_base64: str,
        capability: Capability = Capability.VISION,
        temperature: float = 0.1,
    ) -> str:
        """Generate a text response from one prompt plus one base64 image.

        Ollama's native chat endpoint accepts image payloads as base64 strings.
        This path intentionally bypasses LangChain's text-only structured-output
        helpers so the VISION capability can remain optional and lazy.
        """
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            node = self.pick_node(capability)
            try:
                response = await self._get_http().post(
                    f"{node.base_url}/api/chat",
                    json={
                        "model": node.model,
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt,
                                "images": [image_base64],
                            }
                        ],
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_ctx": settings.llm_num_ctx,
                            "num_predict": settings.llm_num_predict,
                        },
                    },
                )
                response.raise_for_status()
                payload = response.json()
                content = payload.get("message", {}).get("content", "")
                node.failure_count = 0
                return str(content)
            except Exception as exc:  # noqa: BLE001 - failures feed the breaker
                last_error = exc
                node.failure_count += 1
                if node.failure_count >= self.circuit_threshold:
                    logger.error(f"node {node.name} circuit opened")
                logger.warning(
                    f"vision call to {node.name} failed "
                    f"(attempt {attempt + 1}/{self.max_retries}): {exc}"
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(min(2**attempt, 10))
        raise LLMCallError(
            f"all {self.max_retries} attempts failed for {capability.value}"
        ) from last_error

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

        # `work` starts as the caller's messages. On a parse/validation
        # failure the repair hook rewrites it to the original messages plus a
        # single correction note, so the next attempt is grounded in what went
        # wrong instead of blindly resending an identical prompt.
        work: list[BaseMessage] = list(messages)

        async def run(model: ChatOllama) -> T:
            structured = model.with_structured_output(schema)
            result = await structured.ainvoke(work)
            return result  # type: ignore[return-value]

        def repair(exc: Exception) -> None:
            work[:] = [
                *messages,
                HumanMessage(
                    content=(
                        "Your previous reply could not be parsed into the "
                        f"required structured format. Error: {exc}. Reply again "
                        "with ONLY a value that exactly matches the requested "
                        "schema, with no extra prose."
                    )
                ),
            ]

        return await self._execute(capability, temperature, run, on_error=repair)

    async def _execute(
        self,
        capability: Capability,
        temperature: float,
        run: Callable[[ChatOllama], Awaitable[R]],
        *,
        on_error: Callable[[Exception], None] | None = None,
    ) -> R:
        """Run `run` against a picked node, with retry and circuit breaker.

        On each attempt a node is picked fresh, so a failing node is skipped
        once its circuit opens. A successful call resets the node's failure
        count. If `on_error` is given it is invoked after a failed attempt so
        the caller can adjust state (e.g. add repair feedback) before retrying.
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
                    if on_error is not None:
                        on_error(exc)
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
            num_ctx=settings.llm_num_ctx,
            num_predict=settings.llm_num_predict,
        )

    # --- lifecycle ---

    async def warm_up(self) -> None:
        """Load each node's model into memory with a trivial prompt.

        Run once at startup so the first real request does not pay the
        cold-start cost of loading a model into VRAM. Repeated calls are a
        no-op so request handlers never re-warm an already-warm pool.
        """
        if self._warmed:
            return
        for node in self.nodes:
            if not node.warm_up:
                logger.info(f"skipping lazy warm-up for {node.name} ({node.model})")
                continue
            try:
                model = self._chat_model(node, temperature=0.0)
                await model.ainvoke([HumanMessage(content="ok")])
                node.is_healthy = True
                logger.info(f"warmed up {node.name} ({node.model})")
            except Exception as exc:  # noqa: BLE001
                node.is_healthy = False
                logger.error(f"warm-up failed for {node.name}: {exc}")
        self._warmed = True

    async def health_check_once(self) -> None:
        """Probe every node once and update its health state."""
        for node in self.nodes:
            try:
                response = await self._get_http().get(
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
        """Continuously probe node health. Intended to run as a background task.

        Use this only in deployments with a persistent event loop (e.g. the
        Streamlit app). The local API server runs each request in its own
        asyncio.run() loop, so it relies on `ensure_recent_health` instead.
        """
        while True:
            await asyncio.sleep(self.health_interval)
            await self.health_check_once()

    async def ensure_recent_health(self) -> None:
        """Probe node health at most once per `health_interval` seconds.

        Request-driven entry points call this so a node that became unreachable
        (or recovered) is detected without a background loop, while staying
        cheap: repeated calls within the interval are a no-op.
        """
        now = time.monotonic()
        if now - self._last_health_check < self.health_interval:
            return
        self._last_health_check = now
        await self.health_check_once()

    async def aclose(self) -> None:
        """Release the shared HTTP client if one is open."""
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None
        self._http_loop = None


def build_default_pool() -> LLMPool:
    """Build the single-machine core pool from configured capability models.

    Models using the same Ollama URL and tag are grouped into one node with
    multiple capabilities. This keeps the default deployment compact while
    allowing chat/router work to use a general model and code work to use a
    coder-specialized model.

    Returns:
        A pool with the single-machine core configuration.
    """
    grouped: dict[tuple[str, str], LLMNode] = {}
    specs = (
        ("chat", settings.chat_model, Capability.CHAT, True),
        ("coder", settings.coder_model, Capability.CODER, True),
        ("reasoner", settings.reasoner_model, Capability.REASONER, True),
        ("fallback", settings.fallback_model, Capability.FALLBACK, True),
        ("vision", settings.vision_model, Capability.VISION, False),
    )
    for name, model, capability, warm_up in specs:
        if not model:
            continue
        key = (settings.ollama_base_url, model)
        if key not in grouped:
            grouped[key] = LLMNode(
                name=name,
                base_url=settings.ollama_base_url,
                model=model,
                capabilities=set(),
                warm_up=warm_up,
            )
        else:
            grouped[key].name = f"{grouped[key].name}+{name}"
            grouped[key].warm_up = grouped[key].warm_up or warm_up
        grouped[key].capabilities.add(capability)

    return LLMPool(nodes=list(grouped.values()))


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
