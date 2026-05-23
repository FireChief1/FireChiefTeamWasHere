"""Tests for Project Chat action mapping and safety policy."""

from __future__ import annotations

from pathlib import Path

from app.graph.project_actions import (
    ProjectActionDecision,
    action_from_chat_decision,
    detect_read_only_project_action,
    execute_read_only_project_action,
    get_project_action_handler,
    registered_project_actions,
    validate_project_action,
)


def test_project_action_registry_exposes_read_only_handlers():
    actions = set(registered_project_actions())

    assert {"list_folder", "path_info", "read_file"}.issubset(actions)
    assert get_project_action_handler("list_folder") is not None
    assert get_project_action_handler("path_info") is not None
    assert get_project_action_handler("read_file") is not None
    assert get_project_action_handler("missing_action") is None


def test_detect_read_only_project_action_maps_folder_listing(tmp_path: Path):
    action = detect_read_only_project_action(
        "bu klasörde ne dosyalar var",
        str(tmp_path),
    )

    assert action is not None
    assert action.action == "list_folder"
    assert action.read_only is True
    assert action.requires_workflow is False


def test_detect_read_only_project_action_maps_file_inspection(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>Space</h1>", encoding="utf-8")

    action = detect_read_only_project_action(
        "HTML dosyasını açabilir misin?",
        str(tmp_path),
    )

    assert action is not None
    assert action.action == "read_file"
    assert action.target == "index.html"


def test_detect_read_only_project_action_maps_file_path_question(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>Space</h1>", encoding="utf-8")

    action = detect_read_only_project_action(
        "dosya yolu nedir",
        str(tmp_path),
    )

    assert action is not None
    assert action.action == "path_info"
    assert action.target == "index.html"


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
    action = detect_read_only_project_action(
        "HTML dosyası konusu nedir?",
        str(tmp_path),
    )

    assert action is not None
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
    action = detect_read_only_project_action("dosya yolu nedir", str(tmp_path))

    assert action is not None
    response = execute_read_only_project_action(
        action,
        "dosya yolu nedir",
        str(tmp_path),
    )

    assert response is not None
    assert f"`{tmp_path / 'index.html'}`" in response
    assert "Proje içi yol: `index.html`" in response
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
