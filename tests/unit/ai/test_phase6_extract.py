"""Phase 6: text extraction for the course-material index.

Real files, built in memory: a Word document is a ZIP of XML and a PDF is a
small hand-written file with one text object, so these exercise the actual
parsers rather than a mock of them.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from backend.ai.rag.extract import DOCX_TYPE, MAX_TEXT_CHARS, PDF_TYPE, extract_text, is_supported


def _docx(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def _pdf(text: str) -> bytes:
    """A minimal valid one-page PDF with `text` drawn in Helvetica."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


def test_plain_text_markdown_and_csv_are_read():
    for mime in ("text/plain", "text/markdown", "text/csv; charset=utf-8"):
        assert extract_text(b"Photosynthesis\n\n\n\nuses light", mime).text == "Photosynthesis\n\nuses light"


def test_a_word_document_is_read_paragraph_by_paragraph():
    out = extract_text(_docx(["Week 1: Loops", "A for loop repeats work."]), DOCX_TYPE)
    assert out.text == "Week 1: Loops\n\nA for loop repeats work."


def test_a_pdf_is_read():
    assert "Volcanoes erupt magma" in extract_text(_pdf("Volcanoes erupt magma"), PDF_TYPE).text


@pytest.mark.parametrize("mime", ["video/mp4", "image/png", "application/zip", None, ""])
def test_anything_else_is_unsupported_not_guessed(mime):
    assert not is_supported(mime)
    with pytest.raises(ValueError, match="unsupported"):
        extract_text(b"\x00\x01binary", mime)


def test_text_is_capped_and_says_so():
    out = extract_text(b"word " * (MAX_TEXT_CHARS // 2), "text/plain")
    assert out.truncated is True
    assert len(out.text) == MAX_TEXT_CHARS


def test_invalid_bytes_do_not_break_text_extraction():
    assert "caf" in extract_text(b"caf\xe9 notes", "text/plain").text


def test_a_document_that_would_inflate_enormously_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"<a>" + b" " * (51 * 1024 * 1024) + b"</a>")
    with pytest.raises(ValueError, match="implausibly large"):
        extract_text(buffer.getvalue(), DOCX_TYPE)
