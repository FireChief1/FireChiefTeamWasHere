"""Tests for Project Mode chat intent routing."""

from __future__ import annotations

import pytest

from app.graph.project_chat_intent import (
    ProjectChatContext,
    ProjectChatDecision,
    answer_project_chat_direct,
    compose_project_chat_direct_response,
    deterministic_project_chat_decision,
    format_project_chat_route,
    route_project_chat_intent,
)


def test_policy_router_handles_only_empty_messages():
    decision = deterministic_project_chat_decision("   ")

    assert decision is not None
    assert decision.intent == "clarify"
    assert decision.should_run_workflow is False
    assert decision.routed_by == "policy"


@pytest.mark.parametrize(
    "message",
    [
        "bu klasörde ne dosyalar var",
        "bu klaösrde ne dosyaar var",
        "list files in this folder",
    ],
)
def test_policy_router_keeps_folder_listing_out_of_workflow(message: str):
    decision = deterministic_project_chat_decision(message)

    assert decision is not None
    assert decision.intent == "folder_listing"
    assert decision.should_run_workflow is False
    assert decision.routed_by == "policy"


@pytest.mark.parametrize(
    "message",
    [
        "HTML dosyasını açabilir misin?",
        "Bu klasör içindeki HTML dosyası konusu nedir",
        "içeriği bana anlat",
    ],
)
def test_policy_router_keeps_file_inspection_out_of_workflow(
    tmp_path,
    message: str,
):
    (tmp_path / "index.html").write_text(
        "<title>Exploring Space</title><h1>Welcome to Space</h1>",
        encoding="utf-8",
    )

    decision = deterministic_project_chat_decision(
        message,
        ProjectChatContext(project_path=str(tmp_path)),
    )

    assert decision is not None
    assert decision.intent == "file_inspection"
    assert decision.should_run_workflow is False
    assert decision.routed_by == "policy"


def test_policy_router_keeps_path_questions_out_of_file_inspection(tmp_path):
    (tmp_path / "index.html").write_text(
        "<title>Exploring Space</title><h1>Welcome to Space</h1>",
        encoding="utf-8",
    )

    decision = deterministic_project_chat_decision(
        "dosya yolu nedir",
        ProjectChatContext(project_path=str(tmp_path)),
    )

    assert decision is not None
    assert decision.intent == "path_info"
    assert decision.should_run_workflow is False
    assert decision.routed_by == "policy"


def test_policy_router_does_not_block_file_change_tasks():
    decision = deterministic_project_chat_decision("README dosyasını güncelle")

    assert decision is None


@pytest.mark.parametrize(
    "message,intent,should_run",
    [
        ("sen kimsin", "conversation", False),
        ("nasılsın", "conversation", False),
        ("ne yapabiliyorsun?", "help", False),
        ("şu an ne durumdayız?", "status", False),
        ("projeye bir gözatarmısın ne var ne yok", "project_analysis", True),
        ("README dosyasını güncelle", "implementation", True),
    ],
)
async def test_project_chat_v2_uses_model_router_for_natural_language(
    message: str,
    intent: str,
    should_run: bool,
):
    async def fake_router(
        routed_message: str,
        context: ProjectChatContext,
    ) -> ProjectChatDecision:
        assert routed_message == message
        assert context.project_name == "demo"
        return ProjectChatDecision(
            intent=intent,  # type: ignore[arg-type]
            should_run_workflow=should_run,
            confidence=0.88,
            reason="Semantic model route.",
        )

    decision = await route_project_chat_intent(
        message,
        ProjectChatContext(project_name="demo"),
        model_router=fake_router,
    )

    assert decision.intent == intent
    assert decision.should_run_workflow is should_run
    assert decision.routed_by == "model"


async def test_project_chat_normalizes_model_workflow_flag_for_direct_intent():
    async def confused_router(
        message: str,
        context: ProjectChatContext,
    ) -> ProjectChatDecision:
        return ProjectChatDecision(
            intent="conversation",
            should_run_workflow=True,
            confidence=0.91,
            reason="Wrong workflow flag.",
        )

    decision = await route_project_chat_intent(
        "selam",
        ProjectChatContext(),
        model_router=confused_router,
    )

    assert decision.intent == "conversation"
    assert decision.should_run_workflow is False


async def test_project_chat_normalizes_model_workflow_flag_for_workflow_intent():
    async def confused_router(
        message: str,
        context: ProjectChatContext,
    ) -> ProjectChatDecision:
        return ProjectChatDecision(
            intent="project_analysis",
            should_run_workflow=False,
            confidence=0.9,
            reason="Wrong workflow flag.",
        )

    decision = await route_project_chat_intent(
        "projeye bir bak",
        ProjectChatContext(),
        model_router=confused_router,
    )

    assert decision.intent == "project_analysis"
    assert decision.should_run_workflow is True


async def test_project_chat_low_confidence_model_decision_clarifies():
    async def fake_router(
        message: str,
        context: ProjectChatContext,
    ) -> ProjectChatDecision:
        return ProjectChatDecision(
            intent="implementation",
            should_run_workflow=True,
            confidence=0.3,
            reason="Unsure.",
        )

    decision = await route_project_chat_intent(
        "buna bir bakabilir misin",
        ProjectChatContext(),
        model_router=fake_router,
    )

    assert decision.intent == "clarify"
    assert decision.should_run_workflow is False
    assert decision.routed_by == "fallback"


async def test_project_chat_model_failure_clarifies():
    async def failing_router(
        message: str,
        context: ProjectChatContext,
    ) -> ProjectChatDecision:
        raise RuntimeError("router unavailable")

    decision = await route_project_chat_intent(
        "buna bir bakabilir misin",
        ProjectChatContext(),
        model_router=failing_router,
    )

    assert decision.intent == "clarify"
    assert decision.should_run_workflow is False
    assert decision.routed_by == "fallback"
    assert "failed safely" in decision.reason


async def test_project_chat_direct_response_uses_responder_agent():
    async def fake_responder(
        message: str,
        decision: ProjectChatDecision,
        context: ProjectChatContext,
    ) -> str:
        assert message == "nasılsın"
        assert decision.intent == "conversation"
        assert context.project_name == "demo"
        return "İyiyim, buradayım. Projeye birlikte bakabiliriz."

    response = await answer_project_chat_direct(
        "nasılsın",
        ProjectChatDecision(
            intent="conversation",
            should_run_workflow=False,
            confidence=0.92,
            reason="Casual chat.",
        ),
        ProjectChatContext(project_name="demo"),
        responder=fake_responder,
    )

    assert "İyiyim" in response


async def test_project_chat_folder_listing_response_uses_project_path(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Hi</h1>", encoding="utf-8")
    (tmp_path / "assets").mkdir()

    response = await answer_project_chat_direct(
        "bu klasörde ne dosyalar var",
        ProjectChatDecision(
            intent="folder_listing",
            should_run_workflow=False,
            confidence=0.98,
            reason="Read-only listing.",
        ),
        ProjectChatContext(project_name="demo", project_path=str(tmp_path)),
        responder=pytest.fail,
    )

    assert "index.html" in response
    assert "assets/" in response
    assert "Toplam: 2" in response


async def test_project_chat_file_inspection_summarizes_html_file(tmp_path):
    (tmp_path / "index.html").write_text(
        """
        <!doctype html>
        <html>
          <head><title>Exploring Space</title></head>
          <body>
            <h1>Welcome to the World of Space</h1>
            <p>Space is vast and full of wonder.</p>
            <ul><li>Astronomy</li><li>Planets</li></ul>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    response = await answer_project_chat_direct(
        "HTML dosyasının konusu nedir",
        ProjectChatDecision(
            intent="file_inspection",
            should_run_workflow=False,
            confidence=0.98,
            reason="Read-only file inspection.",
        ),
        ProjectChatContext(project_name="demo", project_path=str(tmp_path)),
        responder=pytest.fail,
    )

    assert "index.html" in response
    assert "Exploring Space" in response
    assert "Welcome to the World of Space" in response
    assert "Astronomy" in response


async def test_project_chat_path_info_returns_path_without_file_summary(tmp_path):
    (tmp_path / "index.html").write_text(
        "<title>Exploring Space</title><h1>Welcome to Space</h1>",
        encoding="utf-8",
    )

    response = await answer_project_chat_direct(
        "dosya yolu nedir",
        ProjectChatDecision(
            intent="path_info",
            should_run_workflow=False,
            confidence=0.98,
            reason="Read-only path request.",
        ),
        ProjectChatContext(project_name="demo", project_path=str(tmp_path)),
        responder=pytest.fail,
    )

    assert str(tmp_path / "index.html") in response
    assert "Proje içi yol: `index.html`" in response
    assert "Exploring Space" not in response


async def test_project_chat_direct_response_falls_back_when_responder_fails():
    async def failing_responder(
        message: str,
        decision: ProjectChatDecision,
        context: ProjectChatContext,
    ) -> str:
        raise RuntimeError("responder unavailable")

    response = await answer_project_chat_direct(
        "son durum ne",
        ProjectChatDecision(
            intent="status",
            should_run_workflow=False,
            confidence=0.9,
            reason="Status.",
        ),
        ProjectChatContext(
            project_name="FinalProject",
            project_path="/tmp/final",
            last_task="Refactor nodes.",
            last_status="SUCCESS",
            stack=("Python", "Streamlit"),
            checkpoint_count=3,
        ),
        responder=failing_responder,
    )

    assert "FinalProject" in response
    assert "SUCCESS" in response
    assert "Python, Streamlit" in response


def test_project_chat_status_fallback_uses_context():
    response = compose_project_chat_direct_response(
        ProjectChatDecision(
            intent="status",
            should_run_workflow=False,
            confidence=1.0,
            reason="Status request.",
        ),
        ProjectChatContext(
            project_name="FinalProject",
            project_path="/tmp/final",
            last_task="Refactor nodes.",
            last_status="SUCCESS",
            stack=("Python", "Streamlit"),
            checkpoint_count=3,
        ),
    )

    assert "FinalProject" in response
    assert "SUCCESS" in response
    assert "Python, Streamlit" in response


def test_project_chat_route_label_shows_source_intent_and_confidence():
    label = format_project_chat_route(
        ProjectChatDecision(
            intent="project_analysis",
            should_run_workflow=True,
            confidence=0.842,
            reason="Inspect project.",
            routed_by="model",
        )
    )

    assert label == "model: project_analysis, confidence: 0.84"
