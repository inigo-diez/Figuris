"""Build small, fully controlled PDFs for tests (no external tools).

Coordinates are PDF points with the origin at the bottom-left of the page.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PAGE_W, PAGE_H = 612, 792
LOREM = (
    "Results were consistent across all experimental replicates and the observed "
    "effects remained stable after correction for multiple comparisons in the cohort."
)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text(x: float, y: float, s: str, size: float = 10, bold: bool = False) -> str:
    font = "F2" if bold else "F1"
    return f"BT /{font} {size} Tf {x} {y} Td ({_escape(s)}) Tj ET\n"


def caption(x: float, y: float, label: str, body: str, size: float = 9) -> str:
    """A caption line with a bold label followed by regular text."""
    return (
        f"BT /F2 {size} Tf {x} {y} Td ({_escape(label)}) Tj /F1 {size} Tf "
        f"( {_escape(body)}) Tj ET\n"
    )


def rect(x: float, y: float, w: float, h: float, gray: float = 0.4) -> str:
    return f"{gray} g {x} {y} {w} {h} re f 0 g\n"


def paragraph(
    x: float, top: float, lines: int, width_chars: int = 95, size: float = 10, leading: float = 12
) -> str:
    """Body text: ``lines`` lines starting at ``top`` going down."""
    words = (LOREM + " ") * 4
    out = ""
    for i in range(lines):
        chunk = words[(i * 7) % 40 : (i * 7) % 40 + width_chars].strip()
        out += text(x, top - i * leading, chunk, size)
    return out


@dataclass
class Page:
    content: str = ""
    forms: dict[str, tuple[str, str]] = field(default_factory=dict)  # name -> (matrix, content)


def build_pdf(pages: list[Page]) -> bytes:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    add(b"")  # 1: catalog, filled below
    add(b"")  # 2: pages, filled below
    font_regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    page_ids = []
    for page in pages:
        xobjects = []
        for name, (matrix, content) in page.forms.items():
            data = content.encode("latin-1")
            form_id = add(
                b"<< /Type /XObject /Subtype /Form /BBox [-1000 -1000 3000 3000] /Matrix ["
                + matrix.encode()
                + b"] /Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> "
                % (font_regular, font_bold)
                + b"/Length %d >>\nstream\n" % len(data)
                + data
                + b"\nendstream"
            )
            xobjects.append(f"/{name} {form_id} 0 R")
        data = page.content.encode("latin-1")
        content_id = add(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")
        resources = (
            f"<< /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> "
            f"/XObject << {' '.join(xobjects)} >> >>"
        )
        page_ids.append(
            add(
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Resources {resources} /Contents {content_id} 0 R >>".encode()
            )
        )
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()

    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)
