"""Tests for compacted semantic Project Mode memory."""

from __future__ import annotations

from pathlib import Path

from app import project_memory
from app.project_memory import (
    RetrievedProjectMemory,
    compact_project_exchange,
    purge_project_memory,
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
    monkeypatch.setattr(
        project_memory, "prune_project_memory_chunks", lambda *_a, **_k: []
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


def test_compact_project_exchange_keeps_conversation_out_of_semantic_index(monkeypatch):
    recorded: list[dict[str, object]] = []
    indexed: list[object] = []

    monkeypatch.setattr(
        project_memory,
        "record_project_memory_chunk",
        lambda **kwargs: (recorded.append(kwargs) or {
            "id": 5,
            "project_id": 1,
            "created_at": "",
            "updated_at": "",
            "kind": kwargs["kind"],
            "content": kwargs["content"],
            "source_event_ids": [],
            "importance": kwargs["importance"],
            "metadata": kwargs["metadata"],
            "active": True,
            "dedupe_key": kwargs["dedupe_key"],
        }),
    )
    monkeypatch.setattr(
        project_memory,
        "index_project_memory_chunk",
        lambda *a, **k: indexed.append(a),
    )
    monkeypatch.setattr(
        project_memory, "prune_project_memory_chunks", lambda *_a, **_k: []
    )

    chunk = compact_project_exchange(
        project_path="/tmp/demo",
        task_id="chat-1",
        user_message="merhaba nasilsin",
        assistant_response="Iyiyim, nasil yardimci olabilirim?",
        metadata={"intent": "conversation", "response_source": "model"},
    )

    # Durably recorded as a low-value conversation chunk...
    assert chunk is not None
    assert recorded[0]["kind"] == "conversation"
    assert recorded[0]["importance"] == 1
    # ...but never indexed into Chroma, so it cannot pollute semantic retrieval.
    assert indexed == []


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


def test_compact_project_exchange_evicts_pruned_vectors(monkeypatch):
    deleted_vector_ids: list[list[str]] = []

    monkeypatch.setattr(
        project_memory,
        "record_project_memory_chunk",
        lambda **kwargs: {
            "id": 99,
            "project_id": 1,
            "created_at": "",
            "updated_at": "",
            "kind": kwargs["kind"],
            "content": kwargs["content"],
            "source_event_ids": [],
            "importance": kwargs["importance"],
            "metadata": kwargs["metadata"],
            "active": True,
            "dedupe_key": kwargs["dedupe_key"],
        },
    )
    monkeypatch.setattr(
        project_memory, "index_project_memory_chunk", lambda *_a, **_k: True
    )
    # Pruning reports two evicted chunk ids; their Chroma vectors must be dropped.
    monkeypatch.setattr(
        project_memory, "prune_project_memory_chunks", lambda *_a, **_k: [3, 7]
    )

    class _FakeCollection:
        def delete(self, ids):  # noqa: ANN001 - test stub
            deleted_vector_ids.append(list(ids))

    monkeypatch.setattr(
        project_memory, "get_project_memory_collection", lambda: _FakeCollection()
    )

    compact_project_exchange(
        project_path="/tmp/demo",
        task_id="task-evict",
        user_message="bir sey yap",
        assistant_response="oldu",
        metadata={"status": "SUCCESS", "task_profile": "python"},
    )

    assert deleted_vector_ids == [["project-memory:3", "project-memory:7"]]


def test_purge_project_memory_deletes_vectors_scoped_by_path(monkeypatch):
    deletes: list[dict[str, object]] = []

    class _FakeCollection:
        def delete(self, where):  # noqa: ANN001 - test stub
            deletes.append(where)

    monkeypatch.setattr(
        project_memory, "get_project_memory_collection", lambda: _FakeCollection()
    )

    assert purge_project_memory("/tmp/demo") is True
    expected = str(Path("/tmp/demo").expanduser().resolve())
    assert deletes == [{"project_path": expected}]


def test_purge_project_memory_is_best_effort_when_chroma_unavailable(monkeypatch):
    def _boom():
        raise RuntimeError("chroma down")

    monkeypatch.setattr(
        project_memory, "get_project_memory_collection", _boom
    )

    assert purge_project_memory("/tmp/demo") is False
