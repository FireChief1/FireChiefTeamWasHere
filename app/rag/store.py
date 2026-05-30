"""ChromaDB-backed storage for the RAG knowledge base.

Embeddings are computed with the local nomic-embed-text model via Ollama;
ChromaDB is used purely as the vector store.
"""

from __future__ import annotations

import contextlib
from typing import Any

import chromadb
from langchain_ollama import OllamaEmbeddings

from app.config import settings

COLLECTION_NAME = "knowledge"
PROJECT_MEMORY_COLLECTION_NAME = "project_memory"


def get_collection(*, create: bool = False) -> Any:
    """Return the RAG ChromaDB collection.

    Args:
        create: If True, drop and recreate the collection. Used by ingestion
            so each ingest starts from a clean state.

    Returns:
        The ChromaDB collection object.
    """
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    if create:
        # The collection may not exist yet on a first ingest.
        with contextlib.suppress(Exception):
            client.delete_collection(COLLECTION_NAME)
        return client.create_collection(COLLECTION_NAME)
    return client.get_or_create_collection(COLLECTION_NAME)


def get_project_memory_collection(*, create: bool = False) -> Any:
    """Return the ChromaDB collection used for semantic project memory."""
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    if create:
        with contextlib.suppress(Exception):
            client.delete_collection(PROJECT_MEMORY_COLLECTION_NAME)
        return client.create_collection(PROJECT_MEMORY_COLLECTION_NAME)
    return client.get_or_create_collection(PROJECT_MEMORY_COLLECTION_NAME)


def get_embeddings() -> OllamaEmbeddings:
    """Return the Ollama embedding model used for the knowledge base."""
    return OllamaEmbeddings(
        model=settings.embedding_model,
        base_url=settings.ollama_base_url,
    )
