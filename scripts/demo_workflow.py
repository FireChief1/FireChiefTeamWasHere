"""Run the full multi-agent LangGraph workflow on a single task.

    python scripts/demo_workflow.py "Write a Stack class with push and pop"

If no task is given, a default BankAccount task is used.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph.state import AgentState
from app.graph.workflow import build_workflow
from app.history import record_run
from app.llm.pool import get_pool

DEFAULT_TASK = (
    "Write a BankAccount class with deposit and withdraw methods. "
    "Withdraw must reject amounts larger than the balance."
)


async def main(task: str) -> None:
    """Run the workflow end to end and print a summary of the result."""
    pool = get_pool()
    print("warming up the model...\n")
    await pool.warm_up()

    workflow = build_workflow()
    state: AgentState = {
        "task": task,
        "task_id": uuid.uuid4().hex[:8],
        "mode": "generate",
        "iteration": 0,
        "status": "RUNNING",
    }
    print(f"task: {task}")
    print(f"task_id: {state['task_id']}\n")

    result = await workflow.ainvoke(state, config={"recursion_limit": 50})
    record_run(dict(result))

    print("\n" + "=" * 60)
    print(f"STATUS: {result.get('status')}")
    print(f"iterations: {result.get('iteration', 0)}")
    print(f"issue history: {result.get('issue_count_history')}")
    if result.get("node_error"):
        print(f"error: {result['node_error']}")

    plan = result.get("plan") or []
    print(f"\nplan: {len(plan)} step(s)")

    feedback = result.get("review_feedback") or []
    print(f"final review findings: {len(feedback)}")
    for finding in feedback:
        print(f"  [{finding.severity}] {finding.issue}")

    test_results = result.get("test_results")
    if test_results:
        print(f"tests: {test_results.passed} passed, {test_results.failed} failed")

    code = result.get("code") or {}
    print(f"files: {', '.join(code) or '(none)'}")
    print("=" * 60)

    await pool.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TASK))
