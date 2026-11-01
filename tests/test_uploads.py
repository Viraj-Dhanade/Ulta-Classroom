from io import BytesIO
import unittest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from note_uploads import extract_notes, confirm_source, UploadError, OCR_MESSAGE, MAX_UPLOAD_BYTES
from prompts import SAMPLE_NOTES


def pdf_bytes(text=None, password=None, no_pages=False):
    writer = PdfWriter()
    if not no_pages:
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            stream = DecodedStreamObject()
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\n", " ")
            stream.set_data(f"BT /F1 12 Tf 50 700 Td ({escaped}) Tj ET".encode("latin1"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    if password:
        writer.encrypt(password)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def docx_bytes():
    doc = Document()
    doc.add_paragraph("Before the table.")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "BCC"
    table.cell(0, 1).text = "0.68"
    nested = table.cell(0, 1).add_table(rows=1, cols=1)
    nested.cell(0, 0).text = "Nested note"
    doc.add_paragraph("After the table.")
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


class UploadTests(unittest.TestCase):
    def test_pdf_text(self):
        self.assertEqual(extract_notes("Notes.PDF", pdf_bytes(SAMPLE_NOTES)), SAMPLE_NOTES.replace("\n", " "))

    def test_docx_tables_nested_and_order(self):
        text = extract_notes("notes.docx", docx_bytes())
        self.assertIn("BCC | 0.68", text)
        self.assertIn("Nested note", text)
        self.assertLess(text.index("Before"), text.index("BCC"))
        self.assertLess(text.index("BCC"), text.index("After"))

    def test_txt_encodings(self):
        for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-32"):
            text = "English notes. हिंदी आणि मराठी."
            self.assertEqual(extract_notes("notes.txt", text.encode(encoding)), text)
        self.assertEqual(extract_notes("notes.txt", "A learner’s notes".encode("cp1252")), "A learner’s notes")
        self.assertEqual(extract_notes("notes.txt", "Plain notes".encode("utf-16-le")), "Plain notes")

    def test_bad_files(self):
        for filename, data in (("empty.txt", b""), ("blank.txt", b"   "), ("bad.pdf", b"broken"), ("bad.docx", b"broken"), ("bad.exe", b"something"), ("binary.txt", b"\x01\x02\x03")):
            with self.subTest(filename=filename), self.assertRaises(UploadError):
                extract_notes(filename, data)

    def test_pdf_password_and_image_only(self):
        with self.assertRaisesRegex(UploadError, "password-protected"):
            extract_notes("locked.pdf", pdf_bytes("Some notes", password="test-only"))
        with self.assertRaises(UploadError) as caught:
            extract_notes("scanned.pdf", pdf_bytes())
        self.assertEqual(str(caught.exception), OCR_MESSAGE)
        with self.assertRaisesRegex(UploadError, "no pages"):
            extract_notes("empty.pdf", pdf_bytes(no_pages=True))

    def test_empty_and_encrypted_word(self):
        out = BytesIO()
        Document().save(out)
        with self.assertRaisesRegex(UploadError, "No readable text"):
            extract_notes("empty.docx", out.getvalue())
        with self.assertRaisesRegex(UploadError, "password-protected"):
            extract_notes("encrypted.docx", b"\xd0\xcf\x11\xe0" + b"test")

    def test_size_and_no_truncation(self):
        with self.assertRaisesRegex(UploadError, "10 MB"):
            extract_notes("large.txt", b"x" * (MAX_UPLOAD_BYTES + 1))
        text = SAMPLE_NOTES * 12
        self.assertGreater(len(text), 8000)
        self.assertEqual(extract_notes("long.txt", text.encode()), text)

    def test_confirm_resets_only_when_valid(self):
        state = {"lesson": object(), "voice_cache": {"old": b"audio"}, "answer_old": "draft", "record_old": b"audio", "transcript_old": "text"}
        old = state["lesson"]
        with self.assertRaises(ValueError):
            confirm_source(state, "short", "English")
        self.assertIs(state["lesson"], old)
        confirm_source(state, SAMPLE_NOTES, "English")
        self.assertEqual(state, {"confirmed_source": {"text": SAMPLE_NOTES, "language": "English"}})
