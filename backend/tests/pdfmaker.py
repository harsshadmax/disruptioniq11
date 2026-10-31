"""The PDF writer lives in the app (the showcase seeder uses it too); tests import it from here."""
from app.synth.pdfmaker import CONTRACT_LINES, make_pdf  # noqa: F401
