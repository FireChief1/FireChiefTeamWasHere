"""The Analyst agent.

The Analyst is the first agent in the workflow. It turns a free-form task
description into a short, ordered plan of concrete implementation steps that
guides the Developer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.graph.state import AgentState
from app.llm.pool import Capability


class PlanOutput(BaseModel):
    """The Analyst agent's structured output.

    Attributes:
        steps: The ordered implementation steps for the Developer to follow.
    """

    steps: list[str] = Field(
        description="Ordered, concrete implementation steps (2-6 items)."
    )


class AnalystAgent(BaseAgent[PlanOutput]):
    """Breaks a task into an ordered implementation plan."""

    name = "Analyst"
    capability = Capability.REASONER
    temperature = 0.3

    def output_schema(self) -> type[PlanOutput]:
        return PlanOutput

    def system_prompt(self) -> str:
        return (
            "You are a software analyst on a code development team. Given a "
            "programming task, break it into a short, ordered list of "
            "concrete implementation steps that will guide a developer.\n\n"
            "Keep the plan focused: 2 to 5 steps, each a single actionable "
            "instruction about the implementation logic. Do not write code "
            "yourself, and do not include steps for creating files, writing "
            "tests, or running code -- a separate QA agent handles testing."
        )

    def build_user_message(self, state: AgentState) -> str:
        parts = [f"TASK:\n{state['task']}"]
        rag_context = state.get("rag_context") or []
        if rag_context:
            parts.append(
                "RELEVANT CODING STANDARDS:\n" + "\n---\n".join(rag_context)
            )
        return "\n\n".join(parts)
