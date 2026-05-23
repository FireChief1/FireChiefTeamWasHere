"""The Reviewer agent.

The Reviewer inspects the Developer's code for correctness, quality, standards
compliance, and security issues. Findings are returned as a structured list
with severities that the Supervisor uses to decide whether the code needs
another iteration.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.agents.project_context import project_context_section
from app.graph.state import AgentState, FeedbackItem
from app.llm.pool import Capability


class ReviewOutput(BaseModel):
    """The Reviewer agent's structured output.

    Attributes:
        findings: All review findings. An empty list means the code is clean.
    """

    findings: list[FeedbackItem] = Field(
        description="All review findings; empty if the code is clean."
    )


class ReviewerAgent(BaseAgent[ReviewOutput]):
    """Reviews code for correctness, quality, standards, and security."""

    name = "Reviewer"
    capability = Capability.CODER
    temperature = 0.1

    def output_schema(self) -> type[ReviewOutput]:
        return ReviewOutput

    def system_prompt(self) -> str:
        return (
            "You are a senior code reviewer on a code development team. You "
            "inspect Python code for functional correctness against the task, "
            "code quality, complete type hints and docstrings, and security "
            "issues.\n\n"
            "Report findings as a structured list. Each finding has a "
            "severity:\n"
            "- BLOCKER: broken functionality, wrong behavior, or a security hole\n"
            "- MAJOR: a real quality or standards violation\n"
            "- MINOR: a small, optional improvement\n\n"
            "Each finding must be specific and actionable: say what is wrong "
            "and where. If the code is correct and clean, return an empty "
            "findings list. Do not invent problems."
        )

    def build_user_message(self, state: AgentState) -> str:
        parts = [f"TASK:\n{state['task']}"]
        project_context = project_context_section(state)
        if project_context:
            parts.append(project_context)

        plan = state.get("plan") or []
        if plan:
            steps = "\n".join(f"{i}. {step}" for i, step in enumerate(plan, 1))
            parts.append(f"INTENDED PLAN:\n{steps}")

        code = state.get("code") or {}
        code_block = "\n\n".join(
            f"# {name}\n{content}" for name, content in code.items()
        )
        parts.append(f"CODE TO REVIEW:\n{code_block}")

        rag_context = state.get("rag_context") or []
        if rag_context:
            parts.append(
                "REFERENCE -- review standards that may be relevant. Judge "
                "the code against these where they apply; do not raise issues "
                "that are not real problems:\n"
                + "\n---\n".join(rag_context)
            )
        return "\n\n".join(parts)
