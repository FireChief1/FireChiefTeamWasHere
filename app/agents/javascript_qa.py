"""Node.js / JavaScript QA agent."""

from __future__ import annotations

from app.agents.qa import QAAgent, QAOutput
from app.graph.state import AgentState


class JavaScriptQAAgent(QAAgent):
    """Writes a Node.js test suite (node:test) for the code under review."""

    name = "JavaScriptQA"

    def output_schema(self) -> type[QAOutput]:
        return QAOutput

    def system_prompt(self) -> str:
        return (
            "You are a QA engineer for Node.js. Given JavaScript code, write a "
            "thorough test file using Node's built-in test runner: import "
            "`test` from `node:test` and `assert` from `node:assert/strict`.\n\n"
            "Import the code under test from its exact relative path, e.g. "
            "`import { add } from './adder.js';`. Test the behavior the task "
            "specifies and the code implements: cover the happy path and edge "
            "cases. Do not test behavior the code does not implement. Every "
            "expected value in an assertion must be correct -- compute it "
            "carefully.\n\n"
            "Return the complete test module in test_code, a test_filename "
            "(it will be saved with a .test.mjs name), and test_cases -- one "
            "short plain-language sentence per test (one entry per test)."
        )

    def build_user_message(self, state: AgentState) -> str:
        code = state.get("code") or {}
        code_block = "\n\n".join(
            f"// {name}\n{content}" for name, content in code.items()
        )
        files = ", ".join(code)
        return (
            f"TASK:\n{state.get('task', '')}\n\n"
            f"CODE UNDER TEST (files: {files}):\n{code_block}"
        )
