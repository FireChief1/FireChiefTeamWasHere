"""Base class for all LLM agents.

An agent is a persona layered over the shared LLM pool. Every agent shares the
same machinery — build a system and user message, call the pool for structured
output, return a validated result — and differs only in its persona, the user
message it constructs from the workflow state, and its output schema.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

from app.graph.state import AgentState
from app.llm.pool import Capability, LLMPool

T = TypeVar("T", bound=BaseModel)


class BaseAgent(ABC, Generic[T]):
    """Shared behavior for every agent in the system.

    Subclasses define four things: the persona (`system_prompt`), how to build
    the user message from state (`build_user_message`), the structured output
    schema (`output_schema`), and which pool capability they require.

    Args:
        pool: The shared LLM pool used for every generation call.
    """

    #: Short human-readable name, used in logs and the UI.
    name: str = "agent"
    #: The pool capability this agent requires.
    capability: Capability = Capability.REASONER
    #: Sampling temperature for this agent's calls.
    temperature: float = 0.2

    def __init__(self, pool: LLMPool) -> None:
        self.pool = pool

    @abstractmethod
    def system_prompt(self) -> str:
        """Return the agent's persona as a system prompt."""

    @abstractmethod
    def build_user_message(self, state: AgentState) -> str:
        """Build the user message for this agent from the workflow state.

        Args:
            state: The current workflow state.

        Returns:
            The user message text to send to the model.
        """

    @abstractmethod
    def output_schema(self) -> type[T]:
        """Return the Pydantic schema the agent's output must conform to."""

    async def run(self, state: AgentState) -> T:
        """Run the agent against the current workflow state.

        Builds the system and user messages, calls the LLM pool for structured
        output, and returns the validated result.

        Args:
            state: The current workflow state.

        Returns:
            The agent's structured output, validated against `output_schema`.

        Raises:
            LLMCallError: If the LLM call fails after all retries.
            NoHealthyNodeError: If no node can serve the agent's capability.
        """
        messages = [
            SystemMessage(content=self.system_prompt()),
            HumanMessage(content=self.build_user_message(state)),
        ]
        logger.info(f"[{self.name}] running (capability={self.capability.value})")
        result = await self.pool.astructured(
            messages,
            capability=self.capability,
            schema=self.output_schema(),
            temperature=self.temperature,
            prefer_backend=state.get("code_backend") or None,
        )
        logger.info(f"[{self.name}] complete")
        return result
