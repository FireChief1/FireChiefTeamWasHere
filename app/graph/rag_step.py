"""RAG retrieval node."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from app.graph.error_boundary import node_error_boundary
from app.graph.state import AgentState
from app.rag.retriever import retrieve_with_status


@node_error_boundary
async def rag_node(state: AgentState) -> dict[str, Any]:
    """Retrieve coding-standard chunks relevant to the task."""
    if state.get("use_rag") is False:
        logger.info("RAG: disabled for this run")
        return {
            "rag_context": [],
            "rag_sources": [],
            "rag_status": "disabled",
            "rag_message": "RAG disabled for this run.",
            "rag_chunk_count": 0,
        }
    retrieval = await asyncio.to_thread(
        retrieve_with_status,
        state["task"],
        profile=state.get("task_profile"),
    )
    chunks = retrieval.chunks
    logger.info(f"RAG: retrieved {len(chunks)} chunk(s)")
    if not chunks:
        return {
            "rag_context": [],
            "rag_sources": [],
            "rag_status": retrieval.status,
            "rag_message": retrieval.message,
            "rag_chunk_count": 0,
        }
    return {
        "rag_context": [f"[{chunk.source}]\n{chunk.text}" for chunk in chunks],
        "rag_sources": [chunk.source for chunk in chunks],
        "rag_status": "retrieved",
        "rag_message": retrieval.message,
        "rag_chunk_count": len(chunks),
    }
