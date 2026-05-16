"""Tests for the workflow graph structure."""

from __future__ import annotations

from app.graph.workflow import build_workflow


def test_workflow_builds_with_every_expected_node():
    workflow = build_workflow()
    nodes = set(workflow.get_graph().nodes)
    for expected in (
        "rag",
        "analyst",
        "developer",
        "reviewer",
        "qa",
        "supervisor",
        "integrator",
    ):
        assert expected in nodes
