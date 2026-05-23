"""Tests for RAG document chunking."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.rag import ingest as ingest_module
from app.rag.ingest import chunk_markdown, source_domain, split_large_chunk
from app.rag.retriever import RetrievedChunk, _profile_filtered_chunks


def test_chunk_markdown_splits_on_section_headings():
    text = "# Title\nintro\n\n## First\na\n\n## Second\nb\n"
    chunks = chunk_markdown(text)
    assert len(chunks) == 3


def test_chunk_markdown_keeps_the_heading_with_its_section():
    text = "## Section A\ncontent a\n\n## Section B\ncontent b\n"
    chunks = chunk_markdown(text)
    assert chunks[0].startswith("## Section A")
    assert "content a" in chunks[0]


def test_chunk_markdown_returns_empty_for_blank_input():
    assert chunk_markdown("") == []
    assert chunk_markdown("\n\n") == []


def test_source_domain_uses_top_level_docs_folder():
    assert source_domain("frontend/html-css-standards.md") == "frontend"
    assert source_domain("architecture.md") == "general"


def test_split_large_chunk_caps_parts_and_keeps_content():
    text = " ".join(f"word{i}" for i in range(80))

    chunks = split_large_chunk(text, max_chars=80, overlap=10)

    assert len(chunks) > 1
    assert all(len(chunk) <= 80 for chunk in chunks)
    assert chunks[0].startswith("word0")


def test_ingest_embeds_before_recreating_collection(monkeypatch, tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "guide.md").write_text("# Guide\n\n## One\ncontent", encoding="utf-8")
    events: list[str] = []

    class FakeEmbeddings:
        def embed_documents(self, documents):
            events.append("embed")
            return [[0.1] for _ in documents]

    class FakeCollection:
        def add(self, **_kwargs):
            events.append("add")

    def fake_get_collection(*, create=False):
        assert create is True
        events.append("create_collection")
        return FakeCollection()

    monkeypatch.setattr(ingest_module, "settings", SimpleNamespace(
        docs_dir=docs_dir,
        chunk_size=500,
        chunk_overlap=50,
    ))
    monkeypatch.setattr(ingest_module, "get_embeddings", lambda: FakeEmbeddings())
    monkeypatch.setattr(ingest_module, "get_collection", fake_get_collection)

    assert ingest_module.ingest() == 2
    assert events == ["embed", "create_collection", "add"]


def test_ingest_does_not_recreate_collection_when_embedding_fails(monkeypatch, tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "guide.md").write_text("# Guide\ncontent", encoding="utf-8")
    events: list[str] = []

    class BrokenEmbeddings:
        def embed_documents(self, _documents):
            events.append("embed")
            raise RuntimeError("embedding unavailable")

    def fake_get_collection(*, create=False):
        events.append("create_collection")
        raise AssertionError("collection should not be recreated before embeddings")

    monkeypatch.setattr(ingest_module, "settings", SimpleNamespace(
        docs_dir=docs_dir,
        chunk_size=500,
        chunk_overlap=50,
    ))
    monkeypatch.setattr(ingest_module, "get_embeddings", lambda: BrokenEmbeddings())
    monkeypatch.setattr(ingest_module, "get_collection", fake_get_collection)

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        ingest_module.ingest()
    assert events == ["embed"]


def test_profile_filtered_chunks_prefers_matching_profile_sources():
    chunks = [
        RetrievedChunk(text="python", source="coding-standards/python-style-guide.md"),
        RetrievedChunk(text="html", source="frontend/html-css-standards.md"),
    ]

    filtered = _profile_filtered_chunks(chunks, "static_web", 5)

    assert filtered == [chunks[1]]


def test_python_profile_can_use_architecture_guidance():
    chunks = [
        RetrievedChunk(text="solid", source="architecture/solid-principles.md"),
        RetrievedChunk(text="html", source="frontend/html-css-standards.md"),
    ]

    filtered = _profile_filtered_chunks(chunks, "python", 5)

    assert filtered == [chunks[0]]


def test_project_profile_can_use_architecture_folder_guidance():
    chunks = [
        RetrievedChunk(text="review", source="architecture/project-review-checklist.md"),
        RetrievedChunk(text="html", source="frontend/html-css-standards.md"),
    ]

    filtered = _profile_filtered_chunks(chunks, "project", 5)

    assert filtered == [chunks[0]]
