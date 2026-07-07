import io

import pdfplumber
from docx import Document


SUPPORTED_RESUME_EXTENSIONS = {".pdf", ".doc", ".docx"}


def parse_resume(file_bytes: bytes, filename: str) -> str:
    lower = filename.lower()

    if lower.endswith(".pdf"):
        text_chunks = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_chunks.append(page_text)
        return "\n".join(text_chunks).strip()

    if lower.endswith(".docx"):
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text).strip()

    # Legacy .doc files are accepted for upload and storage. Text extraction
    # depends on file encoding and may not be available without external tools.
    try:
        return file_bytes.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""
