"""Manual demo: run the Developer agent on a single task.

Run from the project root:

    python scripts/demo_developer.py "Write a Stack class with push and pop"

If no task is given, a default Fibonacci task is used. This exercises the
Developer agent end to end against the live local model.
"""

from __future__ import annotations

import asyncio
import sys

from app.agents.developer import DeveloperAgent
from app.graph.state import AgentState
from app.llm.pool import build_default_pool

DEFAULT_TASK = "Write a function that returns the nth Fibonacci number."


async def main(task: str) -> None:
    """Run the Developer agent once and print its output."""
    pool = build_default_pool()
    print("warming up the model...")
    await pool.warm_up()

    agent = DeveloperAgent(pool)
    state: AgentState = {"task": task, "mode": "generate"}
    print(f"\ntask: {task}\nrunning the Developer agent...\n")
    result = await agent.run(state)

    print(f"=== summary ===\n{result.summary}\n")
    for code_file in result.files:
        print(f"=== {code_file.filename} ===")
        print(code_file.content)
        print()

    await pool.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TASK))
