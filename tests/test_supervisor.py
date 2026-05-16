"""Tests for the deterministic Supervisor decision logic."""

from __future__ import annotations

from app.graph.state import AgentState, FeedbackItem
from app.graph.supervisor import route_after_supervisor, supervisor_node


def _blocker() -> FeedbackItem:
    return FeedbackItem(severity="BLOCKER", issue="something is broken")


def _minor() -> FeedbackItem:
    return FeedbackItem(severity="MINOR", issue="a small nitpick")


async def test_supervisor_marks_clean_code_as_success():
    state: AgentState = {"review_feedback": [], "iteration": 0}
    update = await supervisor_node(state)
    assert update["status"] == "SUCCESS"


async def test_supervisor_loops_when_blocker_and_iterations_remain():
    state: AgentState = {"review_feedback": [_blocker()], "iteration": 0}
    update = await supervisor_node(state)
    assert update["status"] == "RUNNING"
    assert update["iteration"] == 1


async def test_supervisor_fails_on_blocker_at_max_iterations():
    state: AgentState = {
        "review_feedback": [_blocker()],
        "iteration": 2,
        "issue_count_history": [3, 2],
    }
    update = await supervisor_node(state)
    assert update["status"] == "FAILED"


async def test_supervisor_warns_on_minor_issues_at_max_iterations():
    state: AgentState = {
        "review_feedback": [_minor()],
        "iteration": 2,
        "issue_count_history": [3, 2],
    }
    update = await supervisor_node(state)
    assert update["status"] == "COMPLETED_WITH_WARNINGS"


async def test_supervisor_stops_when_the_loop_makes_no_progress():
    # The issue count did not decrease (2 -> 2), so the loop is abandoned.
    state: AgentState = {
        "review_feedback": [_blocker(), _minor()],
        "iteration": 0,
        "issue_count_history": [2],
    }
    update = await supervisor_node(state)
    assert update["status"] == "FAILED"


def test_route_sends_success_to_the_integrator():
    assert route_after_supervisor({"status": "SUCCESS"}) == "integrator"


def test_route_loops_back_to_developer_on_running():
    assert route_after_supervisor({"status": "RUNNING"}) == "developer"


def test_route_ends_the_workflow_on_failure():
    assert route_after_supervisor({"status": "FAILED"}) == "end"


def test_route_ends_the_workflow_when_aborting():
    state: AgentState = {"should_abort": True, "status": "RUNNING"}
    assert route_after_supervisor(state) == "end"
