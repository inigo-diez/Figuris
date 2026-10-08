"""Read text lines and graphic elements from a PDF page with pdfium.

Internal geometry uses page points with a TOP-LEFT origin (y grows downward),
relative to the page crop box. Conversion to PDF user space happens only when
results are persisted (see ``Box.to_pdf_bbox``).
"""

from __future__ import annotations

import ctypes
import statistics
from dataclasses import dataclass, field

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

SCANNED_IMAGE_COVERAGE = 0.8
MIN_ELEMENT_SIZE = 0.5


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    def union(self, other: Box) -> Box:
        return Box(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def expand(self, margin: float) -> Box:
        return Box(self.x0 - margin, self.y0 - margin, self.x1 + margin, self.y1 + margin)

    def intersects(self, other: Box) -> bool:
        return (
            self.x0 < other.x1 and other.x0 < self.x1 and self.y0 < other.y1 and other.y0 < self.y1
        )

    def x_overlap(self, other: Box) -> float:
        return max(0.0, min(self.x1, other.x1) - max(self.x0, other.x0))

    def y_overlap(self, other: Box) -> float:
        return max(0.0, min(self.y1, other.y1) - max(self.y0, other.y0))

    def clip(self, width: float, height: float) -> Box:
        return Box(max(0.0, self.x0), max(0.0, self.y0), min(width, self.x1), min(height, self.y1))

    def to_pdf_bbox(self, page_height: float) -> tuple[float, float, float, float]:
        """(left, bottom, right, top) in PDF points, origin bottom-left of the crop box."""
        return (self.x0, page_height - self.y1, self.x1, page_height - self.y0)


@dataclass
class TextLine:
    text: str
    box: Box
    size: float
    first_char_index: int
    char_count: int
    bold_prefix: bool = False
    role: str = "unknown"  # body | caption | figure_text | unknown

    @property
    def stripped(self) -> str:
        return self.text.strip()


@dataclass
class GraphicElement:
    box: Box
    kind: str  # image | path | shading | ink


@dataclass
class PageLayout:
    index: int
    width: float
    height: float
    rotation: int
    lines: list[TextLine]
    graphics: list[GraphicElement]
    is_scanned: bool
    body_size: float = 0.0
    content_box: Box | None = None
    images_full_page: int = 0
    extra: dict = field(default_factory=dict)


def _char_is_bold(textpage: pdfium.PdfTextPage, index: int) -> bool:
    weight = pdfium_c.FPDFText_GetFontWeight(textpage, index)
    if weight >= 600:
        return True
    buffer = ctypes.create_string_buffer(128)
    flags = ctypes.c_int()
    length = pdfium_c.FPDFText_GetFontInfo(
        textpage, index, buffer, len(buffer), ctypes.byref(flags)
    )
    if length <= 0:
        return False
    name = buffer.value.decode("utf-8", "ignore").lower()
    return any(token in name for token in ("bold", "black", "heavy", "semibold", "-b", ",b"))


def _flush_line(chars: list[tuple[str, Box | None, int]], textpage, lines: list[TextLine]) -> None:
    text = "".join(c for c, _, _ in chars)
    boxes = [b for _, b, _ in chars if b is not None]
    if not text.strip() or not boxes:
        return
    box = boxes[0]
    for b in boxes[1:]:
        box = box.union(b)
    heights = [b.height for _, b, _ in chars if b is not None and b.height > 0]
    size = statistics.median(heights) if heights else box.height
    first_index = chars[0][2]
    # Bold label: check the first non-space characters (e.g. "Fig. 3").
    visible = [idx for c, b, idx in chars if b is not None and not c.isspace()][:4]
    bold = bool(visible) and all(_char_is_bold(textpage, idx) for idx in visible)
    lines.append(
        TextLine(
            text=text,
            box=box,
            size=round(size, 2),
            first_char_index=first_index,
            char_count=len(text.strip()),
            bold_prefix=bold,
        )
    )


def read_text_lines(
    page: pdfium.PdfPage,
    page_height: float,
    origin: tuple[float, float],
    text_clips: dict[int, tuple[float, float, float, float]] | None = None,
) -> list[TextLine]:
    textpage = page.get_textpage()
    count = textpage.count_chars()
    ox, oy = origin
    lines: list[TextLine] = []
    current: list[tuple[str, Box | None, int]] = []
    last_box: Box | None = None

    for i in range(count):
        code = pdfium_c.FPDFText_GetUnicode(textpage, i)
        if code in (10, 13):
            # pdfium also emits line breaks where the baseline shifts (sub/superscripts);
            # whether the line really ends is decided by the geometry of the next glyph.
            continue
        char = chr(code) if code else ""
        generated = pdfium_c.FPDFText_IsGenerated(textpage, i) == 1
        box = None
        if not generated:
            left, bottom, right, top = textpage.get_charbox(i, loose=True)
            clip = _glyph_clip(textpage, i, text_clips)
            if clip is not None and not (
                clip[0] - 1 <= (left + right) / 2 <= clip[2] + 1
                and clip[1] - 1 <= (bottom + top) / 2 <= clip[3] + 1
            ):
                continue  # glyph hidden by a clip path
            if right > left and top > bottom:
                box = Box(
                    left - ox, page_height - (top - oy), right - ox, page_height - (bottom - oy)
                )
        if box is not None and last_box is not None:
            # Break when the next glyph is clearly not on the same line.
            size = max(last_box.height, box.height, 1.0)
            # Super/subscripts are shifted but still overlap the previous glyph vertically.
            same_line = abs(box.cy - last_box.cy) < 0.6 * size or box.y_overlap(
                last_box
            ) > 0.3 * min(box.height, last_box.height)
            near = -2 * size < box.x0 - last_box.x1 < 3 * size
            if not (same_line and near):
                _flush_line(current, textpage, lines)
                current = []
        current.append((char, box, i))
        if box is not None:
            last_box = box
    _flush_line(current, textpage, lines)
    textpage.close()
    return _drop_duplicate_lines(lines)


def _glyph_clip(textpage, index: int, text_clips: dict | None):
    if not text_clips:
        return None
    obj = pdfium_c.FPDFText_GetTextObject(textpage, index)
    return text_clips.get(ctypes.addressof(obj.contents)) if obj else None


def _drop_duplicate_lines(lines: list[TextLine]) -> list[TextLine]:
    """Remove text drawn twice at the same place (hidden layers, fake bold).

    Some publishers emit an invisible copy of captions; keep the longest copy.
    """
    kept: list[TextLine] = []
    for line in sorted(lines, key=lambda ln: -ln.char_count):
        prefix = line.stripped[:12]
        duplicate = any(
            other.box.y_overlap(line.box) > 0.5 * min(other.box.height, line.box.height)
            and other.box.x_overlap(line.box) > 0.8 * line.box.width
            and other.stripped.startswith(prefix)
            for other in kept
        )
        if not duplicate:
            kept.append(line)
    return sorted(kept, key=lambda ln: ln.first_char_index)


Affine = tuple[float, float, float, float, float, float]
IDENTITY: Affine = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _compose(inner: Affine, outer: Affine) -> Affine:
    """Matrix applying ``inner`` first, then ``outer`` (PDF row-vector convention)."""
    a, b, c, d, e, f = inner
    A, B, C, D, E, F = outer
    return (
        a * A + b * C,
        a * B + b * D,
        c * A + d * C,
        c * B + d * D,
        e * A + f * C + E,
        e * B + f * D + F,
    )


def _transform_bounds(
    bounds: tuple[float, float, float, float], m: Affine
) -> tuple[float, float, float, float]:
    if m == IDENTITY:
        return bounds
    left, bottom, right, top = bounds
    a, b, c, d, e, f = m
    xs, ys = [], []
    for x, y in ((left, bottom), (left, top), (right, bottom), (right, top)):
        xs.append(a * x + c * y + e)
        ys.append(b * x + d * y + f)
    return min(xs), min(ys), max(xs), max(ys)


Bounds = tuple[float, float, float, float]  # (left, bottom, right, top) in PDF page space


@dataclass
class _PlacedObject:
    obj: pdfium.PdfObject
    to_page: Affine
    clip: Bounds | None  # effective clip rectangle in page space, if any


def _clip_bounds(raw_obj) -> Bounds | None:
    """Bounding box of an object's clip path, in the object's coordinate space."""
    clip = pdfium_c.FPDFPageObj_GetClipPath(raw_obj)
    if not clip:
        return None
    xs: list[float] = []
    ys: list[float] = []
    x, y = ctypes.c_float(), ctypes.c_float()
    for path_index in range(pdfium_c.FPDFClipPath_CountPaths(clip)):
        for seg_index in range(pdfium_c.FPDFClipPath_CountPathSegments(clip, path_index)):
            segment = pdfium_c.FPDFClipPath_GetPathSegment(clip, path_index, seg_index)
            if pdfium_c.FPDFPathSegment_GetPoint(segment, ctypes.byref(x), ctypes.byref(y)):
                xs.append(x.value)
                ys.append(y.value)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def _intersect(a: Bounds | None, b: Bounds | None) -> Bounds | None:
    if a is None:
        return b
    if b is None:
        return a
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def place_objects(page: pdfium.PdfPage) -> list[_PlacedObject]:
    """All page objects with their page-space matrix and effective clip.

    pdfium reports bounds and clip paths of objects nested in Form XObjects in
    the form's own coordinate space; the matrices of enclosing forms are
    applied here. Clips matter: publishers embed figures by importing a whole
    page of another PDF and clipping it, which leaves invisible text and
    graphics outside the clip.
    """
    to_page: dict[int, Affine] = {0: IDENTITY}
    inherited: dict[int, Bounds | None] = {0: None}
    placed = []
    for obj in page.get_objects(max_depth=15):
        matrix = to_page.get(obj.level, IDENTITY)
        own = _clip_bounds(obj.raw)
        clip = _intersect(inherited.get(obj.level), _transform_bounds(own, matrix) if own else None)
        placed.append(_PlacedObject(obj, matrix, clip))
        if obj.type == pdfium_c.FPDF_PAGEOBJ_FORM:
            to_page[obj.level + 1] = _compose(tuple(obj.get_matrix().get()), matrix)
            inherited[obj.level + 1] = clip
    return placed


def read_graphics(
    placed: list[_PlacedObject], width: float, height: float, origin: tuple[float, float]
) -> tuple[list[GraphicElement], int]:
    """Return visible leaf graphic objects and the number of near full-page images."""
    ox, oy = origin
    page_area = width * height
    kinds = {
        pdfium_c.FPDF_PAGEOBJ_IMAGE: "image",
        pdfium_c.FPDF_PAGEOBJ_PATH: "path",
        pdfium_c.FPDF_PAGEOBJ_SHADING: "shading",
    }
    elements: list[GraphicElement] = []
    full_page_images = 0
    for item in placed:
        kind = kinds.get(item.obj.type)
        if kind is None:
            continue
        bounds = _intersect(_transform_bounds(item.obj.get_bounds(), item.to_page), item.clip)
        left, bottom, right, top = bounds
        box = Box(left - ox, height - (top - oy), right - ox, height - (bottom - oy)).clip(
            width, height
        )
        if box.width <= 0 or box.height <= 0:
            continue  # clipped away or outside the visible page
        if box.width < MIN_ELEMENT_SIZE and box.height < MIN_ELEMENT_SIZE:
            continue
        if kind != "image" and box.area > 0.5 * page_area:
            continue
        if box.area > SCANNED_IMAGE_COVERAGE * page_area:
            if kind == "image":
                full_page_images += 1
            # Page backgrounds and full-page clips are not figure content.
            continue
        elements.append(GraphicElement(box=box, kind=kind))
    return elements, full_page_images


def read_page_layout(page: pdfium.PdfPage, index: int) -> PageLayout:
    left, bottom, right, top = page.get_cropbox()
    width, height = right - left, top - bottom
    origin = (left, bottom)
    page_box = Box(0, 0, width, height)
    # Text placed outside the crop box is never displayed (e.g. leftover layers).
    placed = place_objects(page)
    text_clips = {
        ctypes.addressof(p.obj.raw.contents): p.clip
        for p in placed
        if p.obj.type == pdfium_c.FPDF_PAGEOBJ_TEXT and p.clip is not None
    }
    lines = [
        ln
        for ln in read_text_lines(page, height, origin, text_clips)
        if ln.box.x_overlap(page_box) * ln.box.y_overlap(page_box) > 0.5 * ln.box.area
    ]
    graphics, full_page_images = read_graphics(placed, width, height, origin)
    return PageLayout(
        index=index,
        width=width,
        height=height,
        rotation=page.get_rotation(),
        lines=lines,
        graphics=graphics,
        is_scanned=full_page_images > 0,
        images_full_page=full_page_images,
    )
