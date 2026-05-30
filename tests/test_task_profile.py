"""Tests for task-profile routing, including the language axis."""

from __future__ import annotations

from app.graph.task_profile import classify_task_profile


def test_router_language_routes_implementation_by_language():
    # The chat router named python and admitted an implementation, so even vague
    # wording routes to the python profile via the language axis.
    profile, _reason = classify_task_profile(
        {
            "task": "sunu yapiver",
            "mode": "project",
            "project_chat_intent": "implementation",
            "project_chat_action": "modify_project",
            "project_chat_language": "python",
        }
    )
    assert profile == "python"


def test_router_language_javascript_routes_to_node_profile():
    profile, _reason = classify_task_profile(
        {
            "task": "bir fonksiyon ekle",
            "mode": "project",
            "project_chat_intent": "implementation",
            "project_chat_language": "javascript",
        }
    )
    assert profile == "node_js"


def test_javascript_with_web_signal_stays_static_web():
    # JS that is really a web page (HTML/CSS context) routes to static_web.
    profile, _reason = classify_task_profile(
        {
            "task": "javascript ile bir landing page yap",
            "mode": "project",
            "project_chat_intent": "implementation",
            "project_chat_language": "javascript",
        }
    )
    assert profile == "static_web"


def test_unknown_router_language_falls_through_to_keyword_logic():
    # csharp has no profile yet, so the language axis does not fire; routing
    # falls back to the existing keyword path (python default here).
    profile, _reason = classify_task_profile(
        {
            "task": "create something",
            "mode": "project",
            "project_chat_intent": "implementation",
            "project_chat_language": "csharp",
        }
    )
    assert profile == "python"


def test_router_language_ignored_without_implementation_signal():
    # A language hint must not override advisory routing when there is no
    # implementation signal.
    profile, _reason = classify_task_profile(
        {
            "task": "projeyi analiz et",
            "mode": "project",
            "project_chat_intent": "project_analysis",
            "project_chat_language": "python",
        }
    )
    assert profile == "project"


def test_existing_behavior_unchanged_without_language():
    # No language field -> identical to the pre-refactor keyword behavior.
    assert classify_task_profile({"task": "build a landing page", "mode": "project"})[0] == "static_web"
    assert classify_task_profile({"task": "write a python class", "mode": "generate"})[0] == "python"
    assert classify_task_profile({"task": "update the README", "mode": "project"})[0] == "docs"
    assert classify_task_profile({"task": "analyze this project", "mode": "project"})[0] == "project"
