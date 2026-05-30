"""Tests for compacted semantic Project Mode memory."""

from __future__ import annotations

from app import project_memory
from app.project_memory import (
    RetrievedProjectMemory,
    compact_project_exchange,
    semantic_project_memory_for_prompt,
)


def test_compact_project_exchange_records_and_indexes_memory(monkeypatch):
    recorded: list[dict[str, object]] = []
    indexed: list[tuple[str, dict[str, object]]] = []

    def fake_record_project_memory_chunk(**kwargs):
        recorded.append(kwargs)
        return {
            "id": 42,
            "project_id": 7,
            "created_at": "",
            "updated_at": "",
            "kind": kwargs["kind"],
            "content": kwargs["content"],
            "source_event_ids": [],
            "importance": kwargs["importance"],
            "metadata": kwargs["metadata"],
            "active": True,
            "dedupe_key": kwargs["dedupe_key"],
        }

    def fake_index_project_memory_chunk(project_path, chunk):
        indexed.append((project_path, chunk))
        return True

    monkeypatch.setattr(
        project_memory,
        "record_project_memory_chunk",
        fake_record_project_memory_chunk,
    )
    monkeypatch.setattr(
        project_memory,
        "index_project_memory_chunk",
        fake_index_project_memory_chunk,
    )

    chunk = compact_project_exchange(
        project_path="/tmp/demo",
        task_id="task-1",
        user_message="Python class yaz",
        assistant_response="student_class.py hazır.",
        metadata={
            "intent": "implementation",
            "action": "modify_project",
            "response_source": "workflow",
            "status": "SUCCESS",
            "task_profile": "python",
            "planned_files": ["student_class.py"],
        },
    )

    assert chunk is not None
    assert recorded[0]["kind"] == "task_outcome"
    assert recorded[0]["importance"] == 4
    assert recorded[0]["dedupe_key"] == "exchange:task-1"
    assert "Python class yaz" in str(recorded[0]["content"])
    assert "student_class.py" in str(recorded[0]["content"])
    assert indexed[0][0] == "/tmp/demo"


def test_compact_project_exchange_skips_ephemeral_memory(monkeypatch):
    monkeypatch.setattr(
        project_memory,
        "record_project_memory_chunk",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not record")),
    )

    chunk = compact_project_exchange(
        project_path="/tmp/demo",
        task_id="time",
        user_message="saat kaç",
        assistant_response="Saat 20:00.",
        metadata={"action": "current_time"},
    )

    assert chunk is None


def test_semantic_project_memory_for_prompt_is_bounded(monkeypatch):
    monkeypatch.setattr(
        project_memory,
        "retrieve_project_memory",
        lambda **_kwargs: [
            RetrievedProjectMemory(
                content="Kullanıcı model-first routing tercih ediyor.",
                kind="user_preference",
                importance=5,
                source="1",
            )
        ],
    )

    prompt = semantic_project_memory_for_prompt(
        project_path="/tmp/demo",
        query="hardcoded olmasın",
    )

    assert "Relevant semantic project memory" in prompt
    assert "model-first routing" in prompt
