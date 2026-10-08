"""Article body text as passages (paragraphs) with pages, sections and positions.

Built from the page layouts of the figure extraction, which already separates
body text from captions, text inside figures and page margins. Lines are taken
in content-stream order, which follows the reading order in publisher PDFs.

A paragraph ends at a vertical gap, at a first-line indent after a finished
sentence, after a short last line, or at a section heading. A paragraph that
continues in the next column or page stays one passage; each column or page
portion is kept as a segment with its own box, so a quote can be located on
the right page.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from sfi.extract.captions import join_lines
from sfi.extract.layout import Box, PageLayout, TextLine

TEXT_VERSION = "text/0.1"

SECTION_NAMES = (
    r"abstract|summary|introduction|background|results?|discussion|"
    r"results and discussion|conclusions?|concluding remarks|methods|materials and methods|"
    r"material and methods|methods and materials|experimental( section| procedures)?|"
    r"online methods|patients and methods|subjects and methods|study design|"
    r"statistical analysis|limitations|references|bibliography|acknowledge?ments?|"
    r"author contributions|competing interests|conflicts? of interest|funding|"
    r"data availability|code availability|ethics statement|supplementary (information|material)|"
    r"additional information|abbreviations"
)
NUMBERING = r"(?:\d{1,2}(?:\.\d{1,2}){0,3}\.?|[IVX]{1,4}\.)\s+"
KNOWN_SECTION = re.compile(rf"^(?:{NUMBERING})?(?:{SECTION_NAMES})\s*:?$", re.IGNORECASE)
NUMBERED_HEADING = re.compile(rf"^{NUMBERING}[A-Z][^.!?]{{2,100}}$")
# Sections whose text is not about the figures (reference lists, declarations).
BACK_MATTER = re.compile(
    r"references|bibliography|acknowledge?ments?|author contributions|competing interests|"
    r"conflicts? of interest|funding|data availability|code availability|ethics statement|"
    r"additional information|abbreviations",
    re.IGNORECASE,
)
HEADING_STOPWORDS = {
    "and",
    "or",
    "of",
    "the",
    "a",
    "an",
    "in",
    "on",
    "for",
    "to",
    "with",
    "by",
    "from",
}
TERMINAL = (".", "!", "?", ":", ".)", '."', ".”")


@dataclass
class Segment:
    """The part of a passage on one page and column."""

    page_index: int
    char_start: int  # offset of the segment's first character in the passage text
    box: Box


@dataclass
class TextPassage:
    ordinal: int
    section: str | None
    back_matter: bool
    lines: list[tuple[int, TextLine]] = field(default_factory=list)  # (page_index, line)
    segments: list[Segment] = field(default_factory=list)
    text: str = ""

    @property
    def page_index(self) -> int:
        return self.lines[0][0]


def _inside(line: TextLine, boxes: list[Box]) -> bool:
    return any(line.box.x_overlap(b) * line.box.y_overlap(b) > 0.5 * line.box.area for b in boxes)


def is_heading(line: TextLine, layout: PageLayout, body_size: float) -> bool:
    text = line.stripped
    words = text.split()
    if not 1 <= len(words) <= 14 or len(text) > 120 or text.endswith((",", ";", "-")):
        return False
    if KNOWN_SECTION.match(text):
        return True
    if layout.is_scanned or not (text[:1].isupper() or NUMBERED_HEADING.match(text)):
        return False
    if (
        len(text) < 6  # badges such as "OPEN"
        or text.endswith(("(", "[", ":"))
        or words[-1].lower() in HEADING_STOPWORDS  # a title or author list cut mid-line
        or re.search(r"[A-Za-z]{2}\. [A-Z]", text)  # run-in heading followed by body text
        or re.search(r"[A-Za-z]\d", text)
        and "," in text  # author lists with affiliations
    ):
        return False
    emphasised = line.bold_prefix or (body_size and line.size >= 1.15 * body_size)
    return bool(emphasised and (NUMBERED_HEADING.match(text) or not text.endswith(".")))


def _ends_sentence(text: str) -> bool:
    return text.rstrip().endswith(TERMINAL)


def document_body_size(layouts: list[PageLayout]) -> float:
    """Most common size of body text in the whole document."""
    counts: Counter[float] = Counter()
    for layout in layouts:
        for line in layout.lines:
            if line.role == "body":
                counts[round(line.size * 2) / 2] += line.char_count
    return counts.most_common(1)[0][0] if counts else 0.0


def build_passages(
    layouts: list[PageLayout],
    figure_boxes: dict[int, list[Box]],
    caption_lines: set[int],
) -> list[TextPassage]:
    """Group body lines into passages.

    ``figure_boxes``: figure regions per page (text inside them is not body).
    ``caption_lines``: ids of the lines that belong to real captions; other lines the
    caption detector looked at (in-text references starting a line) are body text.

    Pages crowded with small text (tables, figure labels) can make the per-page body
    size of the figure extraction too small, so real paragraphs there were classified
    as figure text; lines outside figure regions with the document body size are
    taken back as body.
    """
    body_size = document_body_size(layouts)
    passages: list[TextPassage] = []
    section: str | None = None
    back_matter = False
    current: TextPassage | None = None
    prev: tuple[int, TextLine] | None = None

    def close() -> None:
        nonlocal current
        if current and current.lines:
            passages.append(current)
        current = None

    for layout in layouts:
        boxes = [b.expand(2) for b in figure_boxes.get(layout.index, [])]
        for line in layout.lines:
            if line.role == "margin" or id(line) in caption_lines or _inside(line, boxes):
                continue
            tolerance = 4.0 if layout.is_scanned else 1.0
            body_sized = abs(line.size - body_size) <= tolerance or (
                abs(line.size - layout.body_size) <= tolerance
            )
            # A body-role line is only a heading if it is a known section or bold.
            if is_heading(line, layout, body_size) and (
                line.role != "body" or KNOWN_SECTION.match(line.stripped) or line.bold_prefix
            ):
                close()
                section = " ".join(line.stripped.split())
                back_matter = bool(BACK_MATTER.search(section))
                prev = None
                continue
            reclaimed = (
                line.role in {"figure_text", "unknown"}
                and line.char_count >= 25
                and abs(line.size - body_size) <= tolerance
            )
            if (
                line.role != "body"
                and not reclaimed
                and not (line.role == "caption" and body_sized)
            ):
                continue
            if current is None or _breaks(prev, (layout.index, line), current):
                close()
                current = TextPassage(len(passages), section, back_matter)
            current.lines.append((layout.index, line))
            prev = (layout.index, line)
    close()
    for passage in passages:
        _finish(passage)
    return [p for p in passages if len(p.text) >= 20]


def _breaks(prev: tuple[int, TextLine] | None, cur: tuple[int, TextLine], passage) -> bool:
    if prev is None:
        return True
    (prev_page, a), (page, b) = prev, cur
    size = max(a.size, b.size, 1.0)
    finished = _ends_sentence(a.stripped)
    if page != prev_page or b.box.y0 < a.box.y0 - size:
        # Next page or next column: a paragraph continues unless the sentence ended.
        return finished
    if abs(b.box.y0 - a.box.y0) < 0.5 * size:
        return False  # same row (split line, inline equation)
    if b.box.y0 - a.box.y1 > 0.8 * size:
        return True
    if not finished:
        return False
    left = min(line.box.x0 for _, line in passage.lines[1:] or passage.lines)
    right = max(line.box.x1 for _, line in passage.lines)
    indented = b.box.x0 - left > 0.6 * size
    short_last = right - a.box.x1 > 4 * size
    return indented or short_last


def clean_text(text: str) -> str:
    """pdfium returns characters outside the BMP as UTF-16 surrogate pairs: combine
    them, and replace lone surrogates, which cannot be stored as UTF-8."""
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def _finish(passage: TextPassage) -> None:
    """Join the text and split it into page/column segments with their offsets."""
    groups: list[list[tuple[int, TextLine]]] = []
    for page, line in passage.lines:
        if groups:
            last_page, last = groups[-1][-1]
            same_column = page == last_page and line.box.y0 >= last.box.y0 - last.size
            if same_column:
                groups[-1].append((page, line))
                continue
        groups.append([(page, line)])
    text = ""
    for group in groups:
        lines = [line for _, line in group]
        part = clean_text(join_lines(lines))
        if text:
            joined = join_lines([_Fake(text), _Fake(part)])
            start = len(joined) - len(part)
            text = joined
        else:
            start, text = 0, part
        box = lines[0].box
        for line in lines[1:]:
            box = box.union(line.box)
        passage.segments.append(Segment(group[0][0], max(0, start), box))
    passage.text = text


@dataclass
class _Fake:
    """Minimal line stand-in so join_lines can glue two already-joined texts."""

    stripped: str


def passages_from_extraction(result) -> list[TextPassage]:
    """Passages for an ExtractionResult: figure regions and real captions are not body."""
    figure_boxes: dict[int, list[Box]] = {}
    caption_lines: set[int] = set()
    for figure in result.figures:
        if figure.box is not None:
            figure_boxes.setdefault(figure.page_index, []).append(figure.box)
        if figure.caption is not None:
            for line in figure.caption.lines + figure.caption.continuation_lines:
                caption_lines.add(id(line))
    for candidate in result.table_captions:
        caption_lines.update(id(line) for line in candidate.lines)
    return build_passages(result.pages, figure_boxes, caption_lines)
