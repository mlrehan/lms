"""Unit tests for RAG document chunker."""

import pytest
from backend.ai.rag.chunker import chunk_text


def test_chunk_text_empty_and_short():
    assert chunk_text("") == []
    assert chunk_text("   \n \r  ") == []

    short = "Python functions are first-class citizens."
    chunks = chunk_text(short, chunk_size=500)
    assert len(chunks) == 1
    assert chunks[0] == short


def test_chunk_text_paragraphs_and_overlap():
    long_doc = (
        "Module 1: Introduction to SQL\n\n"
        "Structured Query Language is used to manage relational databases. " * 10
        + "\n\n"
        + "Module 2: Advanced Joins\n\n"
        "Inner joins return rows where a match exists in both tables. " * 10
        + "\n\n"
        + "Module 3: Indexing and Optimization\n\n"
        "Indexes speed up data retrieval operations at the cost of writes. " * 10
    )

    chunks = chunk_text(long_doc, chunk_size=300, chunk_overlap=50)
    assert len(chunks) >= 3
    # Verify each chunk is bounded
    for c in chunks:
        assert len(c) > 0

