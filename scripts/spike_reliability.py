"""Reliability spike: validate structured output and tool calling.

This script answers the project's biggest open risk (Risk B): can the core
model, qwen2.5-coder:14b, reliably produce valid structured output and tool
calls? The whole multi-agent architecture depends on this assumption.

Run from the project root:

    python scripts/spike_reliability.py [trials]

It runs several trials per scenario and prints a success rate. A rate at or
above 80% means the architecture's structured-output approach is sound. A
lower rate means the build should switch to prompt-based parsing instead of
relying on native structured output.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from app.config import settings
from app.llm.pool import Capability, build_default_pool

DEFAULT_TRIALS = 5


# --- Schemas of increasing complexity (mirroring real agent outputs) ---


class PlanOutput(BaseModel):
    """Analyst-style output: an ordered list of implementation steps."""

    steps: list[str] = Field(description="Ordered implementation steps.")


class FeedbackItem(BaseModel):
    """A single review finding."""

    severity: str = Field(description="One of: BLOCKER, MAJOR, MINOR.")
    issue: str = Field(description="Description of the problem.")


class ReviewOutput(BaseModel):
    """Reviewer-style output: a nested list of findings."""

    findings: list[FeedbackItem] = Field(description="All review findings.")


class CodeFile(BaseModel):
    """A single generated source file."""

    filename: str = Field(description="The file name, e.g. calculator.py.")
    content: str = Field(description="The complete source code of the file.")


class CodeOutput(BaseModel):
    """Developer-style output: generated files plus a summary."""

    files: list[CodeFile] = Field(description="The generated source files.")
    summary: str = Field(description="A one-sentence summary of the code.")


# --- Structured-output scenarios ---


async def run_structured_scenario(
    pool: object,
    label: str,
    schema: type[BaseModel],
    system: str,
    user: str,
    validate: callable,
    trials: int,
) -> tuple[int, int]:
    """Run one structured-output scenario `trials` times.

    Returns a (successes, trials) tuple. A trial succeeds only if the call
    returns without error and the result passes the `validate` check.
    """
    print(f"\n[{label}] schema={schema.__name__}")
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    successes = 0
    for i in range(1, trials + 1):
        try:
            result = await pool.astructured(  # type: ignore[attr-defined]
                messages, capability=Capability.CODER, schema=schema
            )
            if validate(result):
                successes += 1
                print(f"  trial {i}: OK")
            else:
                print(f"  trial {i}: FAIL (schema valid but content empty/wrong)")
        except Exception as exc:  # noqa: BLE001 - the spike measures failures
            print(f"  trial {i}: FAIL ({type(exc).__name__}: {exc})")
    print(f"  -> {successes}/{trials}")
    return successes, trials


# --- Tool-calling scenario ---


@tool
def write_file(filename: str, content: str) -> str:
    """Write content to a file in the workspace.

    Args:
        filename: The name of the file to write.
        content: The text content to write into the file.
    """
    return f"wrote {len(content)} chars to {filename}"


async def run_tool_calling_scenario(trials: int) -> tuple[int, int]:
    """Test whether the model emits a valid tool call.

    Returns a (successes, trials) tuple. A trial succeeds if the model
    responds with a well-formed tool call to `write_file`.
    """
    print("\n[tool-calling] write_file")
    model = ChatOllama(
        model=settings.coder_model,
        base_url=settings.ollama_base_url,
        temperature=0.2,
    ).bind_tools([write_file])
    messages = [
        SystemMessage(
            content="You are a developer. Use the write_file tool to save code."
        ),
        HumanMessage(
            content="Write a Python file hello.py that prints 'hello world'."
        ),
    ]
    successes = 0
    for i in range(1, trials + 1):
        try:
            response = await model.ainvoke(messages)
            calls = getattr(response, "tool_calls", [])
            if calls and calls[0].get("name") == "write_file" and calls[0].get("args"):
                successes += 1
                print(f"  trial {i}: OK (args={list(calls[0]['args'].keys())})")
            else:
                print(f"  trial {i}: FAIL (no valid tool call)")
        except Exception as exc:  # noqa: BLE001
            print(f"  trial {i}: FAIL ({type(exc).__name__}: {exc})")
    print(f"  -> {successes}/{trials}")
    return successes, trials


async def main(trials: int) -> None:
    """Run all spike scenarios and print an overall verdict."""
    print(f"=== Reliability spike: {settings.coder_model} ({trials} trials each) ===")
    pool = build_default_pool()
    print("warming up the model (this loads it into memory)...")
    await pool.warm_up()

    results: list[tuple[str, int, int]] = []

    s, t = await run_structured_scenario(
        pool,
        label="simple",
        schema=PlanOutput,
        system="You are a software analyst. Break the task into clear steps.",
        user="Plan the implementation of a function that reverses a string.",
        validate=lambda r: len(r.steps) > 0,
        trials=trials,
    )
    results.append(("structured/simple", s, t))

    s, t = await run_structured_scenario(
        pool,
        label="nested",
        schema=ReviewOutput,
        system="You are a code reviewer. Report findings with a severity.",
        user=(
            "Review this code and report findings:\n"
            "def div(a, b):\n    return a / b"
        ),
        validate=lambda r: len(r.findings) > 0,
        trials=trials,
    )
    results.append(("structured/nested", s, t))

    s, t = await run_structured_scenario(
        pool,
        label="code-gen",
        schema=CodeOutput,
        system="You are a Python developer. Generate complete, working code.",
        user="Write a function that returns the nth Fibonacci number.",
        validate=lambda r: len(r.files) > 0 and bool(r.files[0].content.strip()),
        trials=trials,
    )
    results.append(("structured/code-gen", s, t))

    s, t = await run_tool_calling_scenario(trials)
    results.append(("tool-calling", s, t))

    await pool.aclose()

    print("\n=== SUMMARY ===")
    total_ok = sum(s for _, s, _ in results)
    total = sum(t for _, _, t in results)
    for label, ok, tt in results:
        rate = 100 * ok / tt if tt else 0
        print(f"  {label:24s} {ok}/{tt}  ({rate:.0f}%)")
    overall = 100 * total_ok / total if total else 0
    print(f"  {'OVERALL':24s} {total_ok}/{total}  ({overall:.0f}%)")
    print()
    if overall >= 80:
        print("VERDICT: architecture is sound — proceed with structured output.")
    else:
        print("VERDICT: reliability too low — switch to prompt-based parsing.")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TRIALS
    asyncio.run(main(n))
