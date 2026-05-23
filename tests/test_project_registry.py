"""Tests for the Postgres-backed project registry."""

from __future__ import annotations

import psycopg
import pytest

from app.config import settings
from app.graph.state import TestResults as WorkflowTestResults
from app.project_registry import (
    delete_project,
    load_project,
    load_project_checkpoints,
    load_project_timeline,
    open_project,
    project_memory_summary,
    record_project_apply,
    record_project_checkpoint,
    record_project_message,
    rename_project,
)


def _postgres_available() -> bool:
    """Return True if the project registry database can be reached."""
    try:
        psycopg.connect(settings.database_url, connect_timeout=3).close()
    except psycopg.Error:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _postgres_available(), reason="Postgres database is not reachable"
)


def test_project_registry_records_project_checkpoint(tmp_path):
    project_path = tmp_path / "demo-project"
    project_path.mkdir()

    project = open_project(project_path)

    assert project is not None
    assert project["path"] == str(project_path.resolve())

    record_project_checkpoint(
        {
            "mode": "project",
            "project_path": str(project_path),
            "task_id": "registry-test",
            "task": "Stabilize Project Mode",
            "status": "SUCCESS",
            "task_profile": "project",
            "project_summary": "Scanned files.",
            "project_brief": "Project brief for demo.",
            "project_stack": ["Python", "Streamlit"],
            "project_entrypoints": ["streamlit run app/ui/streamlit_app.py"],
            "project_test_commands": ["python -m pytest"],
            "project_risks": ["dirty git tree"],
            "project_brief_files": ["pyproject.toml"],
            "project_git_status": "## main\n",
            "integration_planned_files": ["index.html"],
            "integration_written_files": [],
            "integration_preview_only": True,
            "integration_diff": "--- index.html\n+++ index.html\n",
            "test_results": WorkflowTestResults(passed=2, failed=0, total=2),
        }
    )

    updated = load_project(project_path)
    checkpoints = load_project_checkpoints(project_path, limit=5)
    timeline = load_project_timeline(project_path, limit=5)
    memory = project_memory_summary(updated, checkpoints, timeline)

    assert updated is not None
    assert updated["project_stack"] == ["Python", "Streamlit"]
    assert updated["project_test_commands"] == ["python -m pytest"]
    assert checkpoints[0]["task"] == "Stabilize Project Mode"
    assert checkpoints[0]["integration_preview_only"] is True
    assert timeline[0]["kind"] == "checkpoint"
    assert timeline[0]["metadata"]["task_id"] == "registry-test"
    assert "Recent checkpoints" in memory
    assert "Recent timeline" in memory
    assert "Stabilize Project Mode" in memory


def test_project_registry_records_project_apply_event(tmp_path):
    project_path = tmp_path / "apply-project"
    project_path.mkdir()
    assert open_project(project_path) is not None

    record_project_checkpoint(
        {
            "mode": "project",
            "project_path": str(project_path),
            "task_id": "apply-test",
            "task": "Create a static page",
            "status": "SUCCESS",
            "task_profile": "static_web",
            "project_summary": "Scanned files.",
            "project_brief": "Project brief for apply test.",
            "integration_planned_files": ["index.html"],
            "integration_written_files": [],
            "integration_preview_only": True,
            "test_results": WorkflowTestResults(passed=4, failed=0, total=4),
        }
    )

    record_project_apply(
        project_path=project_path,
        task_id="apply-test",
        written_files=["index.html"],
    )

    checkpoints = load_project_checkpoints(project_path, limit=5)
    timeline = load_project_timeline(project_path, limit=5)

    assert checkpoints[0]["written_files"] == ["index.html"]
    assert checkpoints[0]["integration_preview_only"] is False
    assert timeline[0]["kind"] == "project_apply"
    assert timeline[0]["metadata"]["written_files"] == ["index.html"]


def test_project_registry_records_project_conversation_messages(tmp_path):
    project_path = tmp_path / "chat-project"
    project_path.mkdir()
    assert open_project(project_path) is not None

    record_project_message(
        project_path=project_path,
        role="user",
        body="Bu projeyi Codex gibi incele.",
        task_id="chat-test",
    )
    record_project_message(
        project_path=project_path,
        role="assistant",
        body="Projeyi okudum ve güvenli sonraki adımı çıkardım.",
        task_id="chat-test",
        metadata={"status": "SUCCESS"},
    )

    timeline = load_project_timeline(project_path, limit=5)
    memory = project_memory_summary(load_project(project_path), [], timeline)

    assert timeline[0]["kind"] == "assistant_message"
    assert timeline[0]["metadata"]["role"] == "assistant"
    assert timeline[0]["metadata"]["status"] == "SUCCESS"
    assert timeline[1]["kind"] == "user_message"
    assert timeline[1]["metadata"]["task_id"] == "chat-test"
    assert "Bu projeyi Codex gibi incele." in memory
    assert "Projeyi okudum" in memory


def test_project_registry_renames_and_deletes_project(tmp_path):
    project_path = tmp_path / "renamed-project"
    project_path.mkdir()
    assert open_project(project_path) is not None

    renamed = rename_project(project_path, "Readable Project")

    assert renamed is not None
    assert renamed["name"] == "Readable Project"
    assert load_project_timeline(project_path, limit=5)[0]["kind"] == "project_renamed"
    assert delete_project(project_path) is True
    assert load_project(project_path) is None
