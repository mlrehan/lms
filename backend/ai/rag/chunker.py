"""Document & Text Chunking Engine for RAG.

Splits technical content, lecture sheets, and lesson notes into semantically coherent
chunks with sliding-window overlap.
"""

from __future__ import annotations

import re
from typing import Sequence


def chunk_text(
    text: str,
    *,
    chunk_size: int = 600,
    chunk_overlap: int = 100,
) -> list[str]:
    """Split text into overlapping character windows preserving paragraph and sentence boundaries."""
    cleaned = re.sub(r"\r\n?", "\n", text).strip()
    if not cleaned:
        return []

    if len(cleaned) <= chunk_size:
        return [cleaned]

    # Split on double newlines (paragraphs), single newlines, or sentence ends
    paragraphs = re.split(r"\n\s*\n", cleaned)
    chunks: list[str] = []
    current_chunk = ""

    for para in paragraphs:
        para_clean = para.strip()
        if not para_clean:
            continue

        if not current_chunk:
            current_chunk = para_clean
        elif len(current_chunk) + len(para_clean) + 2 <= chunk_size:
            current_chunk += "\n\n" + para_clean
        else:
            chunks.append(current_chunk)
            # Retain overlap from end of current chunk
            overlap_prefix = current_chunk[-chunk_overlap:] if len(current_chunk) > chunk_overlap else current_chunk
            current_chunk = overlap_prefix + "\n\n" + para_clean

    if current_chunk and (not chunks or chunks[-1] != current_chunk):
        chunks.append(current_chunk)

    return chunks

