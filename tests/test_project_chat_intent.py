"""Tests for Project Mode chat intent routing."""

from __future__ import annotations

import pytest

from app.graph.project_chat_intent import (
    ProjectChatContext,
    ProjectChatDecision,
    answer_project_chat_direct,
    answer_project_chat_direct_result,
    compose_project_chat_direct_response,
    deterministic_project_chat_decision,
    format_project_chat_route,
    is_direct_model_response_grounded,
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
def test_policy_router_leaves_folder_listing_to_model(message: str):
    decision = deterministic_project_chat_decision(message)

    assert decision is None


@pytest.mark.parametrize(
    "message",
    [
        "HTML dosyasını açabilir misin?",
        "Bu klasör içindeki HTML dosyası konusu nedir",
        "içeriği bana anlat",
    ],
)
def test_policy_router_leaves_file_inspection_to_model(
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

    assert decision is None


def test_policy_router_leaves_path_questions_to_model(tmp_path):
    (tmp_path / "index.html").write_text(
        "<title>Exploring Space</title><h1>Welcome to Space</h1>",
        encoding="utf-8",
    )

    decision = deterministic_project_chat_decision(
        "dosya yolu nedir",
        ProjectChatContext(project_path=str(tmp_path)),
    )

    assert decision is None


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
        ("saat kaç", "status", False),
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
            action={
                "conversation": "direct_chat",
                "help": "direct_chat",
                "status": "project_status",
                "project_analysis": "analyze_project",
                "implementation": "modify_project",
            }.get(intent, "clarify"),  # type: ignore[arg-type]
        )

    decision = await route_project_chat_intent(
        message,
        ProjectChatContext(project_name="demo"),
        model_router=fake_router,
    )

    assert decision.intent == intent
    assert decision.should_run_workflow is should_run
    assert decision.routed_by == "model"


@pytest.mark.parametrize(
    "message,intent,action",
    [
        ("bu klasörde ne dosyalar var", "folder_listing", "list_folder"),
        ("HTML dosyasını açabilir misin?", "file_inspection", "read_file"),
        ("hangi proje içindeyiz", "path_info", "path_info"),
        ("saat kaç", "status", "current_time"),
        ("10-2 sonucu nedir", "conversation", "calculate"),
        ("kaç farklı dilde kod yazabiliyorsun", "help", "assistant_capabilities"),
    ],
)
async def test_project_chat_uses_model_router_for_read_only_actions(
    message: str,
    intent: str,
    action: str,
):
    async def fake_router(
        routed_message: str,
        context: ProjectChatContext,
    ) -> ProjectChatDecision:
        assert routed_message == message
        return ProjectChatDecision(
            intent=intent,  # type: ignore[arg-type]
            should_run_workflow=False,
            confidence=0.9,
            reason="Semantic read-only route.",
            action=action,  # type: ignore[arg-type]
        )

    decision = await route_project_chat_intent(
        message,
        ProjectChatContext(project_name="demo"),
        model_router=fake_router,
    )

    assert decision.intent == intent
    assert decision.action == action
    assert decision.should_run_workflow is False
    assert decision.routed_by == "model"


async def test_project_chat_corrects_arithmetic_misrouted_as_status():
    async def confused_router(
        message: str,
        context: ProjectChatContext,
    ) -> ProjectChatDecision:
        return ProjectChatDecision(
            intent="status",
            should_run_workflow=False,
            confidence=0.91,
            reason="Confused Turkish result with project status.",
            action="project_status",
        )

    decision = await route_project_chat_intent(
        "10-2 sonucu nedir",
        ProjectChatContext(project_name="demo"),
        model_router=confused_router,
    )

    assert decision.intent == "conversation"
    assert decision.action == "calculate"
    assert decision.should_run_workflow is False
    assert decision.routed_by == "fallback"


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


async def test_project_chat_direct_result_reports_model_source():
    async def fake_responder(
        message: str,
        decision: ProjectChatDecision,
        context: ProjectChatContext,
    ) -> str:
        return "İyiyim, buradayım."

    answer = await answer_project_chat_direct_result(
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

    assert answer.response == "İyiyim, buradayım."
    assert answer.response_source == "model"


async def test_project_chat_direct_result_blocks_ungrounded_model_action_claim():
    async def hallucinating_responder(
        message: str,
        decision: ProjectChatDecision,
        context: ProjectChatContext,
    ) -> str:
        assert message == "fenasın başa belasın"
        assert decision.intent == "conversation"
        assert context.last_task == "Yeni bir python dosyası oluştur."
        return (
            "İşte isteğinize göre bir Python dosyası oluşturdum. "
            "Dosya adı `sayici.py`."
        )

    answer = await answer_project_chat_direct_result(
        "fenasın başa belasın",
        ProjectChatDecision(
            intent="conversation",
            should_run_workflow=False,
            confidence=0.92,
            reason="Casual chat.",
        ),
        ProjectChatContext(
            project_name="demo",
            project_path="/tmp/demo",
            last_task="Yeni bir python dosyası oluştur.",
            last_status="SUCCESS",
        ),
        responder=hallucinating_responder,
    )

    assert answer.response_source == "fallback"
    assert "sayici.py" not in answer.response
    assert "dosya oluşturmadım" in answer.response


def test_direct_model_grounding_rejects_unexecuted_work_claims():
    assert not is_direct_model_response_grounded(
        "İşte isteğinize göre bir Python dosyası oluşturdum."
    )
    assert not is_direct_model_response_grounded("I created sayici.py for you.")
    assert is_direct_model_response_grounded("İyiyim, buradayım. Devam edebiliriz.")


async def test_project_chat_direct_result_reports_action_source_for_current_time(
    tmp_path,
):
    async def fail_if_called(
        message: str,
        decision: ProjectChatDecision,
        context: ProjectChatContext,
    ) -> str:
        raise AssertionError("current_time should not call the LLM responder")

    answer = await answer_project_chat_direct_result(
        "saat kaç",
        ProjectChatDecision(
            intent="status",
            should_run_workflow=False,
            confidence=0.92,
            reason="Clock question.",
            action="current_time",
        ),
        ProjectChatContext(project_name="demo", project_path=str(tmp_path)),
        responder=fail_if_called,
    )

    assert "Saat şu anda" in answer.response
    assert "Europe/Istanbul" in answer.response
    assert answer.response_source == "action"


async def test_project_chat_direct_result_reports_action_source_for_calculation(
    tmp_path,
):
    async def fail_if_called(
        message: str,
        decision: ProjectChatDecision,
        context: ProjectChatContext,
    ) -> str:
        raise AssertionError("calculate should not call the LLM responder")

    answer = await answer_project_chat_direct_result(
        "10-2 sonucu nedir",
        ProjectChatDecision(
            intent="conversation",
            should_run_workflow=False,
            confidence=0.92,
            reason="Arithmetic.",
            action="calculate",
        ),
        ProjectChatContext(project_name="demo", project_path=str(tmp_path)),
        responder=fail_if_called,
    )

    assert answer.response == "`10 - 2` sonucu: **8**"
    assert answer.response_source == "action"


async def test_project_chat_direct_result_reports_capabilities_from_action(
    tmp_path,
):
    async def fail_if_called(
        message: str,
        decision: ProjectChatDecision,
        context: ProjectChatContext,
    ) -> str:
        raise AssertionError("capabilities should not call the LLM responder")

    answer = await answer_project_chat_direct_result(
        "kaç farklı dilde kod yazabiliyorsun",
        ProjectChatDecision(
            intent="help",
            should_run_workflow=False,
            confidence=0.92,
            reason="Capability question.",
            action="direct_chat",
        ),
        ProjectChatContext(
            project_name="demo",
            project_path=str(tmp_path),
            stack=("Static HTML",),
        ),
        responder=fail_if_called,
    )

    assert "Sadece HTML ile sınırlı değilim" in answer.response
    assert "Python" in answer.response
    assert answer.response_source == "action"


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


async def test_project_chat_direct_result_reports_fallback_source():
    async def failing_responder(
        message: str,
        decision: ProjectChatDecision,
        context: ProjectChatContext,
    ) -> str:
        raise RuntimeError("responder unavailable")

    answer = await answer_project_chat_direct_result(
        "son durum ne",
        ProjectChatDecision(
            intent="status",
            should_run_workflow=False,
            confidence=0.9,
            reason="Status.",
        ),
        ProjectChatContext(project_name="FinalProject", last_status="SUCCESS"),
        responder=failing_responder,
    )

    assert "FinalProject" in answer.response
    assert answer.response_source == "fallback"


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


def test_project_chat_responder_context_keeps_last_task_out_of_conversation():
    context = ProjectChatContext(
        project_name="demo",
        project_path="/tmp/demo",
        last_task="Yeni bir python dosyası oluştur.",
        last_status="SUCCESS",
        stack=("Python",),
        checkpoint_count=1,
    )

    conversation_context = context.responder_summary("conversation")
    status_context = context.responder_summary("status")

    assert "Yeni bir python dosyası oluştur" not in conversation_context
    assert "Previous run status is history only" in conversation_context
    assert "Yeni bir python dosyası oluştur" in status_context


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
