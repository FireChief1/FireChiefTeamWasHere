"""Tests for the deterministic Supervisor decision logic."""

from __future__ import annotations

from app.graph.state import AgentState, FeedbackItem, TestResults
from app.graph.supervisor import route_after_supervisor, supervisor_node


def _blocker() -> FeedbackItem:
    return FeedbackItem(severity="BLOCKER", issue="something is broken")


def _failing_tests() -> TestResults:
    return TestResults(passed=0, failed=1, total=1, output="1 failed")


def _minor() -> FeedbackItem:
    return FeedbackItem(severity="MINOR", issue="a small nitpick")


async def test_supervisor_marks_clean_code_as_success():
    state: AgentState = {"review_feedback": [], "iteration": 0}
    update = await supervisor_node(state)
    assert update["status"] == "SUCCESS"


async def test_supervisor_does_not_loop_on_minor_only_findings():
    # MINOR findings alone never trigger a loop; the code is good enough.
    state: AgentState = {"review_feedback": [_minor()], "iteration": 0}
    update = await supervisor_node(state)
    assert update["status"] == "COMPLETED_WITH_WARNINGS"


async def test_supervisor_loops_when_blocker_and_iterations_remain():
    state: AgentState = {"review_feedback": [_blocker()], "iteration": 0}
    update = await supervisor_node(state)
    assert update["status"] == "RUNNING"
    assert update["iteration"] == 1


async def test_supervisor_fails_at_max_iterations_when_tests_fail():
    # A genuine test failure that the loop could not fix is a hard FAILED.
    state: AgentState = {
        "review_feedback": [_blocker()],
        "iteration": 2,
        "issue_count_history": [3, 2],
        "test_results": _failing_tests(),
    }
    update = await supervisor_node(state)
    assert update["status"] == "FAILED"


async def test_supervisor_warns_at_max_iterations_when_tests_pass():
    # Only reviewer judgment is left (no test failure), so keep the best attempt
    # with warnings instead of discarding it.
    state: AgentState = {
        "review_feedback": [_blocker()],
        "iteration": 2,
        "issue_count_history": [3, 2],
    }
    update = await supervisor_node(state)
    assert update["status"] == "COMPLETED_WITH_WARNINGS"


async def test_supervisor_warns_on_no_progress_when_tests_pass():
    # The blocking-issue count did not decrease (1 -> 1). With passing tests the
    # remaining blocker is reviewer judgment, so finish with warnings (preview),
    # not a hard FAILED.
    state: AgentState = {
        "review_feedback": [_blocker()],
        "iteration": 0,
        "issue_count_history": [1],
    }
    update = await supervisor_node(state)
    assert update["status"] == "COMPLETED_WITH_WARNINGS"


async def test_supervisor_fails_on_no_progress_when_tests_fail():
    state: AgentState = {
        "review_feedback": [_blocker()],
        "iteration": 0,
        "issue_count_history": [1],
        "test_results": _failing_tests(),
    }
    update = await supervisor_node(state)
    assert update["status"] == "FAILED"


async def test_supervisor_restores_prior_best_code_when_current_code_is_worse():
    state: AgentState = {
        "review_feedback": [_blocker(), _blocker()],
        "iteration": 1,
        "issue_count_history": [1],
        "best_code": {"best.py": "def ok():\n    return True\n"},
        "code": {"current.py": "def worse():\n    return False\n"},
        "max_iterations": 3,
        "test_results": _failing_tests(),
    }

    update = await supervisor_node(state)

    assert update["status"] == "FAILED"
    assert update["code"] == {"best.py": "def ok():\n    return True\n"}


def test_route_sends_success_to_the_integrator():
    assert route_after_supervisor({"status": "SUCCESS"}) == "integrator"


def test_route_sends_warnings_to_the_integrator():
    assert route_after_supervisor({"status": "COMPLETED_WITH_WARNINGS"}) == "integrator"


def test_route_loops_back_to_developer_on_running():
    assert route_after_supervisor({"status": "RUNNING"}) == "developer"


def test_route_ends_the_workflow_on_failure():
    assert route_after_supervisor({"status": "FAILED"}) == "end"


def test_route_ends_the_workflow_when_aborting():
    state: AgentState = {"should_abort": True, "status": "RUNNING"}
    assert route_after_supervisor(state) == "end"
