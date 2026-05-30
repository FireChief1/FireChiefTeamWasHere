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


def _model_router(
    *,
    intent: str,
    action: str,
    action_target: str = "",
    should_run_workflow: bool = False,
):
    async def fake_router(
        message: str,
        context: ProjectChatContext,
    ) -> ProjectChatDecision:
        return ProjectChatDecision(
            intent=intent,  # type: ignore[arg-type]
            should_run_workflow=should_run_workflow,
            confidence=0.9,
            reason=f"Model selected {action} for: {message}",
            action=action,  # type: ignore[arg-type]
            action_target=action_target,
        )

    return fake_router


@pytest.fixture(autouse=True)
def _disable_semantic_memory_side_effects(monkeypatch: pytest.MonkeyPatch):
    """Keep API service tests focused on routing/workflow behavior."""
    monkeypatch.setattr(
        project_service,
        "semantic_project_memory_for_prompt",
        lambda **_kwargs: "",
    )
    monkeypatch.setattr(
        project_service,
        "compact_project_exchange",
        lambda **_kwargs: None,
    )


def test_list_projects_payload_filters_missing_and_duplicate_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    existing = tmp_path / "existing"
    existing.mkdir()
    missing = tmp_path / "missing"
    first = _project(existing)
    duplicate = {**_project(existing), "id": 2, "name": "Duplicate"}
    stale = {**_project(missing), "id": 3}

    monkeypatch.setattr(
        project_service,
        "load_projects",
        lambda _limit=100: [first, duplicate, stale],
    )
    monkeypatch.setattr(
        project_service,
        "_is_transient_test_project_path",
        lambda _path: False,
    )

    payload = project_service.list_projects_payload()

    assert [item["path"] for item in payload] == [str(existing)]
    assert payload[0]["name"] == existing.name


def test_list_projects_payload_hides_pytest_temp_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    real_project = tmp_path / "real-project"
    real_project.mkdir()
    pytest_project = tmp_path / "pytest-of-user" / "pytest-1" / "chat-project"
    pytest_project.mkdir(parents=True)

    monkeypatch.setattr(
        project_service,
        "load_projects",
        lambda _limit=100: [_project(pytest_project), _project(real_project)],
    )
    monkeypatch.setattr(
        project_service,
        "_is_transient_test_project_path",
        lambda path: "pytest-of-user" in path,
    )

    payload = project_service.list_projects_payload()

    assert [item["path"] for item in payload] == [str(real_project)]


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
    assert result["route"]["responseSource"] == "model"
    assert "İyiyim" in result["assistantResponse"]
    assert records == [
        ("user", "nasılsın"),
        ("assistant", "İyiyim, proje " + tmp_path.name + " açık."),
    ]


@pytest.mark.asyncio
async def test_handle_project_chat_uses_and_compacts_semantic_memory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    project = _project(tmp_path)
    compacted: list[dict[str, object]] = []

    async def fake_router(
        message: str,
        context: ProjectChatContext,
    ) -> ProjectChatDecision:
        assert "model-first routing" in context.semantic_memory
        return ProjectChatDecision(
            intent="conversation",
            should_run_workflow=False,
            confidence=0.9,
            reason="Direct chat.",
            routed_by="model",
        )

    async def fake_responder(
        message: str,
        decision: ProjectChatDecision,
        context: ProjectChatContext,
    ) -> str:
        assert "model-first routing" in context.semantic_memory
        return "Hafızadaki tercihi dikkate aldım."

    monkeypatch.setattr(project_service, "open_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project_checkpoints", lambda *_args: [])
    monkeypatch.setattr(project_service, "load_project_timeline", lambda *_args: [])
    monkeypatch.setattr(project_service, "record_project_message", lambda **_kwargs: None)
    monkeypatch.setattr(project_service, "run_project_workflow", pytest.fail)
    monkeypatch.setattr(
        project_service,
        "semantic_project_memory_for_prompt",
        lambda **_kwargs: (
            "Relevant semantic project memory:\n"
            "- Kullanıcı model-first routing tercih ediyor."
        ),
    )
    monkeypatch.setattr(
        project_service,
        "compact_project_exchange",
        lambda **kwargs: compacted.append(kwargs),
    )

    result = await project_service.handle_project_chat(
        project_path=str(tmp_path),
        message="bunu unutma",
        model_router=fake_router,
        direct_responder=fake_responder,
    )

    assert result["ranWorkflow"] is False
    assert compacted[0]["user_message"] == "bunu unutma"
    assert compacted[0]["metadata"]["response_source"] == "model"


@pytest.mark.asyncio
async def test_handle_project_chat_passes_router_action_to_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    project = _project(tmp_path)
    captured: dict[str, object] = {}

    async def fake_run_project_workflow(**kwargs):
        captured.update(kwargs)
        return {
            "task_id": "task-1",
            "task": kwargs["task"],
            "mode": "project",
            "status": "SUCCESS",
            "task_profile": "python",
            "project_path": str(tmp_path),
            "integration_preview_only": True,
            "integration_planned_files": ["student.py"],
            "integration_target_path": str(tmp_path),
            "code": {"student.py": "class Student:\n    pass\n"},
        }

    async def fake_analyze_image_attachment(**_kwargs):
        return "Screenshot shows a broken submit button."

    monkeypatch.setattr(project_service, "open_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project_checkpoints", lambda *_args: [])
    monkeypatch.setattr(project_service, "load_project_timeline", lambda *_args: [])
    monkeypatch.setattr(project_service, "record_project_message", lambda **_kwargs: None)
    monkeypatch.setattr(project_service, "record_run", lambda _state: None)
    monkeypatch.setattr(project_service, "record_project_checkpoint", lambda _state: None)
    monkeypatch.setattr(project_service, "run_project_workflow", fake_run_project_workflow)
    monkeypatch.setattr(
        project_service,
        "analyze_image_attachment",
        fake_analyze_image_attachment,
    )

    result = await project_service.handle_project_chat(
        project_path=str(tmp_path),
        message="python sınıfı öğrenciler için olsun",
        image_attachment={
            "name": "screen.png",
            "mimeType": "image/png",
            "data": "data:image/png;base64,aGVsbG8=",
        },
        model_router=_model_router(
            intent="implementation",
            action="modify_project",
            should_run_workflow=True,
        ),
    )

    assert result["ranWorkflow"] is True
    assert captured["chat_decision"].intent == "implementation"
    assert captured["chat_action"].action == "modify_project"
    assert captured["vision_context"] == "Screenshot shows a broken submit button."
    assert result["run"]["taskProfile"] == "python"


@pytest.mark.asyncio
async def test_handle_project_chat_uses_vision_without_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    project = _project(tmp_path)
    records: list[tuple[str, str, dict[str, object]]] = []

    def fake_record_project_message(**kwargs):
        records.append((kwargs["role"], kwargs["body"], kwargs["metadata"]))

    async def fake_analyze_image_attachment(**kwargs):
        assert kwargs["image"].name == "screen.png"
        return "Görselde bir hata mesajı ve giriş formu görünüyor."

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
    monkeypatch.setattr(
        project_service,
        "analyze_image_attachment",
        fake_analyze_image_attachment,
    )

    result = await project_service.handle_project_chat(
        project_path=str(tmp_path),
        message="",
        image_attachment={
            "name": "screen.png",
            "mimeType": "image/png",
            "data": "data:image/png;base64,aGVsbG8=",
        },
        model_router=_model_router(intent="conversation", action="direct_chat"),
    )

    assert result["ranWorkflow"] is False
    assert result["route"]["responseSource"] == "vision"
    assert "hata mesajı" in result["assistantResponse"]
    assert records[0][1] == "Bu görseli yorumla."
    assert records[-1][2]["response_source"] == "vision"
    assert records[-1][2]["image_name"] == "screen.png"


@pytest.mark.asyncio
async def test_handle_project_chat_keeps_image_description_direct_when_router_overfires(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    project = _project(tmp_path)

    async def fake_analyze_image_attachment(**kwargs):
        assert kwargs["image"].name == "confusion_matrix.png"
        return "Görselde bir confusion matrix grafiği görünüyor."

    monkeypatch.setattr(project_service, "open_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project_checkpoints", lambda *_args: [])
    monkeypatch.setattr(project_service, "load_project_timeline", lambda *_args: [])
    monkeypatch.setattr(project_service, "record_project_message", lambda **_kwargs: None)
    monkeypatch.setattr(project_service, "run_project_workflow", pytest.fail)
    monkeypatch.setattr(
        project_service,
        "analyze_image_attachment",
        fake_analyze_image_attachment,
    )

    result = await project_service.handle_project_chat(
        project_path=str(tmp_path),
        message="Bu resim nedir bana analiz et",
        image_attachment={
            "name": "confusion_matrix.png",
            "mimeType": "image/png",
            "data": "data:image/png;base64,aGVsbG8=",
        },
        model_router=_model_router(
            intent="implementation",
            action="modify_project",
            should_run_workflow=True,
        ),
    )

    assert result["ranWorkflow"] is False
    assert result["route"]["responseSource"] == "vision"
    assert "confusion matrix" in result["assistantResponse"]


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
        model_router=_model_router(intent="folder_listing", action="list_folder"),
    )

    assert result["ranWorkflow"] is False
    assert result["route"]["intent"] == "folder_listing"
    assert result["route"]["action"] == "list_folder"
    assert result["route"]["readOnly"] is True
    assert result["route"]["responseSource"] == "action"
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
        model_router=_model_router(intent="file_inspection", action="read_file"),
    )

    assert result["ranWorkflow"] is False
    assert result["route"]["intent"] == "file_inspection"
    assert result["route"]["action"] == "read_file"
    assert result["route"]["actionTarget"] == "index.html"
    assert result["route"]["responseSource"] == "action"
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
        model_router=_model_router(intent="path_info", action="path_info"),
    )

    assert result["ranWorkflow"] is False
    assert result["route"]["intent"] == "path_info"
    assert result["route"]["action"] == "path_info"
    assert result["route"]["actionTarget"] == "index.html"
    assert result["route"]["responseSource"] == "action"
    assert str(tmp_path / "index.html") in result["assistantResponse"]
    assert "Arabalar" not in result["assistantResponse"]


@pytest.mark.asyncio
async def test_handle_project_chat_returns_project_path_for_current_project_question(
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
        message="hangi proje içindeyiz",
        model_router=_model_router(intent="path_info", action="path_info"),
    )

    assert result["ranWorkflow"] is False
    assert result["route"]["intent"] == "path_info"
    assert result["route"]["action"] == "path_info"
    assert result["route"]["actionTarget"] == "."
    assert result["route"]["responseSource"] == "action"
    assert f"Proje klasörü: `{tmp_path}`" in result["assistantResponse"]
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


def test_register_pending_project_apply_returns_client_safe_payload(tmp_path: Path):
    state = {
        "mode": "project",
        "status": "SUCCESS",
        "task_id": "apply-token-test",
        "project_path": str(tmp_path),
        "integration_target_path": str(tmp_path),
        "project_mcp_root": str(tmp_path),
        "integration_preview_only": True,
        "integration_planned_files": ["index.html"],
        "integration_file_actions": [{"file": "index.html", "action": "create"}],
        "integration_diff": "--- /dev/null\n+++ index.html\n",
        "code": {"index.html": "<!doctype html>\n"},
    }

    payload = project_service.register_pending_project_apply(state)

    assert payload is not None
    assert payload["taskId"] == "apply-token-test"
    assert payload["targetPath"] == str(tmp_path)
    assert payload["plannedFiles"] == ["index.html"]
    assert "code" not in payload
    assert payload["token"] in project_service._PENDING_PROJECT_APPLIES
    project_service._PENDING_PROJECT_APPLIES.pop(payload["token"], None)


def test_register_pending_project_apply_supersedes_prior_preview(tmp_path: Path):
    project_service._PENDING_PROJECT_APPLIES.clear()
    state = {
        "mode": "project",
        "status": "SUCCESS",
        "task_id": "first",
        "project_path": str(tmp_path),
        "integration_target_path": str(tmp_path),
        "integration_preview_only": True,
        "code": {"index.html": "<!doctype html>\n"},
    }

    first = project_service.register_pending_project_apply(state)
    second = project_service.register_pending_project_apply({**state, "task_id": "second"})

    assert first is not None and second is not None
    # The stale token for the same project is invalidated so it can never
    # write outdated code; only the latest preview survives.
    assert first["token"] not in project_service._PENDING_PROJECT_APPLIES
    assert second["token"] in project_service._PENDING_PROJECT_APPLIES
    project_service._PENDING_PROJECT_APPLIES.clear()


def test_prune_pending_applies_drops_expired_and_caps_size():
    project_service._PENDING_PROJECT_APPLIES.clear()
    for index in range(project_service._MAX_PENDING_APPLIES + 5):
        project_service._PENDING_PROJECT_APPLIES[f"tok-{index}"] = {
            "token": f"tok-{index}",
            "task_id": f"task-{index}",
            "target_path": f"/tmp/project-{index}",
            "mcp_root": "",
            "code": {},
            "planned_files": [],
            "file_actions": [],
            "diff": "",
            "created_at": float(index),
        }

    # now is far beyond the TTL relative to created_at=0..N, so old ones expire.
    project_service._prune_pending_applies(
        now=project_service._PENDING_APPLY_TTL_SECONDS + 1.0
    )

    assert len(project_service._PENDING_PROJECT_APPLIES) <= project_service._MAX_PENDING_APPLIES
    project_service._PENDING_PROJECT_APPLIES.clear()


def test_project_memory_summary_is_length_bounded():
    from app.project_registry import _MAX_MEMORY_SUMMARY_CHARS, project_memory_summary

    project = {
        "id": 1,
        "name": "demo",
        "path": "/tmp/demo",
        "project_brief": "B" * 10_000,
        "project_stack": ["python"],
        "project_entrypoints": [],
        "project_test_commands": [],
        "project_risks": ["R" * 5_000 for _ in range(5)],
        "last_task": "do things",
        "last_status": "SUCCESS",
    }

    summary = project_memory_summary(project, [])  # type: ignore[arg-type]

    # The brief line is clipped to 600 chars, and the whole summary is clamped.
    assert "Last project brief: " + "B" * 600 in summary
    assert "B" * 601 not in summary
    assert len(summary) <= _MAX_MEMORY_SUMMARY_CHARS + 3


def test_clamp_max_iterations_bounds_user_input():
    assert project_service._clamp_max_iterations(3) == 3
    assert project_service._clamp_max_iterations(0) == project_service._MIN_MAX_ITERATIONS
    assert project_service._clamp_max_iterations(-5) == project_service._MIN_MAX_ITERATIONS
    assert project_service._clamp_max_iterations(999) == project_service._MAX_MAX_ITERATIONS


def test_recursion_limit_grows_with_iterations_and_exceeds_node_count():
    for iterations in (1, 3, 10):
        limit = project_service._recursion_limit_for(iterations)
        # Lead nodes (5) + iterations*(dev,rev,qa,sup) + integrator must fit.
        assert limit > 5 + iterations * 4 + 1


def test_run_payload_exposes_developer_diagnostics():
    payload = project_service.run_payload(
        {
            "task_id": "diag",
            "status": "FAILED",
            "task_profile": "python",
            "dev_repair_attempted": True,
            "dev_validation_error": "Developer produced invalid Python.",
            "dev_rejected_code": {"counting.py": "def broken(:\n"},
            "node_error": "developer_node: Developer produced invalid Python.",
        }
    )

    assert payload["devRepairAttempted"] is True
    assert payload["devValidationError"] == "Developer produced invalid Python."
    assert payload["rejectedCode"] == {"counting.py": "def broken(:\n"}
    assert payload["nodeError"] == "developer_node: Developer produced invalid Python."


@pytest.mark.asyncio
async def test_handle_project_apply_writes_pending_preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    token = "apply-token"
    project = _project(tmp_path)
    applied: list[tuple[str, list[str]]] = []

    project_service._PENDING_PROJECT_APPLIES[token] = {
        "token": token,
        "task_id": "task-1",
        "target_path": str(tmp_path),
        "mcp_root": str(tmp_path),
        "code": {"index.html": "<!doctype html>\n"},
        "planned_files": ["index.html"],
        "file_actions": [{"file": "index.html", "action": "create"}],
        "diff": "--- /dev/null\n+++ index.html\n",
    }

    async def fake_apply_project_files(target_path: str, code: dict[str, str]):
        assert target_path == str(tmp_path)
        assert code == {"index.html": "<!doctype html>\n"}
        return {
            "integration_target_path": target_path,
            "project_mcp_root": target_path,
            "integration_written_files": ["index.html"],
        }

    def fake_record_project_apply(**kwargs):
        applied.append((kwargs["task_id"], kwargs["written_files"]))

    monkeypatch.setattr(project_service, "ensure_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project", lambda _path: project)
    monkeypatch.setattr(project_service, "load_project_checkpoints", lambda *_args: [])
    monkeypatch.setattr(project_service, "load_project_timeline", lambda *_args: [])
    monkeypatch.setattr(
        project_service,
        "apply_project_files",
        fake_apply_project_files,
    )
    monkeypatch.setattr(
        project_service,
        "record_project_apply",
        fake_record_project_apply,
    )

    result = await project_service.handle_project_apply(
        project_path=str(tmp_path),
        apply_token=token,
    )

    assert result["apply"]["writtenFiles"] == ["index.html"]
    assert applied == [("task-1", ["index.html"])]
    assert token not in project_service._PENDING_PROJECT_APPLIES
