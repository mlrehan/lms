"""Read a file someone attached to an AI assistant message.

Pure functions over bytes: no database, no storage, no network. The service
layer decides who may attach and keeps the result; this module decides only
*what the file is* and *what text it holds*.

Three rules shape it, each the answer to a way an upload goes wrong:

1. **The extension chooses the reader, and the bytes must agree.** A browser's
   MIME type is whatever the operating system guessed (Windows sends
   ``application/octet-stream`` for a ``.ipynb``), so it is not consulted. The
   extension picks one of a short allowlist of readers, and that reader then
   refuses bytes that are not what the extension claims: a PDF must start
   ``%PDF-``, an Office file must be a ZIP holding its main part, a text file
   must decode, an image must decode as one of four formats. A renamed
   executable fails every one of those.
2. **Every limit is about an attacker's file, not a typical one.** ZIP entries
   are size-checked before they are inflated (a 40 KB archive can expand to
   gigabytes), PDF pages and spreadsheet rows are capped, images have a pixel
   budget checked before decoding, and the text kept is capped.
3. **Never pretend.** A scanned PDF with no text layer is reported as having
   none, not as an empty document; a format that cannot be read is refused by
   name. The assistant is told exactly what it received, because a model told
   "here is the file" when it got nothing will grade nothing confidently.

Notebooks are rendered cell by cell with their outputs, execution counts and
errors, because for marking the outputs *are* the evidence: whether the code
ran, what it printed, and where it failed.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

MAX_TEXT_CHARS = 1_500_000
MAX_PDF_PAGES = 400
MAX_SHEET_ROWS = 5_000
MAX_OUTPUT_CHARS = 6_000          # per notebook cell output
MAX_IMAGE_PIXELS = 40_000_000     # checked before decoding
IMAGE_MAX_SIDE = 1_600            # what the model is shown
ZIP_MAX_ENTRIES = 10_000
ZIP_MAX_TOTAL = 200 * 1024 * 1024
ZIP_MAX_ENTRY = 60 * 1024 * 1024

# extension -> (kind, canonical MIME type). Anything absent is refused.
_CODE = {
    "py": "text/x-python", "sql": "application/sql", "js": "text/javascript", "ts": "text/plain",
    "tsx": "text/plain", "jsx": "text/plain", "java": "text/x-java", "c": "text/x-c", "h": "text/x-c",
    "cpp": "text/x-c++", "cs": "text/plain", "r": "text/plain", "rb": "text/plain", "go": "text/plain",
    "php": "text/plain", "html": "text/html", "css": "text/css", "json": "application/json",
    "xml": "application/xml", "yaml": "text/yaml", "yml": "text/yaml", "sh": "text/plain",
    "kt": "text/plain", "swift": "text/plain", "scala": "text/plain", "m": "text/plain",
}
FORMATS: dict[str, tuple[str, str]] = {
    "ipynb": ("NOTEBOOK", "application/x-ipynb+json"),
    "txt": ("TEXT", "text/plain"), "md": ("TEXT", "text/markdown"), "markdown": ("TEXT", "text/markdown"),
    "log": ("TEXT", "text/plain"),
    "csv": ("CSV", "text/csv"), "tsv": ("CSV", "text/tab-separated-values"),
    "pdf": ("PDF", "application/pdf"),
    "docx": ("DOCX", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "xlsx": ("XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "png": ("IMAGE", "image/png"), "jpg": ("IMAGE", "image/jpeg"), "jpeg": ("IMAGE", "image/jpeg"),
    "webp": ("IMAGE", "image/webp"), "gif": ("IMAGE", "image/gif"),
    **{ext: ("CODE", mime) for ext, mime in _CODE.items()},
}
# Named so the refusal can say why rather than "unsupported".
_REFUSED_HINTS = {
    "doc": "Old Word .doc files cannot be read; save it as .docx or PDF.",
    "xls": "Old Excel .xls files cannot be read; save it as .xlsx or CSV.",
    "ppt": "PowerPoint files cannot be read; export it as PDF.",
    "pptx": "PowerPoint files cannot be read; export it as PDF.",
    "zip": "Archives are not opened; attach the files inside it instead.",
    "rar": "Archives are not opened; attach the files inside it instead.",
    "7z": "Archives are not opened; attach the files inside it instead.",
    "svg": "SVG images can carry script and are not accepted; attach a PNG or JPEG.",
    "exe": "Programs are not accepted.",
    "dll": "Programs are not accepted.",
    "msi": "Programs are not accepted.",
    "bat": "Scripts that run on Windows are not accepted; paste the code as a .txt file.",
    "ps1": "Scripts that run on Windows are not accepted; paste the code as a .txt file.",
}

ACCEPTED_EXTENSIONS = tuple(sorted(FORMATS))


class AttachmentRejected(ValueError):
    """The file is not one this assistant will take. The message is for the person."""


@dataclass
class Extracted:
    kind: str
    mime_type: str
    status: str                       # READY / EMPTY
    text: str | None = None
    truncated: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    # For images: the re-encoded JPEG the model is shown (never the original
    # bytes, which could be a polyglot carrying something else).
    image_bytes: bytes | None = None
    note: str | None = None


def classify(filename: str) -> tuple[str, str, str]:
    """(extension, kind, canonical MIME) for `filename`, or raise AttachmentRejected."""
    name = (filename or "").strip()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in FORMATS:
        kind, mime = FORMATS[ext]
        return ext, kind, mime
    if ext in _REFUSED_HINTS:
        raise AttachmentRejected(_REFUSED_HINTS[ext])
    shown = f".{ext} files" if ext else "Files without an extension"
    raise AttachmentRejected(
        f"{shown} cannot be read here. Supported: PDF, Word (.docx), Excel (.xlsx), CSV, text, "
        "Markdown, Jupyter notebooks (.ipynb), code files and images (PNG, JPEG, WebP, GIF)."
    )


def _clip(text: str) -> tuple[str, bool]:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    if len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS], True
    return text, False


def decode_text(data: bytes) -> str:
    """Decode a text file, refusing binary data disguised by its extension."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError as exc:
            raise AttachmentRejected("The file says it is UTF-16 text but is not readable as such.") from exc
    sample = data[:65536]
    if b"\x00" in sample:
        raise AttachmentRejected("This file contains binary data, not text, so it cannot be read as its extension claims.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    # Older Windows editors save in cp1252; accept that only when it decodes cleanly.
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise AttachmentRejected("The file's text encoding could not be read; save it as UTF-8.") from exc


# ---------------------------------------------------------------------------
# ZIP-based Office files
# ---------------------------------------------------------------------------


def _open_zip(data: bytes, required: str, label: str) -> zipfile.ZipFile:
    if not data.startswith(b"PK\x03\x04"):
        raise AttachmentRejected(f"This is not a real {label} file (it is not the ZIP container {label} files are).")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise AttachmentRejected(f"The {label} file is damaged and could not be opened.") from exc
    infos = archive.infolist()
    # Every entry is judged on open, not only the ones a reader goes on to use:
    # an unread 100 MB part is still a sign of a file built to do harm.
    if (
        len(infos) > ZIP_MAX_ENTRIES
        or sum(i.file_size for i in infos) > ZIP_MAX_TOTAL
        or any(i.file_size > ZIP_MAX_ENTRY for i in infos)
    ):
        raise AttachmentRejected(f"The {label} file expands to an implausible size and was not opened.")
    names = {i.filename for i in infos}
    if required not in names:
        raise AttachmentRejected(f"This is not a real {label} file: it has no {required}.")
    return archive


def _read_entry(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > ZIP_MAX_ENTRY:
        raise AttachmentRejected("Part of the file expands to an implausible size and was not opened.")
    with archive.open(info) as handle:
        # Read one byte past the declared size: a lying header is caught here.
        blob = handle.read(ZIP_MAX_ENTRY + 1)
    if len(blob) > ZIP_MAX_ENTRY:
        raise AttachmentRejected("Part of the file expands to an implausible size and was not opened.")
    return blob


def _xml(blob: bytes) -> ElementTree.Element:
    # Office parts never use a DTD. Refusing one closes entity-expansion tricks
    # without depending on the XML parser's own limits.
    if b"<!DOCTYPE" in blob[:4096] or b"<!ENTITY" in blob:
        raise AttachmentRejected("The file contains XML constructs Office files never use, and was not opened.")
    return ElementTree.fromstring(blob)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _docx(data: bytes) -> Extracted:
    archive = _open_zip(data, "word/document.xml", "Word")
    root = _xml(_read_entry(archive, "word/document.xml"))
    body = root.find(f"{_W}body")
    lines: list[str] = []
    tables = 0

    def para_text(p: ElementTree.Element) -> str:
        return "".join(t.text or "" for t in p.iter(f"{_W}t"))

    for block in (list(body) if body is not None else []):
        if block.tag == f"{_W}p":
            text = para_text(block)
            style = block.find(f"{_W}pPr/{_W}pStyle")
            level = style.get(f"{_W}val", "") if style is not None else ""
            match = re.match(r"(?i)heading\s*(\d)", level)
            if match and text:
                text = "#" * int(match.group(1)) + " " + text
            lines.append(text)
        elif block.tag == f"{_W}tbl":
            tables += 1
            lines.append(f"[Table {tables}]")
            for row in block.iter(f"{_W}tr"):
                cells = [" ".join(para_text(p) for p in tc.iter(f"{_W}p")).strip() for tc in row.iter(f"{_W}tc")]
                lines.append(" | ".join(cells))
            lines.append("")
    text, truncated = _clip("\n".join(lines))
    kind, mime = FORMATS["docx"]
    return Extracted(kind, mime, "READY" if text else "EMPTY", text or None, truncated, {"tables": tables},
                     note=None if text else "The document contains no text.")


def _column_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return 0
    n = 0
    for ch in letters.group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _xlsx(data: bytes) -> Extracted:
    archive = _open_zip(data, "xl/workbook.xml", "Excel")
    names = set(archive.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in _xml(_read_entry(archive, "xl/sharedStrings.xml")).iter(f"{_S}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_S}t")))
    rels: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for rel in _xml(_read_entry(archive, "xl/_rels/workbook.xml.rels")).iter(f"{_PKG}Relationship"):
            target = rel.get("Target", "").lstrip("/")
            rels[rel.get("Id", "")] = target if target.startswith("xl/") else f"xl/{target}"
    workbook = _xml(_read_entry(archive, "xl/workbook.xml"))
    out: list[str] = []
    sheets: list[dict[str, Any]] = []
    truncated_rows = False
    for sheet in workbook.iter(f"{_S}sheet"):
        name = sheet.get("name", "Sheet")
        path = rels.get(sheet.get(f"{_R}id", ""), "")
        if path not in names:
            continue
        root = _xml(_read_entry(archive, path))
        out.append(f"=== Sheet: {name} ===")
        count = 0
        for row in root.iter(f"{_S}row"):
            if count >= MAX_SHEET_ROWS:
                truncated_rows = True
                out.append(f"[... rows after {MAX_SHEET_ROWS} not shown]")
                break
            values: dict[int, str] = {}
            for cell in row.iter(f"{_S}c"):
                kind = cell.get("t", "n")
                v = cell.find(f"{_S}v")
                raw = v.text if v is not None else None
                if kind == "s" and raw is not None and raw.isdigit() and int(raw) < len(shared):
                    value = shared[int(raw)]
                elif kind == "inlineStr":
                    value = "".join(t.text or "" for t in cell.iter(f"{_S}t"))
                elif kind == "b":
                    value = "TRUE" if raw == "1" else "FALSE"
                else:
                    value = raw or ""
                formula = cell.find(f"{_S}f")
                if formula is not None and formula.text:
                    value = f"{value} [={formula.text}]"
                values[_column_index(cell.get("r", ""))] = value
            if values:
                width = max(values) + 1
                ref = row.get("r", str(count + 1))
                out.append(f"{ref}: " + "\t".join(values.get(i, "") for i in range(width)))
            count += 1
        sheets.append({"name": name, "rows": count})
        out.append("")
    text, truncated = _clip("\n".join(out))
    kind, mime = FORMATS["xlsx"]
    has_cells = any(s["rows"] for s in sheets)
    return Extracted(kind, mime, "READY" if has_cells else "EMPTY", text if has_cells else None,
                     truncated or truncated_rows, {"sheets": sheets},
                     note=None if has_cells else "The workbook has no filled cells.")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _pdf(data: bytes) -> Extracted:
    if not data.lstrip()[:5] == b"%PDF-":
        raise AttachmentRejected("This is not a real PDF file.")
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise AttachmentRejected("The PDF is password-protected and cannot be read.")
        total = len(reader.pages)
        pages = []
        for index, page in enumerate(reader.pages):
            if index >= MAX_PDF_PAGES:
                break
            pages.append(f"--- Page {index + 1} ---\n{page.extract_text() or ''}")
    except AttachmentRejected:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise AttachmentRejected("The PDF is damaged and could not be read.") from exc
    text, truncated = _clip("\n\n".join(pages))
    has_text = bool(re.sub(r"--- Page \d+ ---", "", text).strip())
    kind, mime = FORMATS["pdf"]
    return Extracted(
        kind, mime, "READY" if has_text else "EMPTY", text if has_text else None,
        truncated or total > MAX_PDF_PAGES, {"pages": total},
        note=None if has_text else (
            "The PDF has no text layer -- it is probably a scan or a photo. Its contents cannot be read "
            "here; attach the pages as images, or ask for the original document."
        ),
    )


# ---------------------------------------------------------------------------
# Jupyter notebooks
# ---------------------------------------------------------------------------

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TAGS = re.compile(r"<[^>]+>")


def _joined(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(v) for v in value)
    return str(value or "")


def _cap(text: str) -> str:
    text = text.rstrip()
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + f"\n[... output cut: {len(text) - MAX_OUTPUT_CHARS} more characters]"
    return text


def _render_output(output: dict[str, Any]) -> str:
    kind = output.get("output_type")
    if kind == "stream":
        return f"[{output.get('name', 'stdout')}]\n" + _cap(_joined(output.get("text")))
    if kind == "error":
        trace = _ANSI.sub("", "\n".join(_joined(t) for t in output.get("traceback") or []))
        head = f"[ERROR] {output.get('ename', 'Error')}: {output.get('evalue', '')}"
        return head + ("\n" + _cap(trace) if trace else "")
    if kind in ("execute_result", "display_data", "pyout"):
        data = output.get("data") or {}
        parts = []
        label = "[result]" if kind != "display_data" else "[display]"
        if "text/plain" in data:
            parts.append(_cap(_joined(data["text/plain"])))
        elif "text/markdown" in data:
            parts.append(_cap(_joined(data["text/markdown"])))
        elif "text/html" in data:
            parts.append(_cap(_TAGS.sub(" ", _joined(data["text/html"]))))
        images = [m for m in data if m.startswith("image/")]
        if images:
            parts.append(f"[{', '.join(images)} output: a chart or picture, not shown here]")
        if "text" in output and not parts:  # nbformat 3
            parts.append(_cap(_joined(output["text"])))
        return label + "\n" + "\n".join(parts) if parts else label + " (empty)"
    return f"[{kind or 'output'}]"


def _notebook(data: bytes) -> Extracted:
    try:
        nb = json.loads(decode_text(data))
    except json.JSONDecodeError as exc:
        raise AttachmentRejected(
            f"This .ipynb file is not valid notebook JSON (line {exc.lineno}). It may be incomplete or edited by hand."
        ) from exc
    if not isinstance(nb, dict):
        raise AttachmentRejected("This .ipynb file is not a Jupyter notebook.")
    cells = nb.get("cells")
    if cells is None and isinstance(nb.get("worksheets"), list) and nb["worksheets"]:
        cells = nb["worksheets"][0].get("cells")  # nbformat 3
    if not isinstance(cells, list):
        raise AttachmentRejected("This .ipynb file has no cells, so it is not a Jupyter notebook.")

    meta = nb.get("metadata") or {}
    language = ((meta.get("kernelspec") or {}).get("language")
                or (meta.get("language_info") or {}).get("name") or "unknown")
    lines: list[str] = []
    counts = {"code": 0, "markdown": 0, "raw": 0}
    unexecuted = errors = 0
    for number, cell in enumerate(cells, start=1):
        if not isinstance(cell, dict):
            continue
        ctype = cell.get("cell_type", "code")
        counts[ctype] = counts.get(ctype, 0) + 1
        source = _joined(cell.get("source", cell.get("input", "")))
        if ctype == "code":
            run = cell.get("execution_count", cell.get("prompt_number"))
            outputs = cell.get("outputs") or []
            run_label = f"In [{run}]" if run is not None else "not run"
            if run is None and not outputs and source.strip():
                unexecuted += 1
            lines.append(f"--- Cell {number} · code · {run_label} ---")
            lines.append(source.rstrip() or "(empty)")
            if outputs:
                lines.append("Output:")
                for output in outputs:
                    if isinstance(output, dict):
                        if output.get("output_type") == "error":
                            errors += 1
                        lines.append(_render_output(output))
            elif source.strip():
                lines.append("Output: (none -- this cell has no saved output)")
        else:
            lines.append(f"--- Cell {number} · {ctype} ---")
            lines.append(source.rstrip() or "(empty)")
        lines.append("")
    header = (
        f"Jupyter notebook · language {language} · {len(cells)} cells "
        f"({counts.get('code', 0)} code, {counts.get('markdown', 0)} markdown) · "
        f"{unexecuted} code cell(s) never run · {errors} cell(s) ended in an error"
    )
    text, truncated = _clip(header + "\n\n" + "\n".join(lines))
    kind, mime = FORMATS["ipynb"]
    return Extracted(kind, mime, "READY", text, truncated, {
        "cells": len(cells), "code_cells": counts.get("code", 0), "markdown_cells": counts.get("markdown", 0),
        "unexecuted_code_cells": unexecuted, "error_cells": errors, "language": language,
    })


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def _image(data: bytes, ext: str) -> Extracted:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = (probe.format or "").upper()
            width, height = probe.size
            if fmt not in {"PNG", "JPEG", "WEBP", "GIF"}:
                raise AttachmentRejected("The image is not a PNG, JPEG, WebP or GIF.")
            if width * height > MAX_IMAGE_PIXELS:
                raise AttachmentRejected("The image has too many pixels to process.")
            probe.seek(0)
            image = probe.convert("RGB")
    except AttachmentRejected:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise AttachmentRejected(f"This is not a readable image, though it is named .{ext}.") from exc
    image.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return Extracted("IMAGE", "image/jpeg", "READY", None, False,
                     {"width": width, "height": height, "format": fmt}, image_bytes=buffer.getvalue())


# ---------------------------------------------------------------------------


def extract(filename: str, data: bytes) -> Extracted:
    """What the file is and what it contains. Raises AttachmentRejected with a reason."""
    ext, kind, mime = classify(filename)
    if not data:
        raise AttachmentRejected("The file is empty.")
    if kind == "NOTEBOOK":
        return _notebook(data)
    if kind == "PDF":
        return _pdf(data)
    if kind == "DOCX":
        return _docx(data)
    if kind == "XLSX":
        return _xlsx(data)
    if kind == "IMAGE":
        return _image(data, ext)
    text, truncated = _clip(decode_text(data))
    details: dict[str, Any] = {"lines": text.count("\n") + 1 if text else 0}
    if kind == "CSV":
        details["rows"] = details["lines"]
    return Extracted(kind, mime, "READY" if text else "EMPTY", text or None, truncated, details,
                     note=None if text else "The file contains no text.")
