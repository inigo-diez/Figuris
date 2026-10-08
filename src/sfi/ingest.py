"""Validate untrusted PDF input before any processing."""

from __future__ import annotations

import pypdfium2 as pdfium


class InvalidDocumentError(Exception):
    """The input cannot be processed. ``code`` is stable for API/UI use."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_pdf_bytes(data: bytes, max_bytes: int) -> None:
    if not data:
        raise InvalidDocumentError("empty", "The file is empty.")
    if len(data) > max_bytes:
        raise InvalidDocumentError(
            "too_large",
            f"The file is {len(data) / 1e6:.1f} MB; the limit is {max_bytes / 1e6:.0f} MB.",
        )
    # The PDF header may be preceded by junk bytes; readers accept it within 1 KiB.
    if b"%PDF-" not in data[:1024]:
        raise InvalidDocumentError("not_pdf", "The file is not a PDF (missing %PDF- header).")


def open_pdf(data: bytes, max_pages: int) -> pdfium.PdfDocument:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        message = str(exc).lower()
        if "password" in message:
            raise InvalidDocumentError("encrypted", "The PDF is password protected.") from exc
        raise InvalidDocumentError("unreadable", f"The PDF cannot be parsed: {exc}") from exc
    if len(pdf) == 0:
        raise InvalidDocumentError("no_pages", "The PDF has no pages.")
    if len(pdf) > max_pages:
        raise InvalidDocumentError(
            "too_many_pages", f"The PDF has {len(pdf)} pages; the limit is {max_pages}."
        )
    return pdf
