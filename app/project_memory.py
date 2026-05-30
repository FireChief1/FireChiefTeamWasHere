"""Compacted semantic memory for Project Mode.

Postgres remains the durable source of truth for memory chunks. ChromaDB is a
secondary semantic index that can be rebuilt or ignored when unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from app.project_registry import (
    ProjectMemoryChunk,
    record_project_memory_chunk,
)
from app.rag.store import get_embeddings, get_project_memory_collection

_MAX_MEMORY_CONTENT_CHARS = 1800
_MAX_PROMPT_MEMORY_CHARS = 2200


@dataclass(frozen=True)
class RetrievedProjectMemory:
    """One semantically retrieved project memory item."""

    content: str
    kind: str
    importance: int
    source: str


def compact_project_exchange(
    *,
    project_path: str,
    task_id: str,
    user_message: str,
    assistant_response: str,
    metadata: dict[str, object] | None = None,
) -> ProjectMemoryChunk | None:
    """Compact one user/assistant exchange into durable project memory."""
    clean_user = user_message.strip()
    clean_assistant = assistant_response.strip()
    if not clean_user or not clean_assistant:
        return None

    route_metadata = dict(metadata or {})
    kind = _kind_from_metadata(route_metadata)
    if kind == "ephemeral":
        return None
    importance = _importance_from_metadata(route_metadata)
    content = _compact_exchange_text(
        user_message=clean_user,
        assistant_response=clean_assistant,
        metadata=route_metadata,
    )
    chunk = record_project_memory_chunk(
        project_path=project_path,
        kind=kind,
        content=content,
        source_event_ids=[],
        importance=importance,
        metadata=route_metadata,
        dedupe_key=f"exchange:{task_id}" if task_id else "",
    )
    if chunk is not None:
        index_project_memory_chunk(project_path, chunk)
    return chunk


def index_project_memory_chunk(
    project_path: str,
    chunk: ProjectMemoryChunk,
) -> bool:
    """Index a project memory chunk into Chroma for semantic retrieval."""
    try:
        collection = get_project_memory_collection()
        vector = get_embeddings().embed_query(chunk["content"])
        collection.upsert(
            ids=[_vector_id(chunk)],
            documents=[chunk["content"]],
            embeddings=[vector],
            metadatas=[
                {
                    "project_path": str(Path(project_path).expanduser().resolve()),
                    "kind": chunk["kind"],
                    "importance": str(chunk["importance"]),
                    "memory_id": str(chunk["id"]),
                    "dedupe_key": chunk["dedupe_key"],
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001 - memory indexing is non-critical
        logger.warning(f"project memory semantic indexing unavailable: {exc}")
        return False
    return True


def retrieve_project_memory(
    *,
    project_path: str,
    query: str,
    k: int = 5,
) -> list[RetrievedProjectMemory]:
    """Retrieve semantically relevant memory chunks for one project."""
    clean_query = query.strip()
    if not clean_query:
        return []

    resolved_path = str(Path(project_path).expanduser().resolve())
    try:
        collection = get_project_memory_collection()
        if collection.count() == 0:
            return []
        query_vector = get_embeddings().embed_query(clean_query)
        result = collection.query(
            query_embeddings=[query_vector],
            n_results=k,
            where={"project_path": resolved_path},
        )
    except Exception as exc:  # noqa: BLE001 - memory retrieval is optional
        logger.warning(f"project memory retrieval unavailable: {exc}")
        return []

    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    memories: list[RetrievedProjectMemory] = []
    for document, metadata in zip(documents, metadatas, strict=False):
        meta = metadata or {}
        memories.append(
            RetrievedProjectMemory(
                content=str(document),
                kind=str(meta.get("kind") or "memory"),
                importance=_safe_int(meta.get("importance"), default=1),
                source=str(meta.get("memory_id") or ""),
            )
        )
    return memories


def semantic_project_memory_for_prompt(
    *,
    project_path: str,
    query: str,
    k: int = 5,
) -> str:
    """Return a bounded prompt section with relevant semantic project memory."""
    memories = retrieve_project_memory(project_path=project_path, query=query, k=k)
    if not memories:
        return ""

    lines = ["Relevant semantic project memory:"]
    remaining = _MAX_PROMPT_MEMORY_CHARS
    for memory in memories:
        item = (
            f"- [{memory.kind}; importance {memory.importance}] "
            f"{memory.content.strip()}"
        )
        if len(item) > remaining:
            item = item[: max(0, remaining - 3)].rstrip() + "..."
        lines.append(item)
        remaining -= len(item)
        if remaining <= 0:
            break
    return "\n".join(lines)


def _compact_exchange_text(
    *,
    user_message: str,
    assistant_response: str,
    metadata: dict[str, object],
) -> str:
    route = " / ".join(
        str(metadata.get(key) or "")
        for key in ("intent", "action", "response_source")
        if metadata.get(key)
    )
    outcome = " / ".join(
        str(metadata.get(key) or "")
        for key in ("status", "task_profile")
        if metadata.get(key)
    )
    lines = ["Project memory chunk."]
    if route:
        lines.append(f"Route: {route}.")
    if outcome:
        lines.append(f"Outcome: {outcome}.")
    planned = metadata.get("planned_files")
    if isinstance(planned, list) and planned:
        lines.append("Planned files: " + ", ".join(str(item) for item in planned[:8]))
    written = metadata.get("written_files")
    if isinstance(written, list) and written:
        lines.append("Written files: " + ", ".join(str(item) for item in written[:8]))
    lines.append(f"User: {_truncate(user_message, 700)}")
    lines.append(f"Assistant: {_truncate(assistant_response, 700)}")
    return _truncate("\n".join(lines), _MAX_MEMORY_CONTENT_CHARS)


def _kind_from_metadata(metadata: dict[str, object]) -> str:
    if metadata.get("status") or metadata.get("task_profile"):
        return "task_outcome"
    if metadata.get("action") in {"read_file", "list_folder", "path_info"}:
        return "project_fact"
    if metadata.get("action") in {"current_time", "calculate"}:
        return "ephemeral"
    return "conversation"


def _importance_from_metadata(metadata: dict[str, object]) -> int:
    if metadata.get("status") in {"SUCCESS", "COMPLETED_WITH_WARNINGS"}:
        return 4
    if metadata.get("status") == "FAILED":
        return 3
    if metadata.get("action_requires_workflow") is True:
        return 4
    if metadata.get("action") in {"read_file", "list_folder", "path_info"}:
        return 2
    return 1


def _vector_id(chunk: ProjectMemoryChunk) -> str:
    return f"project-memory:{chunk['id']}"


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 3)].rstrip() + "..."


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
