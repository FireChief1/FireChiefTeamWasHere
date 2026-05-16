"""Verify the Reviewer actually catches real bugs (not a rubber stamp).

Feeds the Reviewer a BankAccount class with a deliberate bug: withdraw does
not check the balance, so the account can go negative. A working Reviewer
must report a BLOCKER finding.

    python scripts/check_reviewer.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.reviewer import ReviewerAgent
from app.graph.state import AgentState
from app.llm.pool import build_default_pool

BUGGY_CODE = '''\
class BankAccount:
    def __init__(self, balance: float = 0.0):
        self.balance = balance

    def deposit(self, amount: float) -> None:
        self.balance += amount

    def withdraw(self, amount: float) -> None:
        # no balance check here
        self.balance -= amount
'''


async def main() -> None:
    """Run the Reviewer on deliberately buggy code and report the verdict."""
    pool = build_default_pool()
    print("warming up the model...\n")
    await pool.warm_up()

    state: AgentState = {
        "task": (
            "Write a BankAccount class with deposit and withdraw methods. "
            "Withdraw must reject amounts larger than the balance."
        ),
        "mode": "review",
        "code": {"bank_account.py": BUGGY_CODE},
    }
    review = await ReviewerAgent(pool).run(state)
    await pool.aclose()

    print(f"Reviewer found {len(review.findings)} finding(s):")
    for finding in review.findings:
        print(f"  [{finding.severity}] {finding.issue}")
        if finding.suggestion:
            print(f"            -> {finding.suggestion}")

    blockers = [f for f in review.findings if f.severity == "BLOCKER"]
    print()
    if blockers:
        print("VERDICT: the Reviewer caught the missing balance check.")
    else:
        print("VERDICT: the Reviewer MISSED the bug — its prompt needs work.")


if __name__ == "__main__":
    asyncio.run(main())
