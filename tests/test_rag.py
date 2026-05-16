"""Tests for RAG document chunking."""

from __future__ import annotations

from app.rag.ingest import chunk_markdown


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
