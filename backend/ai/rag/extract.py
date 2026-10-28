"""Text out of a stored file, for the course-material index.

Deliberately partial: plain text, Markdown, CSV, PDF (pypdf) and Word .docx
(read as the ZIP of XML it is, with the standard library). Anything else is
reported as unsupported rather than guessed at -- an index full of decoded
binary is worse than an honest gap, because it answers questions with noise.

Every limit here exists because the input is a file somebody uploaded: a size
cap on what is read, a page cap on PDFs, and a cap on the text kept.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

TEXT_TYPES = frozenset({"text/plain", "text/markdown", "text/x-markdown", "text/csv"})
PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUPPORTED_TYPES = TEXT_TYPES | {PDF_TYPE, DOCX_TYPE}

MAX_PDF_PAGES = 300
MAX_TEXT_CHARS = 400_000

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class Extracted:
    text: str
    truncated: bool


def is_supported(mime_type: str | None) -> bool:
    return (mime_type or "").split(";")[0].strip().lower() in SUPPORTED_TYPES


def _clip(text: str) -> Extracted:
    text = re.sub(r"[ \t]+", " ", text.replace("\x00", ""))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > MAX_TEXT_CHARS:
        return Extracted(text[:MAX_TEXT_CHARS], truncated=True)
    return Extracted(text, truncated=False)


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info = archive.getinfo("word/document.xml")
        # A ZIP entry can expand enormously; refuse rather than inflate it.
        if info.file_size > 50 * 1024 * 1024:
            raise ValueError("document.xml is implausibly large")
        root = ElementTree.fromstring(archive.read(info))
    paragraphs = []
    for para in root.iter(f"{_W}p"):
        runs = [node.text or "" for node in para.iter(f"{_W}t")]
        if runs:
            paragraphs.append("".join(runs))
    return "\n\n".join(paragraphs)


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for index, page in enumerate(reader.pages):
        if index >= MAX_PDF_PAGES:
            break
        pages.append(page.extract_text() or "")
    return "\n\n".join(pages)


def extract_text(data: bytes, mime_type: str | None) -> Extracted:
    """Text from `data`. Raises ValueError for an unsupported or unreadable file."""
    kind = (mime_type or "").split(";")[0].strip().lower()
    if kind in TEXT_TYPES:
        return _clip(data.decode("utf-8", errors="replace"))
    if kind == PDF_TYPE:
        return _clip(_pdf_text(data))
    if kind == DOCX_TYPE:
        return _clip(_docx_text(data))
    raise ValueError(f"unsupported type {kind or 'unknown'}")
