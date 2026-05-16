"""Manual demo: run the full agent pipeline without the LangGraph workflow.

Runs Analyst -> Developer -> Reviewer -> QA in sequence on a single task,
printing each agent's output. This exercises every agent end to end before the
graph is built, so the workflow step starts from a known-good base.

    python scripts/demo_pipeline.py "Write a Stack class with push and pop"
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.analyst import AnalystAgent
from app.agents.developer import DeveloperAgent
from app.agents.qa import QAAgent
from app.agents.reviewer import ReviewerAgent
from app.graph.state import AgentState
from app.llm.pool import build_default_pool

DEFAULT_TASK = (
    "Write a BankAccount class with deposit and withdraw methods. "
    "Withdraw must reject amounts larger than the balance."
)


async def main(task: str) -> None:
    """Run the four agents in sequence and print each result."""
    pool = build_default_pool()
    print("warming up the model...\n")
    await pool.warm_up()

    state: AgentState = {"task": task, "mode": "generate"}
    print(f"task: {task}\n")

    plan = await AnalystAgent(pool).run(state)
    print(f"=== ANALYST: {len(plan.steps)} step(s) ===")
    for i, step in enumerate(plan.steps, 1):
        print(f"  {i}. {step}")
    state["plan"] = plan.steps

    code = await DeveloperAgent(pool).run(state)
    state["code"] = {f.filename: f.content for f in code.files}
    print(f"\n=== DEVELOPER: {code.summary} ===")
    for name in state["code"]:
        print(f"  file: {name}")

    review = await ReviewerAgent(pool).run(state)
    print(f"\n=== REVIEWER: {len(review.findings)} finding(s) ===")
    for finding in review.findings:
        print(f"  [{finding.severity}] {finding.issue}")

    qa = await QAAgent(pool).run(state)
    print(f"\n=== QA: {qa.summary} ===")
    print(f"  test file: {qa.test_filename}")

    await pool.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TASK))
