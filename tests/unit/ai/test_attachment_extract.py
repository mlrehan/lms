"""What the assistant is told a file contains -- and what it refuses to pretend.

Every refusal here is asserted by its *reason*, not merely by raising: a file
refused for the wrong reason (a renamed program refused because it is "empty")
passes a bare `pytest.raises` while the check it was meant to prove is gone.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from backend.ai.attachment_extract import AttachmentRejected, classify, extract

NOTEBOOK = {
    "nbformat": 4,
    "metadata": {"kernelspec": {"language": "python"}, "colab": {"base_uri": "https://localhost:8080/"}},
    "cells": [
        {"cell_type": "markdown", "source": ["# Section D Question 19\n", "Average of three marks"]},
        {
            "cell_type": "code", "execution_count": 3,
            "source": ["marks = [3.0, 2.0, 4.0]\n", "print(sum(marks) / 3)"],
            "outputs": [{"output_type": "stream", "name": "stdout", "text": ["3.0\n"]}],
        },
        {
            "cell_type": "code", "execution_count": 4, "source": "total_marks + 1",
            "outputs": [{
                "output_type": "error", "ename": "NameError", "evalue": "name 'total_marks' is not defined",
                "traceback": ["\x1b[0;31mNameError\x1b[0m: name 'total_marks' is not defined"],
            }],
        },
        {"cell_type": "code", "execution_count": None, "source": "plot()", "outputs": []},
        {
            "cell_type": "code", "execution_count": 6, "source": "chart",
            "outputs": [{"output_type": "display_data", "data": {"image/png": "iVBOR...", "text/plain": "<Figure>"}}],
        },
    ],
}


def _zip(entries: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_a_notebook_is_rendered_cell_by_cell_with_its_outputs_and_errors() -> None:
    result = extract("assignment.ipynb", json.dumps(NOTEBOOK).encode())
    text = result.text or ""
    assert result.kind == "NOTEBOOK" and result.status == "READY"
    assert "--- Cell 2 · code · In [3] ---" in text and "print(sum(marks) / 3)" in text
    assert "[stdout]\n3.0" in text
    # The error is evidence for marking, with the terminal colour codes gone.
    assert "[ERROR] NameError: name 'total_marks' is not defined" in text and "\x1b" not in text
    assert "--- Cell 4 · code · not run ---" in text and "no saved output" in text
    assert "image/png output" in text  # a chart is named, never silently dropped
    assert result.details["unexecuted_code_cells"] == 1 and result.details["error_cells"] == 1
    assert "localhost:8080" not in text  # notebook metadata is not content


def test_a_broken_notebook_is_refused_with_the_line_that_broke_it() -> None:
    with pytest.raises(AttachmentRejected, match="not valid notebook JSON"):
        extract("half.ipynb", b'{"cells": [ {"cell_type": "code",\n')


def test_json_that_is_not_a_notebook_is_refused() -> None:
    with pytest.raises(AttachmentRejected, match="no cells"):
        extract("data.ipynb", b'{"hello": 1}')


@pytest.mark.parametrize("name, reason", [
    ("setup.exe", "Programs are not accepted"),
    ("drawing.svg", "can carry script"),
    ("old.doc", "save it as .docx"),
    ("bundle.zip", "Archives are not opened"),
    ("README", "without an extension"),
    ("thing.xyz", ".xyz files cannot be read"),
])
def test_unsupported_types_are_refused_by_name(name: str, reason: str) -> None:
    with pytest.raises(AttachmentRejected, match=reason):
        classify(name)


def test_a_program_renamed_to_py_is_refused_as_binary() -> None:
    with pytest.raises(AttachmentRejected, match="binary data"):
        extract("homework.py", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00")


def test_text_renamed_to_pdf_is_refused() -> None:
    with pytest.raises(AttachmentRejected, match="not a real PDF"):
        extract("essay.pdf", b"just some text")


def test_text_renamed_to_docx_is_refused() -> None:
    with pytest.raises(AttachmentRejected, match="not a real Word file"):
        extract("essay.docx", b"just some text")


def test_a_zip_that_is_not_a_word_document_is_refused() -> None:
    with pytest.raises(AttachmentRejected, match="no word/document.xml"):
        extract("essay.docx", _zip({"payload.bin": b"x"}))


def test_a_zip_bomb_is_refused_before_it_is_inflated() -> None:
    # 100 MB of zeros compresses to ~100 KB: the declared size is what is checked.
    bomb = _zip({"xl/workbook.xml": "<workbook/>", "xl/worksheets/sheet1.xml": b"\0" * (100 * 1024 * 1024)})
    assert len(bomb) < 1024 * 1024
    with pytest.raises(AttachmentRejected, match="implausible size"):
        extract("sheet.xlsx", bomb)


def test_an_office_file_carrying_a_dtd_is_refused() -> None:
    evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><w:document xmlns:w="w">&a;</w:document>'
    with pytest.raises(AttachmentRejected, match="never use"):
        extract("evil.docx", _zip({"word/document.xml": evil}))


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def test_a_word_document_keeps_headings_and_tables() -> None:
    doc = (
        f'<w:document {W}><w:body>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Marking scheme</w:t></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Criterion</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:t>Marks</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>Correct output</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:t>10</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
        '</w:body></w:document>'
    )
    result = extract("rubric.docx", _zip({"word/document.xml": doc}))
    assert result.text is not None
    assert "# Marking scheme" in result.text
    assert "Criterion | Marks" in result.text and "Correct output | 10" in result.text


S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def test_a_spreadsheet_keeps_cell_positions_and_formulas() -> None:
    xlsx = _zip({
        "xl/workbook.xml": f'<workbook {S} {R}><sheets><sheet name="Marks" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'
        ),
        "xl/sharedStrings.xml": f'<sst {S}><si><t>Name</t></si><si><r><t>Ve</t></r><r><t>s</t></r></si></sst>',
        # A gap: A1 and D1 with no B or C cell -- appending in order would shift D left.
        "xl/worksheets/sheet1.xml": (
            f'<worksheet {S}><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="D1"><v>70</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="D2"><f>SUM(B2:C2)</f><v>9</v></c></row>'
            '</sheetData></worksheet>'
        ),
    })
    result = extract("marks.xlsx", xlsx)
    assert result.text is not None
    assert "=== Sheet: Marks ===" in result.text
    assert "1: Name\t\t\t70" in result.text
    assert "2: Ves\t\t\t9 [=SUM(B2:C2)]" in result.text  # shared string split across runs, rejoined


def test_a_pdf_with_no_text_layer_says_so_instead_of_reading_as_empty() -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    result = extract("scan.pdf", buffer.getvalue())
    assert result.status == "EMPTY" and result.text is None
    assert "no text layer" in (result.note or "")
    assert result.details["pages"] == 1


def test_an_image_is_re_encoded_and_a_fake_one_refused() -> None:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (3000, 1000), "white").save(buffer, format="PNG")
    result = extract("board.png", buffer.getvalue())
    assert result.kind == "IMAGE" and result.mime_type == "image/jpeg"
    assert result.image_bytes is not None and result.image_bytes[:2] == b"\xff\xd8"
    with Image.open(io.BytesIO(result.image_bytes)) as shown:
        assert max(shown.size) == 1600  # downscaled for the model
    with pytest.raises(AttachmentRejected, match="not a readable image"):
        extract("board.png", b"<svg onload=alert(1)>")


def test_cp1252_text_from_an_old_editor_is_read() -> None:
    result = extract("notes.txt", "café – naïve".encode("cp1252"))
    assert result.text == "café – naïve"


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(AttachmentRejected, match="empty"):
        extract("blank.py", b"")
