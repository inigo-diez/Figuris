"""Render pages and figure regions to PNG."""

from __future__ import annotations

import io

import pypdfium2 as pdfium

from sfi.extract.layout import Box


def render_region_png(page: pdfium.PdfPage, box: Box, dpi: int, padding: float = 2.0) -> bytes:
    left, bottom, right, top = page.get_cropbox()
    width, height = right - left, top - bottom
    region = box.expand(padding).clip(width, height)
    # pdfium crops by the amount removed from each side: (left, bottom, right, top).
    crop = (region.x0, height - region.y1, width - region.x1, region.y0)
    image = page.render(scale=dpi / 72, crop=crop).to_pil()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_page_png(page: pdfium.PdfPage, dpi: int) -> bytes:
    image = page.render(scale=dpi / 72).to_pil()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
