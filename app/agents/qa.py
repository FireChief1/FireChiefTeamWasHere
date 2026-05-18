"""The QA agent.

The QA agent writes a pytest test suite for the Developer's code. It produces
only the test code; the QA workflow node later runs that suite and records the
results.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.graph.state import AgentState
from app.llm.pool import Capability


class QAOutput(BaseModel):
    """The QA agent's structured output.

    Attributes:
        test_filename: The test file name, e.g. test_bank_account.py.
        test_code: The complete pytest test module.
        summary: A one-sentence summary of what the tests cover.
    """

    test_filename: str = Field(description="Test file name, e.g. test_x.py")
    test_code: str = Field(description="The complete pytest test module.")
    summary: str = Field(description="One-sentence summary of test coverage.")


class QAAgent(BaseAgent[QAOutput]):
    """Writes a pytest test suite for the code under review."""

    name = "QA"
    capability = Capability.REASONER
    temperature = 0.2

    def output_schema(self) -> type[QAOutput]:
        return QAOutput

    def system_prompt(self) -> str:
        return (
            "You are a QA engineer on a code development team. Given Python "
            "code, write a thorough pytest test suite for it.\n\n"
            "Test the behavior the task specifies and the code implements. "
            "Cover the happy path and edge cases (empty, zero, boundary "
            "values). Test an error case only when the code itself raises an "
            "exception for it or the task explicitly requires it -- do not "
            "invent requirements such as type validation that the code does "
            "not implement. Use the Arrange-Act-Assert structure.\n\n"
            "Every expected value in an assertion must be correct for the "
            "task as specified. Compute each expected value carefully and "
            "verify it -- a wrong expected value makes correct code fail. "
            "Name each test accurately for what it checks.\n\n"
            "Return the test file name and its complete content. The test "
            "module must import the code under test by its module name (the "
            "file name without the .py extension)."
        )

    def build_user_message(self, state: AgentState) -> str:
        code = state.get("code") or {}
        code_block = "\n\n".join(
            f"# {name}\n{content}" for name, content in code.items()
        )
        modules = ", ".join(name.removesuffix(".py") for name in code)
        return (
            f"TASK:\n{state['task']}\n\n"
            f"CODE UNDER TEST (modules: {modules}):\n{code_block}"
        )
