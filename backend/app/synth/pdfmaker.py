"""A tiny PDF writer for the sample contracts and tests: plain text lines in Helvetica, nothing else."""


def _escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(lines: list[str], *, empty: bool = False) -> bytes:
    """A one-page text PDF. `empty=True` makes a page with no text, like a scan."""
    body = "" if empty else "BT /F1 10 Tf 40 800 Td 13 TL " + " ".join(f"({_escape(ln)}) Tj T*" for ln in lines) + " ET"
    stream = body.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


CONTRACT_LINES = [
    "SUPPLY AGREEMENT - Sundaram Auto Parts",
    "1. Scope. The Supplier delivers goods to the Customer's nominated warehouse by the agreed due date.",
    "2. Late delivery. If an order is delivered after its due date, the Supplier shall pay liquidated damages at the",
    "rate of 2% of the order value per day of delay, capped at 10% of the order value.",
    "3. No penalty applies for a delay within a grace period of 3 days.",
    "4. The Customer may terminate an order if the delay exceeds 14 calendar days.",
    "5. A fixed penalty of Rs. 25,000 per late order applies to expedited orders, not to exceed Rs. 60,000.",
    "6. Neither party is liable for delay caused by events of force majeure.",
]
