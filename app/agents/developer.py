"""The Developer agent.

The Developer writes Python code that satisfies the task and the Analyst's
plan. On a review iteration it instead receives the current code plus the
Reviewer's findings and produces a corrected version, fixing only the
reported issues.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.graph.state import AgentState
from app.llm.pool import Capability


class CodeFile(BaseModel):
    """A single generated source file.

    Attributes:
        filename: The file name, for example ``bank_account.py``.
        content: The complete source code of the file.
    """

    filename: str = Field(description="The file name, e.g. bank_account.py")
    content: str = Field(description="The complete source code of the file.")


class CodeOutput(BaseModel):
    """The Developer agent's structured output.

    Attributes:
        approach: How the Developer approached the task and its key decisions.
        assumptions: Assumptions made and edge cases the Developer was unsure of.
        files: The generated source files.
        summary: A one-sentence summary of what was built or changed.
    """

    approach: str = Field(
        description="How you approached the task: the design and key decisions."
    )
    assumptions: list[str] = Field(
        description=(
            "Assumptions and decisions you made where the task was ambiguous, "
            "plus any edge cases you were unsure about or did not fully handle."
        )
    )
    files: list[CodeFile] = Field(description="The generated source files.")
    summary: str = Field(description="One-sentence summary of the work.")


class DeveloperAgent(BaseAgent[CodeOutput]):
    """Writes and revises Python code.

    On the first pass the agent works from the task and the Analyst's plan. On
    a review iteration it works from the current code and the Reviewer's
    feedback, applying surgical fixes rather than rewriting working code.
    """

    name = "Developer"
    capability = Capability.CODER
    temperature = 0.2

    def output_schema(self) -> type[CodeOutput]:
        return CodeOutput

    def system_prompt(self) -> str:
        return (
            "You are a senior Python developer on a code development team. "
            "You write clean, correct, fully type-hinted Python code that "
            "follows PEP 8 and uses Google-style docstrings.\n\n"
            "Return your work as structured output:\n"
            "- approach: explain how you approached the task and the key "
            "design decisions you made.\n"
            "- assumptions: list the assumptions and decisions you made where "
            "the task was ambiguous, and honestly note any edge cases you "
            "were unsure about or did not fully handle.\n"
            "- files: the source files, each with a filename and complete "
            "content.\n"
            "- summary: a one-sentence summary.\n\n"
            "Write only the implementation code the task requires. Do not "
            "write test files or test code -- a separate QA agent handles "
            "testing. When you are given issues to fix, change only what the "
            "issues describe and leave working code intact."
        )

    def build_user_message(self, state: AgentState) -> str:
        """Build the prompt, branching between first pass and review iteration."""
        parts = [f"TASK:\n{state['task']}"]

        plan = state.get("plan") or []
        if plan:
            steps = "\n".join(f"{i}. {step}" for i, step in enumerate(plan, 1))
            parts.append(f"IMPLEMENTATION PLAN:\n{steps}")

        rag_context = state.get("rag_context") or []
        if rag_context:
            parts.append(
                "RELEVANT CODING STANDARDS:\n" + "\n---\n".join(rag_context)
            )

        feedback = state.get("review_feedback") or []
        if feedback:
            parts.append(self._review_iteration_section(state, feedback))

        return "\n\n".join(parts)

    @staticmethod
    def _review_iteration_section(state: AgentState, feedback: list) -> str:
        """Build the section shown to the Developer on a review iteration."""
        current_code = state.get("code") or {}
        code_block = "\n\n".join(
            f"# {name}\n{content}" for name, content in current_code.items()
        )
        issues = "\n".join(
            f"- [{item.severity}] {item.issue}"
            + (f"  ->  {item.suggestion}" if item.suggestion else "")
            for item in feedback
        )
        return (
            f"YOUR CURRENT CODE:\n{code_block}\n\n"
            f"ISSUES TO FIX (fix only these; keep working code intact):\n"
            f"{issues}"
        )
