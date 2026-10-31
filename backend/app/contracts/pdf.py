"""Text out of an uploaded PDF. Scanned images are not read (there is no OCR); the caller gets a plain reason."""
import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 60
MAX_CHARS = 200_000  # kept in the database; far more than any penalty section needs


class UnreadablePdf(Exception):
    """The message is safe to show to the user."""


def extract_text(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise UnreadablePdf(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    if not data.startswith(b"%PDF-"):
        raise UnreadablePdf("This does not look like a PDF file.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UnreadablePdf("The PDF is password protected. Remove the password and upload it again.")
        if len(reader.pages) > MAX_PAGES:
            raise UnreadablePdf(f"The PDF has more than {MAX_PAGES} pages.")
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except UnreadablePdf:
        raise
    except (PdfReadError, ValueError, KeyError, OSError, RecursionError, TypeError) as exc:
        raise UnreadablePdf("The PDF could not be read; it may be damaged.") from exc
    if len(text.strip()) < 40:
        raise UnreadablePdf("No text was found. Scanned or image-only PDFs are not supported; upload a text-based PDF.")
    return text[:MAX_CHARS]
