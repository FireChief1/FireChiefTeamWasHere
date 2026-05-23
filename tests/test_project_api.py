"""Tests for the local React UI project API service."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api import project_service
from app.graph.project_chat_intent import ProjectChatContext, ProjectChatDecision


def _project(path: Path) -> dict[str, object]:
    return {
        "id": 1,
        "created_at": "",
        "updated_at": "",
        "last_opened_at": "",
        "name": path.name,
        "path": str(path),
        "project_brief": "",
        "project_stack": ["Python"],
        "project_entrypoints": [],
        "project_test_commands": [],
        "project_risks": [],
        "project_brief_files": [],
        "git_status": "",
        "last_task": "",
        "last_status": "",
    }


@pytest.mark.asyncio
async def test_handle_project_chat_keeps_direct_messages_out_of_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    records: list[tuple[str, str]] = []
    project = _project(tmp_path)

    async def fake_router(
        message: str,
        context: ProjectChatContext,
    ) -> ProjectChatDecision:
        assert message == "nasılsın"
        assert context.project_path == str(tmp_path)
        return ProjectChatDecision(
            intent="conversation",
            should_run_workflow=False,
            confidence=0.92,
            reason="Small talk.",
            routed_by="model",
        )

    async def fake_responder(
        message: str,
        decision: ProjectChatDecision,
        context: ProjectChatContext,
    ) -> str:
        assert decision.intent == "conversation"
        assert context.project_name == tmp_path.name
        return f"İyiyim, proje {context.project_name} açık."

    def fake_record_project_message(**kwargs):
        records.append((kwargs["role"], kwargs["body"]))

    monkeypatch.setattr(project_service, "open_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project_checkpoints", lambda *_args: [])
    monkeypatch.setattr(project_service, "load_project_timeline", lambda *_args: [])
    monkeypatch.setattr(
        project_service,
        "record_project_message",
        fake_record_project_message,
    )
    monkeypatch.setattr(
        project_service,
        "run_project_workflow",
        pytest.fail,
    )

    result = await project_service.handle_project_chat(
        project_path=str(tmp_path),
        message="nasılsın",
        model_router=fake_router,
        direct_responder=fake_responder,
    )

    assert result["ranWorkflow"] is False
    assert result["route"]["intent"] == "conversation"
    assert "İyiyim" in result["assistantResponse"]
    assert records == [
        ("user", "nasılsın"),
        ("assistant", "İyiyim, proje " + tmp_path.name + " açık."),
    ]


@pytest.mark.asyncio
async def test_handle_project_chat_lists_folder_without_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    (tmp_path / "index.html").write_text("<h1>Hi</h1>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    records: list[tuple[str, str]] = []
    project = _project(tmp_path)

    def fake_record_project_message(**kwargs):
        records.append((kwargs["role"], kwargs["body"]))

    monkeypatch.setattr(project_service, "open_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project_checkpoints", lambda *_args: [])
    monkeypatch.setattr(project_service, "load_project_timeline", lambda *_args: [])
    monkeypatch.setattr(
        project_service,
        "record_project_message",
        fake_record_project_message,
    )
    monkeypatch.setattr(project_service, "run_project_workflow", pytest.fail)

    result = await project_service.handle_project_chat(
        project_path=str(tmp_path),
        message="bu klaösrde ne dosyaar var",
    )

    assert result["ranWorkflow"] is False
    assert result["route"]["intent"] == "folder_listing"
    assert result["route"]["action"] == "list_folder"
    assert result["route"]["readOnly"] is True
    assert "index.html" in result["assistantResponse"]
    assert "assets/" in result["assistantResponse"]
    assert records[0] == ("user", "bu klaösrde ne dosyaar var")


@pytest.mark.asyncio
async def test_handle_project_chat_reads_html_file_without_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    (tmp_path / "index.html").write_text(
        "<title>Arabalar</title><h1>Arabalar</h1><p>Spor arabalar.</p>",
        encoding="utf-8",
    )
    project = _project(tmp_path)

    monkeypatch.setattr(project_service, "open_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project_checkpoints", lambda *_args: [])
    monkeypatch.setattr(project_service, "load_project_timeline", lambda *_args: [])
    monkeypatch.setattr(project_service, "record_project_message", lambda **_kwargs: None)
    monkeypatch.setattr(project_service, "run_project_workflow", pytest.fail)

    result = await project_service.handle_project_chat(
        project_path=str(tmp_path),
        message="HTML dosyası konusu nedir?",
    )

    assert result["ranWorkflow"] is False
    assert result["route"]["intent"] == "file_inspection"
    assert result["route"]["action"] == "read_file"
    assert result["route"]["actionTarget"] == "index.html"
    assert "Arabalar" in result["assistantResponse"]
    assert "Spor arabalar" in result["assistantResponse"]


@pytest.mark.asyncio
async def test_handle_project_chat_returns_file_path_without_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    (tmp_path / "index.html").write_text(
        "<title>Arabalar</title><h1>Arabalar</h1>",
        encoding="utf-8",
    )
    project = _project(tmp_path)

    monkeypatch.setattr(project_service, "open_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project_checkpoints", lambda *_args: [])
    monkeypatch.setattr(project_service, "load_project_timeline", lambda *_args: [])
    monkeypatch.setattr(project_service, "record_project_message", lambda **_kwargs: None)
    monkeypatch.setattr(project_service, "run_project_workflow", pytest.fail)

    result = await project_service.handle_project_chat(
        project_path=str(tmp_path),
        message="dosya yolu nedir",
    )

    assert result["ranWorkflow"] is False
    assert result["route"]["intent"] == "path_info"
    assert result["route"]["action"] == "path_info"
    assert result["route"]["actionTarget"] == "index.html"
    assert str(tmp_path / "index.html") in result["assistantResponse"]
    assert "Arabalar" not in result["assistantResponse"]


def test_ensure_project_rejects_missing_path(tmp_path: Path):
    missing = tmp_path / "missing"

    with pytest.raises(project_service.ProjectServiceError, match="does not exist"):
        project_service.ensure_project(str(missing))


def test_project_payload_uses_ui_safe_keys(tmp_path: Path):
    payload = project_service.project_payload(_project(tmp_path))  # type: ignore[arg-type]

    assert payload["name"] == tmp_path.name
    assert payload["path"] == str(tmp_path)
    assert payload["stack"] == ["Python"]
