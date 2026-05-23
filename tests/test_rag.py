"""Tests for RAG document chunking."""

from __future__ import annotations

from app.rag.ingest import chunk_markdown, source_domain
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


def test_profile_filtered_chunks_prefers_matching_profile_sources():
    chunks = [
        RetrievedChunk(text="python", source="coding-standards/python-style-guide.md"),
        RetrievedChunk(text="html", source="frontend/html-css-standards.md"),
    ]

    filtered = _profile_filtered_chunks(chunks, "static_web", 5)

    assert filtered == [chunks[1]]
