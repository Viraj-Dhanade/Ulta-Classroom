"""In-memory extraction and explicit source confirmation; no document logging."""
from io import BytesIO
import logging
from pathlib import PurePath
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
OCR_MESSAGE = "This PDF needs OCR. Please upload a text-based PDF or paste the text."
# Malformed-file library diagnostics can contain fragments of uploaded content.
logging.getLogger("pypdf").setLevel(logging.CRITICAL + 1)


class UploadError(ValueError):
    pass


def _txt(data):
    if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encoding = "utf-32"
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif b"\x00" in data:
        if len(data) % 2 == 0 and data[1::2].count(0) > len(data) * .3:
            encoding = "utf-16-le"
        elif len(data) % 2 == 0 and data[::2].count(0) > len(data) * .3:
            encoding = "utf-16-be"
        else:
            raise UploadError("This TXT file appears to contain binary data. Save it as UTF-8 text and try again.")
    else:
        try:
            return _readable(data.decode("utf-8-sig"))
        except UnicodeDecodeError:
            encoding = "cp1252"
    try:
        return _readable(data.decode(encoding))
    except UnicodeError:
        raise UploadError("Could not decode this TXT file. Save it as UTF-8 text and try again.") from None


def _readable(text):
    if any((ord(c) < 32 and c not in "\n\r\t") or 127 <= ord(c) < 160 for c in text):
        raise UploadError("This TXT file contains unsupported control characters. Save it as UTF-8 text and try again.")
    return text


def _blocks(container):
    for block in container.iter_inner_content():
        if isinstance(block, Paragraph):
            yield block.text
        elif isinstance(block, Table):
            seen = set()
            for row in block.rows:
                cells = []
                for cell in row.cells:
                    if cell._tc not in seen:
                        seen.add(cell._tc)
                        cells.append("\n".join(_blocks(cell)))
                yield " | ".join(cells)


def extract_notes(filename, data):
    suffix = PurePath(filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt"):
        raise UploadError("Unsupported file type. Upload one PDF, DOCX, or TXT file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError("The file is too large. Upload a file up to 10 MB.")
    if not data:
        raise UploadError("This file is empty. Upload a document containing study notes.")
    try:
        if suffix == ".txt":
            text = _txt(data)
        elif suffix == ".pdf":
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise UploadError("This PDF is password-protected. Upload an unlocked copy or paste the text.")
            if not reader.pages:
                raise UploadError("This PDF has no pages. Upload a document containing study notes.")
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            if not text.strip():
                raise UploadError(OCR_MESSAGE)
        else:
            if data.startswith(b"\xd0\xcf\x11\xe0"):
                raise UploadError("This document is password-protected or an older Word format. Upload an unlocked DOCX or paste the text.")
            with ZipFile(BytesIO(data)) as archive:
                if any(item.flag_bits & 1 for item in archive.infolist()):
                    raise UploadError("This DOCX is password-protected. Upload an unlocked copy or paste the text.")
                if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                    raise UploadError("This DOCX expands to too much data. Export a smaller section or paste the text.")
            text = "\n".join(_blocks(Document(BytesIO(data))))
    except UploadError:
        raise
    except Exception:
        raise UploadError(f"Could not read this {suffix[1:].upper()} file. It may be corrupted or not a valid document. Upload another copy or paste the text.") from None
    if not text.strip():
        raise UploadError("No readable text was found. Upload a document containing study notes or paste the text.")
    return text.strip()


def confirm_source(state, text, language):
    """Called only after explicit confirmation and notes validation, before API calls."""
    from classroom import validate_notes
    validate_notes(text)
    for key in list(state):
        if key in ("lesson", "voice_cache", "source_edit") or key.startswith(("answer_", "record_", "transcript_")):
            del state[key]
    state["confirmed_source"] = {"text": text, "language": language}
