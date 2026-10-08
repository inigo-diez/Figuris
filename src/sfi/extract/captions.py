"""Detect figure/table caption candidates and grow them into caption blocks.

Detection is deliberately generous: in-text references that happen to start a
line ("Fig. 3 shows ...") also become low-scoring candidates. Region
assignment later keeps the candidate that actually sits next to graphics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sfi.extract.layout import Box, PageLayout, TextLine

LABEL_RE = re.compile(
    r"""^\s*
    (?P<prefix>(?:Extended\s+Data|Supplementary|Suppl\.?)\s+)?
    (?P<word>Figure|FIGURE|Fig\.?|FIG\.?|Table|TABLE|Scheme|SCHEME)
    \s*
    (?P<num>S?\d{1,3}[a-zA-Z]?|[IVXl]{1,5})
    (?![\w-])
    (?P<rest>.*)$""",
    re.VERBOSE,
)

ROMAN = {"I": 1, "V": 5, "X": 10}
STRONG_CAPTION_SCORE = 2.5
# Panel markers that open the next part of a caption: "a, ", "b. ", "(c)", "d)".
CONTINUATION_START = re.compile(r"^(\([a-z]\)|[a-z][,.)]\s)")


@dataclass
class CaptionCandidate:
    kind: str  # figure | table | scheme
    label: str  # normalized, e.g. "Figure 3", "Extended Data Figure 1"
    number: str
    score: float
    page_index: int
    lines: list[TextLine] = field(default_factory=list)
    continued_on_next_page: bool = False
    continuation_lines: list[TextLine] = field(default_factory=list)

    @property
    def box(self) -> Box:
        box = self.lines[0].box
        for line in self.lines[1:]:
            box = box.union(line.box)
        return box

    @property
    def text(self) -> str:
        return join_lines(self.lines + self.continuation_lines)


def join_lines(lines: list[TextLine]) -> str:
    text = ""
    for line in lines:
        part = line.stripped
        # pdfium reports soft hyphens at line ends as U+0002 or U+00AD.
        if text.endswith(("\x02", "­")) or text.endswith("-") and part[:1].islower():
            text = text[:-1] + part
        elif text:
            text += " " + part
        else:
            text = part
    return " ".join(text.split())


def normalize_number(raw: str) -> str:
    """Normalize '3', 'S2', 'IV' and the OCR confusion 'I'/'l' for '1'."""
    token = raw.replace("l", "I")
    if re.fullmatch(r"[IVX]+", token):
        total, prev = 0, 0
        for ch in reversed(token):
            value = ROMAN[ch]
            total = total - value if value < prev else total + value
            prev = max(prev, value)
        return str(total)
    return raw


def parse_label(text: str) -> tuple[str, str, str, str] | None:
    """Return (kind, normalized_label, number, rest) if text starts with a label."""
    match = LABEL_RE.match(text)
    if not match:
        return None
    word = match.group("word").lower().rstrip(".")
    kind = {"figure": "figure", "fig": "figure", "table": "table", "scheme": "scheme"}[word]
    number = normalize_number(match.group("num"))
    prefix = " ".join(match.group("prefix").split()) + " " if match.group("prefix") else ""
    noun = {"figure": "Figure", "table": "Table", "scheme": "Scheme"}[kind]
    return kind, f"{prefix}{noun} {number}", number, match.group("rest")


def normalize_label(label: str) -> str | None:
    """Normalize any label string (e.g. JATS 'Fig. 3 |') for comparison."""
    parsed = parse_label(label)
    return parsed[1] if parsed else None


def _line_above(line: TextLine, lines: list[TextLine]) -> TextLine | None:
    above = [
        other
        for other in lines
        if other is not line
        and other.box.y1 <= line.box.y0 + 0.5 * line.size
        and other.box.x_overlap(line.box) > 0.3 * min(other.box.width, line.box.width)
    ]
    return max(above, key=lambda other: other.box.y1, default=None)


def score_candidate(line: TextLine, rest: str, number_raw: str, layout: PageLayout) -> float:
    score = 0.0
    tail = rest.lstrip()
    if line.bold_prefix:
        score += 2.0
    if rest[:1] in {".", ":", "|"} or tail[:1] in {"|", "—", "–"} or not tail:
        score += 1.0
    elif tail[:1].isupper() or tail[:1] == "(":
        score += 0.5
    if (
        tail[:1].islower()
        or tail[:1] in {",", ")", ";"}
        or tail.lower().startswith(("and ", "to ", "or "))
    ):
        score -= 3.0
    if re.search(r"\d[a-zA-Z]$", number_raw):
        score -= 1.0
    if layout.body_size and line.size < layout.body_size - 0.3:
        score += 1.0
    above = _line_above(line, layout.lines)
    if above is None or line.box.y0 - above.box.y1 > 0.4 * line.size:
        score += 1.0
    return score


def find_caption_candidates(layout: PageLayout) -> list[CaptionCandidate]:
    candidates = []
    for line in layout.lines:
        parsed = parse_label(line.stripped)
        if parsed is None:
            continue
        kind, label, number, rest = parsed
        raw_number = LABEL_RE.match(line.stripped).group("num")
        score = score_candidate(line, rest, raw_number, layout)
        if score < 1.0:
            continue
        candidate = CaptionCandidate(
            kind=kind,
            label=label,
            number=number,
            score=score,
            page_index=layout.index,
            lines=[line],
        )
        grow_caption(candidate, layout)
        candidates.append(candidate)
    return candidates


def grow_caption(candidate: CaptionCandidate, layout: PageLayout) -> None:
    """Append the lines of the caption paragraph, including a second caption column.

    Some layouts (e.g. Springer) set wide captions in two columns that start at
    the same height; the right column continues the text of the left one.
    """
    used = {id(candidate.lines[0])}
    _grow_column(candidate, layout, candidate.lines[0], used)
    first = candidate.lines[0]
    while True:
        column = candidate.box
        starts = [
            line
            for line in layout.lines
            if id(line) not in used
            and abs(line.box.y0 - first.box.y0) < 0.5 * first.size
            and line.box.x0 > column.x1 + 4
            and line.box.x0 - column.x1 < 4 * first.size
            and abs(line.size - first.size) < 0.5
            and parse_label(line.stripped) is None
        ]
        if not starts:
            return
        start = min(starts, key=lambda line: line.box.x0)
        candidate.lines.append(start)
        used.add(id(start))
        _grow_column(candidate, layout, start, used)


def _grow_column(
    candidate: CaptionCandidate, layout: PageLayout, current: TextLine, used: set[int]
) -> None:
    column = current.box
    while True:
        following = [
            line
            for line in layout.lines
            if id(line) not in used
            and line.box.y0 > current.box.y0 + 0.3 * current.size
            and line.box.y0 - current.box.y1 < 0.75 * current.size
            and line.box.x_overlap(column.expand(4)) > 0.5 * line.box.width
            and abs(line.size - current.size) < (4.0 if layout.is_scanned else 1.5)
            and parse_label(line.stripped) is None
        ]
        if not following:
            return
        nxt = min(following, key=lambda line: line.box.y0)
        candidate.lines.append(nxt)
        used.add(id(nxt))
        column = column.union(Box(nxt.box.x0, column.y0, nxt.box.x1, column.y1))
        current = nxt


def attach_continuation(
    candidate: CaptionCandidate, layout: PageLayout, next_layout: PageLayout | None
) -> None:
    """Detect captions that run past the page bottom and pull the rest from the next page."""
    content = [ln for ln in layout.lines if ln.role != "margin"]
    if not content:
        return
    last = candidate.lines[-1]
    lowest = max(ln.box.y1 for ln in content)
    if last.box.y1 < lowest - 0.5 * last.size:
        return
    # A last line that ends a sentence well before the right edge of the text column
    # closes the paragraph: the caption is complete even at the page bottom, unless the
    # next page starts with a panel marker ("a, Left panel: ..."), as in captions whose
    # panel descriptions run onto the next page. Without this check, body text of the
    # next page, often set in the same size, would be taken as the continuation.
    column = candidate.box
    right_edge = max(
        [column.x1]
        + [
            ln.box.x1
            for ln in content
            if ln.char_count >= 40 and ln.box.x_overlap(column) > 0.5 * ln.box.width
        ]
    )
    finished = last.stripped.endswith((".", "!", "?")) and right_edge - last.box.x1 > 3 * last.size
    top_lines = sorted(
        (
            ln
            for ln in (next_layout.lines if next_layout else [])
            if ln.role != "margin" and ln.box.x_overlap(column) > 0.5 * ln.box.width
        ),
        key=lambda ln: ln.box.y0,
    )
    if finished and not (top_lines and CONTINUATION_START.match(top_lines[0].stripped)):
        return
    candidate.continued_on_next_page = True
    if next_layout is None:
        return
    block: list[TextLine] = []
    for line in top_lines:
        # A panel marker signals continued caption text even when the font size
        # differs from a bold caption title.
        continues = not block and CONTINUATION_START.match(line.stripped) is not None
        reference = block[0].size if block else last.size
        if parse_label(line.stripped) is not None or (
            abs(line.size - reference) > 0.6 and not continues
        ):
            break
        if block and line.box.y0 - block[-1].box.y1 > 0.75 * line.size:
            break
        block.append(line)
    candidate.continuation_lines = block
