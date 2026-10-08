"""Evidence layer: the text printed inside a figure, as tokens with a position (E03).

Each token keeps its text, its box on the page, a confidence and its producer:

- ``pdf``: words of the PDF text layer inside the figure (vector figures); exact;
- ``pdf-ocr``: the same on scanned pages, whose text layer is an old OCR;
- ``ocr:<engine>-<version>``: text read from the rendered figure (raster figures,
  scans), with the engine's confidence. OCR tokens that overlap an exact PDF word
  are dropped: the text layer of a born-digital PDF is authoritative where it exists.

The tokens let the validator check the numbers a claim says it reads in the figure,
and let a claim point to the exact place of a value. Panel letters found here can
anchor panel splitting later.

Boxes are page points with a top-left origin, relative to the crop box, like the
rest of the extractor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from sfi.extract.layout import Box

EVIDENCE_VERSION = "evidence/0.2"  # 0.2: OCR kept over the old text layer of scans
OCR_DPI = 200  # figure rendering for OCR; small axis labels need more than the 100 of panels
SCANNED_LAYER_CONFIDENCE = 0.7  # text layer of a scan: OCR made when the PDF was produced
_NUMBER = re.compile(r"[-−–]?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class TextToken:
    text: str
    box: Box
    confidence: float
    source: str  # "pdf" or "ocr:<engine>-<version>"


class OcrEngine(Protocol):
    name: str
    version: str

    def read(self, image: np.ndarray) -> list[tuple[str, list[list[float]], float]]:
        """Lines of text in an RGB image: (text, 4 corner points in pixels, confidence)."""
        ...


class RapidOcrEngine:
    """RapidOCR (Apache-2.0) on ONNX Runtime with PaddleOCR models; optional extra "ocr"."""

    name = "rapidocr"
    # Lower detection thresholds than the defaults (0.5): on the vector figures of E03
    # they read more small tick labels (number accuracy 0.90 -> 0.92 at 200 dpi).
    params = {"box_thresh": 0.3, "text_score": 0.3}

    def __init__(self) -> None:
        from importlib.metadata import version

        from rapidocr import RapidOCR

        self.version = version("rapidocr")
        self._engine = RapidOCR(params={"Global.log_level": "warning"})

    def read(self, image: np.ndarray) -> list[tuple[str, list[list[float]], float]]:
        """Words with their own boxes: adjacent tick labels read as one line ("350 400")
        must stay separate values."""
        # RapidOCR keeps the options of each call for the next ones, so every call sets
        # all the steps it uses (read_line turns detection off).
        result = self._engine(
            image, use_det=True, use_cls=True, use_rec=True, return_word_box=True, **self.params
        )
        if result is None or result.txts is None:
            return []
        out = []
        words_by_line = result.word_results or [()] * len(result.txts)
        for text, box, score, words in zip(
            result.txts, result.boxes, result.scores, words_by_line, strict=True
        ):
            if words:
                out.extend(
                    (str(word), np.asarray(word_box, dtype=float).tolist(), float(word_score))
                    for word, word_score, word_box in words
                )
            else:
                out.append((str(text), np.asarray(box, dtype=float).tolist(), float(score)))
        return out

    def read_line(self, image: np.ndarray) -> tuple[str, float]:
        """Recognition alone on an image holding one short text: detection often misses
        a lone letter, such as a panel letter in a corner."""
        result = self._engine(
            image, use_det=False, use_cls=False, use_rec=True, return_word_box=False, **self.params
        )
        if result is None or not result.txts:
            return "", 0.0
        return str(result.txts[0]), float(result.scores[0])


_SHARED: dict[str, OcrEngine | None] = {}


def default_ocr_engine() -> OcrEngine | None:
    """RapidOCR when the "ocr" extra is installed; else no OCR (PDF text only).

    Loading the models takes about a second, so one engine is shared by the process.
    """
    if "engine" not in _SHARED:
        try:
            _SHARED["engine"] = RapidOcrEngine()
        except ImportError:
            _SHARED["engine"] = None
    return _SHARED["engine"]


def ocr_engine_for(mode: str) -> OcrEngine | None:
    """The engine for a ``figure_ocr`` setting: auto, on or off."""
    if mode == "off":
        return None
    engine = default_ocr_engine()
    if engine is None and mode == "on":
        raise RuntimeError('SFI_FIGURE_OCR=on needs the "ocr" extra: pip install -e ".[ocr]"')
    return engine


def pdf_tokens(page: pdfium.PdfPage, region: Box, scanned: bool = False) -> list[TextToken]:
    """Words of the PDF text layer whose centre lies inside ``region``.

    On scanned pages the text layer was itself produced by OCR when the PDF was made:
    those words are marked ``pdf-ocr`` with a lower confidence instead of exact ``pdf``.
    """
    source, confidence = ("pdf-ocr", SCANNED_LAYER_CONFIDENCE) if scanned else ("pdf", 1.0)
    left, bottom, right, top = page.get_cropbox()
    height = top - bottom
    textpage = page.get_textpage()
    words: list[TextToken] = []
    current: list[tuple[str, Box]] = []

    def flush() -> None:
        if current:
            box = current[0][1]
            for _, b in current[1:]:
                box = box.union(b)
            words.append(TextToken("".join(c for c, _ in current), box, confidence, source))
            current.clear()

    try:
        for i in range(textpage.count_chars()):
            code = pdfium_c.FPDFText_GetUnicode(textpage, i)
            if pdfium_c.FPDFText_IsGenerated(textpage, i) == 1 or code in (0, 9, 10, 13, 32):
                flush()
                continue
            x0, y0, x1, y1 = textpage.get_charbox(i, loose=True)
            box = Box(x0 - left, height - (y1 - bottom), x1 - left, height - (y0 - bottom))
            if not (region.x0 <= box.cx <= region.x1 and region.y0 <= box.cy <= region.y1):
                flush()
                continue
            if current:
                last = current[-1][1]
                size = max(last.height, box.height, 1.0)
                if (
                    abs(box.cy - last.cy) > 0.5 * size
                    or not -0.5 * size < box.x0 - last.x1 < 0.3 * size
                ):
                    flush()
            current.append((chr(code), box))
        flush()
    finally:
        textpage.close()
    return words


def render_region(page: pdfium.PdfPage, region: Box, dpi: int) -> np.ndarray:
    """RGB rendering of ``region``; pixel (0, 0) is the region's top-left corner."""
    left, bottom, right, top = page.get_cropbox()
    width, height = right - left, top - bottom
    crop = (region.x0, height - region.y1, width - region.x1, region.y0)
    return page.render(scale=dpi / 72, crop=crop).to_numpy()[..., :3].copy()


def ocr_tokens(
    page: pdfium.PdfPage, region: Box, engine: OcrEngine, dpi: int = OCR_DPI
) -> list[TextToken]:
    image = render_region(page, region, dpi)
    scale = 72 / dpi
    tokens = []
    for text, quad, confidence in engine.read(image):
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        box = Box(
            region.x0 + min(xs) * scale,
            region.y0 + min(ys) * scale,
            region.x0 + max(xs) * scale,
            region.y0 + max(ys) * scale,
        )
        tokens.append(
            TextToken(
                text.strip(), box, round(confidence, 3), f"ocr:{engine.name}-{engine.version}"
            )
        )
    return [t for t in tokens if t.text]


def figure_tokens(
    page: pdfium.PdfPage,
    region: Box,
    engine: OcrEngine | None,
    dpi: int = OCR_DPI,
    scanned: bool = False,
) -> list[TextToken]:
    """PDF words inside the figure plus OCR text that no PDF word already covers."""
    native = pdf_tokens(page, region, scanned)
    if engine is None:
        return native
    # Only exact PDF words take precedence; the old OCR layer of a scan does not, since
    # it misreads values our OCR reads correctly (e.g. "9.3" in PMC1971548 Fig. 1).
    exact = [word for word in native if word.source == "pdf"]
    read = [
        token
        for token in ocr_tokens(page, region, engine, dpi)
        if not any(
            token.box.x_overlap(word.box) * token.box.y_overlap(word.box) > 0.5 * word.box.area
            for word in exact
        )
    ]
    return native + read


def numbers_in(text: str) -> list[str]:
    """Numbers as printed, with a normalized minus sign: '−0.5' -> '-0.5'."""
    return [n.replace("−", "-").replace("–", "-") for n in _NUMBER.findall(text)]


# 0.2: letters chosen outside lines of text, whitespace cuts between letters, lone
# letters read one by one
PANEL_ANCHORS_VERSION = "letter-anchors/0.2"
LETTER_UPSCALE = 3  # lone letters are read enlarged; at 100 dpi they are ~10 px tall
LETTER_MIN_SCORE = 0.5


def read_lone_letters(
    gray: np.ndarray,
    letters: list[str],
    engine: OcrEngine,
    size: int | None = None,
    dpi: int = 100,
) -> list[tuple[str, tuple[int, int, int, int], float]]:
    """Panel letters the OCR pass missed, read one ink blob at a time.

    Candidates are blobs of a letter's size with no other ink right around them (a
    letter inside a word or a label has neighbours). Each is enlarged and read by the
    recogniser alone; the ones that read as one of ``letters`` are returned as pixel
    tokens. ``size`` is the height of the letters already found, if any.
    """
    read_line = getattr(engine, "read_line", None)
    if read_line is None or not letters:
        return []
    import cv2

    from sfi.extract.panels import ink_masks, letter_key

    mask = ink_masks(gray)[0]
    # Same tolerance as find_anchors: OCR boxes of small letters are loose.
    low, high = (0.5 * size, 2.0 * size) if size else (0.07 * dpi, 0.25 * dpi)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    height, width = mask.shape
    wanted = {x.lower() for x in letters}
    found = []
    for i in range(1, count):
        x, y, w, h, _ = (int(v) for v in stats[i])
        if not (low <= h <= high and 0.2 * h <= w <= 1.5 * h):
            continue
        pad_x, pad_y = max(2, h // 2), max(2, h // 3)
        x0, y0 = max(0, x - pad_x), max(0, y - pad_y)
        x1, y1 = min(width, x + w + pad_x), min(height, y + h + pad_y)
        around = mask[y0:y1, x0:x1] & (labels[y0:y1, x0:x1] != i)
        if around.sum() > 2:
            continue
        margin = h // 2
        crop = gray[max(0, y - margin) : y + h + margin, max(0, x - margin) : x + w + margin]
        crop = cv2.resize(
            crop, None, fx=LETTER_UPSCALE, fy=LETTER_UPSCALE, interpolation=cv2.INTER_CUBIC
        )
        crop = cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        text, score = read_line(cv2.cvtColor(crop, cv2.COLOR_GRAY2RGB))
        if score >= LETTER_MIN_SCORE and letter_key(text) in wanted:
            found.append((text.strip(), (x, y, x + w, y + h), round(score, 3)))
    return found


def pixel_letter_tokens(
    gray: np.ndarray,
    caption: str,
    tokens: list[tuple[str, tuple[int, int, int, int], float]],
    engine: OcrEngine | None,
    dpi: int = 100,
) -> list[tuple[str, tuple[int, int, int, int], float]]:
    """``tokens`` plus the lone letters read for the caption letters not yet found."""
    from sfi.extract.panels import caption_letters, find_anchors, ink_masks

    letters = caption_letters(caption)
    if engine is None or len(letters) < 2:
        return tokens
    anchors = find_anchors(tokens, letters, ink_masks(gray)[0])
    missing = [x for x in letters if x not in anchors]
    if not missing:
        return tokens
    heights = sorted(b[3] - b[1] for b in anchors.values())
    size = heights[len(heights) // 2] if heights else None
    return tokens + read_lone_letters(gray, missing, engine, size, dpi)


def anchor_panels(
    page: pdfium.PdfPage,
    region: Box,
    caption: str,
    tokens: list[TextToken],
    dpi: int = 100,
    engine: OcrEngine | None = None,
) -> list[tuple[str, Box, str, float]] | None:
    """Panels around the letters printed in the figure (see panels.detect_anchored_panels).

    With an OCR ``engine``, caption letters missing from ``tokens`` are looked for
    among the lone letters of the figure (``read_lone_letters``). Returns (letter,
    page box, sub-caption, confidence) per panel, or None when the letters do not
    determine the panels; the whitespace split is kept then.
    """
    from sfi.extract.panels import detect_anchored_panels

    scale = dpi / 72
    in_pixels = [
        (
            t.text,
            (
                int((t.box.x0 - region.x0) * scale),
                int((t.box.y0 - region.y0) * scale),
                int((t.box.x1 - region.x0) * scale) + 1,
                int((t.box.y1 - region.y0) * scale) + 1,
            ),
            t.confidence,
        )
        for t in tokens
    ]
    gray = render_region(page, region, dpi).mean(axis=2).astype(np.uint8)
    in_pixels = pixel_letter_tokens(gray, caption, in_pixels, engine, dpi)
    result = detect_anchored_panels(gray, caption, in_pixels)
    if result is None:
        return None
    out = []
    for panel in result.panels:
        x0, y0, x1, y1 = panel.box
        box = Box(
            region.x0 + x0 / scale,
            region.y0 + y0 / scale,
            min(region.x1, region.x0 + x1 / scale),
            min(region.y1, region.y0 + y1 / scale),
        )
        out.append((panel.label, box, panel.subcaption, panel.confidence))
    return out
