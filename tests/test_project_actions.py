"""Tests for Project Chat action mapping and safety policy."""

from __future__ import annotations

from pathlib import Path

from app.graph.project_actions import (
    ProjectActionDecision,
    action_from_chat_decision,
    execute_read_only_project_action,
    get_project_action_handler,
    registered_project_actions,
    validate_project_action,
)


def test_project_action_registry_exposes_read_only_handlers():
    actions = set(registered_project_actions())

    assert {
        "list_folder",
        "path_info",
        "read_file",
        "current_time",
        "calculate",
        "assistant_capabilities",
    }.issubset(actions)
    assert get_project_action_handler("list_folder") is not None
    assert get_project_action_handler("path_info") is not None
    assert get_project_action_handler("read_file") is not None
    assert get_project_action_handler("current_time") is not None
    assert get_project_action_handler("calculate") is not None
    assert get_project_action_handler("assistant_capabilities") is not None
    assert get_project_action_handler("missing_action") is None


def test_action_from_chat_decision_maps_workflow_intent(tmp_path: Path):
    action = action_from_chat_decision(
        message="README dosyasını güncelle",
        intent="implementation",
        should_run_workflow=True,
        confidence=0.9,
        reason="Change request.",
        routed_by="model",
        project_path=str(tmp_path),
    )

    assert action.action == "modify_project"
    assert action.requires_workflow is True
    assert action.read_only is False


def test_action_from_chat_decision_uses_model_selected_action(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>Space</h1>", encoding="utf-8")

    action = action_from_chat_decision(
        message="HTML dosyasını açabilir misin?",
        intent="file_inspection",
        should_run_workflow=False,
        confidence=0.9,
        reason="Model selected read_file.",
        routed_by="model",
        project_path=str(tmp_path),
        action_name="read_file",
    )

    assert action.action == "read_file"
    assert action.target == "index.html"
    assert action.requires_workflow is False
    assert action.read_only is True


def test_action_from_chat_decision_uses_model_action_target(tmp_path: Path):
    nested = tmp_path / "docs"
    nested.mkdir()
    (nested / "note.md").write_text("# Note", encoding="utf-8")

    action = action_from_chat_decision(
        message="note dosyasını oku",
        intent="file_inspection",
        should_run_workflow=False,
        confidence=0.9,
        reason="Model selected read_file target.",
        routed_by="model",
        project_path=str(tmp_path),
        action_name="read_file",
        action_target="docs/note.md",
    )

    assert action.action == "read_file"
    assert action.target == "docs/note.md"
    assert action.safety_status == "allowed"


def test_action_from_chat_decision_reconciles_conflicting_model_action(
    tmp_path: Path,
):
    action = action_from_chat_decision(
        message="README dosyasını güncelle",
        intent="implementation",
        should_run_workflow=True,
        confidence=0.9,
        reason="Model action conflicted with workflow intent.",
        routed_by="model",
        project_path=str(tmp_path),
        action_name="read_file",
    )

    assert action.action == "modify_project"
    assert action.requires_workflow is True
    assert action.read_only is False


def test_execute_current_time_uses_action_executor(tmp_path: Path):
    action = action_from_chat_decision(
        message="saat kaç",
        intent="status",
        should_run_workflow=False,
        confidence=0.98,
        reason="Model selected current_time.",
        routed_by="model",
        project_path=str(tmp_path),
        action_name="current_time",
    )

    response = execute_read_only_project_action(action, "saat kaç", str(tmp_path))

    assert response is not None
    assert "Saat şu anda" in response
    assert "Europe/Istanbul" in response
    assert "Tarih:" in response


def test_execute_calculate_uses_action_executor(tmp_path: Path):
    action = action_from_chat_decision(
        message="10-2 sonucu nedir",
        intent="conversation",
        should_run_workflow=False,
        confidence=0.98,
        reason="Model selected calculate.",
        routed_by="model",
        project_path=str(tmp_path),
        action_name="calculate",
    )

    response = execute_read_only_project_action(action, "10-2 sonucu nedir", str(tmp_path))

    assert response == "`10 - 2` sonucu: **8**"


def test_execute_capabilities_uses_action_executor(tmp_path: Path):
    action = action_from_chat_decision(
        message="kaç farklı dilde kod yazabiliyorsun",
        intent="help",
        should_run_workflow=False,
        confidence=0.9,
        reason="Capability question.",
        routed_by="model",
        project_path=str(tmp_path),
        action_name="direct_chat",
    )

    response = execute_read_only_project_action(action, action.reason, str(tmp_path))

    assert response is not None
    assert "Sadece HTML ile sınırlı değilim" in response
    assert "Python" in response
    assert "HTML/CSS" in response


def test_validate_project_action_blocks_path_escape(tmp_path: Path):
    action = action_from_chat_decision(
        message="secret dosyasını oku",
        intent="file_inspection",
        should_run_workflow=False,
        confidence=0.9,
        reason="Read file.",
        routed_by="model",
        project_path=str(tmp_path),
    )
    action = action.model_copy(update={"target": "../secret.txt"})

    validated = validate_project_action(action, str(tmp_path))

    assert validated.safety_status == "blocked"
    assert "outside" in validated.safety_message


def test_execute_read_only_project_action_summarizes_html(tmp_path: Path):
    (tmp_path / "index.html").write_text(
        "<title>Arabalar</title><h1>Arabalar</h1><p>Spor arabalar.</p>",
        encoding="utf-8",
    )
    action = action_from_chat_decision(
        message="HTML dosyası konusu nedir?",
        intent="file_inspection",
        should_run_workflow=False,
        confidence=0.98,
        reason="Model selected read_file.",
        routed_by="model",
        project_path=str(tmp_path),
        action_name="read_file",
    )

    response = execute_read_only_project_action(
        action,
        "HTML dosyası konusu nedir?",
        str(tmp_path),
    )

    assert response is not None
    assert "Arabalar" in response
    assert "Spor arabalar" in response


def test_execute_path_info_returns_path_without_reading_file(tmp_path: Path):
    (tmp_path / "index.html").write_text(
        "<title>Secret Topic</title><h1>Do not summarize</h1>",
        encoding="utf-8",
    )
    action = action_from_chat_decision(
        message="dosya yolu nedir",
        intent="path_info",
        should_run_workflow=False,
        confidence=0.98,
        reason="Model selected path_info.",
        routed_by="model",
        project_path=str(tmp_path),
        action_name="path_info",
    )

    response = execute_read_only_project_action(
        action,
        "dosya yolu nedir",
        str(tmp_path),
    )

    assert response is not None
    assert f"`{tmp_path / 'index.html'}`" in response
    assert "Proje içi yol: `index.html`" in response
    assert "Secret Topic" not in response


def test_execute_path_info_returns_project_folder_for_current_project_question(
    tmp_path: Path,
):
    (tmp_path / "index.html").write_text(
        "<title>Secret Topic</title><h1>Do not summarize</h1>",
        encoding="utf-8",
    )
    action = action_from_chat_decision(
        message="hangi proje içindeyiz",
        intent="path_info",
        should_run_workflow=False,
        confidence=0.98,
        reason="Model selected project path_info.",
        routed_by="model",
        project_path=str(tmp_path),
        action_name="path_info",
    )

    response = execute_read_only_project_action(
        action,
        "hangi proje içindeyiz",
        str(tmp_path),
    )

    assert response is not None
    assert f"Proje klasörü: `{tmp_path}`" in response
    assert "Secret Topic" not in response


def test_registry_read_file_handler_blocks_large_selected_file(tmp_path: Path):
    large_file = tmp_path / "large.txt"
    large_file.write_text("x" * 200_001, encoding="utf-8")
    action = ProjectActionDecision(
        action="read_file",
        target="large.txt",
        requires_workflow=False,
        read_only=True,
    )

    response = execute_read_only_project_action(
        action,
        "large dosyasını oku",
        str(tmp_path),
    )

    assert response is not None
    assert "too large" in response
