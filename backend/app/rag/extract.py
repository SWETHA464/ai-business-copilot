"""Text extraction + upload validation for PDF, DOCX, TXT and CSV.

Validation is content-based (magic bytes / decodability), not just extension based.
"""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

ALLOWED_TYPES = ("pdf", "docx", "txt", "csv")
MAX_CSV_ROWS = 20000


class ExtractionError(Exception):
    """User-presentable problem with an uploaded file."""


@dataclass
class Page:
    number: int | None
    text: str


def safe_display_name(filename: str) -> str:
    name = PurePath((filename or "").replace("\\", "/")).name
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = re.sub(r"[^\w.\- ()]", "_", name).strip(" .")
    return (name or "document")[:200]


def detect_type(filename: str, data: bytes) -> str:
    """Return the validated file type or raise ExtractionError."""
    ext = PurePath(filename or "").suffix.lower().lstrip(".")
    if ext not in ALLOWED_TYPES:
        raise ExtractionError(f"Unsupported file type '.{ext}'. Allowed: {', '.join(ALLOWED_TYPES)}.")
    if not data:
        raise ExtractionError("The file is empty.")
    if ext == "pdf" and not data.lstrip()[:5] == b"%PDF-":
        raise ExtractionError("The file does not look like a valid PDF.")
    if ext == "docx":
        if data[:2] != b"PK":
            raise ExtractionError("The file does not look like a valid DOCX document.")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" not in z.namelist():
                    raise ExtractionError("The file does not look like a valid DOCX document.")
        except zipfile.BadZipFile:
            raise ExtractionError("The DOCX file is corrupt.")
    if ext in ("txt", "csv") and b"\x00" in data[:4096]:
        raise ExtractionError("The file appears to be binary, not text.")
    return ext


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ExtractionError("The text file could not be decoded.")  # pragma: no cover


def _pdf(data: bytes) -> list[Page]:
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        raise ExtractionError("The PDF is corrupt or could not be opened.")
    try:
        if doc.needs_pass:
            raise ExtractionError("Password-protected PDFs are not supported.")
        return [Page(i + 1, page.get_text("text")) for i, page in enumerate(doc)]
    finally:
        doc.close()


def _docx(data: bytes) -> list[Page]:
    import docx

    try:
        d = docx.Document(io.BytesIO(data))
    except Exception:
        raise ExtractionError("The DOCX file is corrupt or could not be opened.")
    lines = [p.text for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                lines.append(" | ".join(cells))
    return [Page(None, "\n".join(lines))]


def _csv(data: bytes) -> list[Page]:
    import pandas as pd

    try:
        df = pd.read_csv(io.StringIO(_decode(data)), dtype=str, nrows=MAX_CSV_ROWS, keep_default_na=False)
    except Exception:
        raise ExtractionError("The CSV file could not be parsed.")
    if df.empty:
        raise ExtractionError("The CSV file has no rows.")
    cols = [str(c) for c in df.columns]
    lines = [f"Columns: {', '.join(cols)}"]
    for _, row in df.iterrows():
        lines.append("; ".join(f"{c}: {row[c]}" for c in df.columns if str(row[c]).strip()))
    return [Page(None, "\n".join(lines))]


def extract_pages(data: bytes, file_type: str) -> list[Page]:
    if file_type == "pdf":
        pages = _pdf(data)
    elif file_type == "docx":
        pages = _docx(data)
    elif file_type == "csv":
        pages = _csv(data)
    elif file_type == "txt":
        pages = [Page(None, _decode(data))]
    else:  # pragma: no cover
        raise ExtractionError("Unsupported file type.")
    cleaned = [Page(p.number, clean_text(p.text)) for p in pages]
    cleaned = [p for p in cleaned if p.text]
    if not cleaned:
        raise ExtractionError("No readable text was found in the file (it may be empty or scanned images).")
    return cleaned


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\x00", " ").replace("­", "")
    text = re.sub(r"-\n(?=[a-z])", "", text)           # de-hyphenate line-wrapped words
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
