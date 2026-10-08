"""Multipanel figures: split a figure into panels and link them to sub-captions (E02).

Baseline from the evaluation plan: whitespace (XY-cut) segmentation of the rendered
figure, guided by the panel letters of the caption. Most published figures are a
single raster image whose letters are drawn in pixels, so letters are given in
reading order, and boxes are only published when the number of panels matches the
letters of the caption; otherwise the figure stays whole and the panels keep only
their letter and sub-caption. Reading the drawn letters needs OCR (E03).

Everything works on a grayscale rendering of the figure region; boxes are pixel
coordinates of that rendering, top-left origin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

INK = 235  # gray level below which a pixel is content
PixelBox = tuple[int, int, int, int]  # x0, y0, x1, y1 (exclusive)

# --- sub-captions ------------------------------------------------------------------------

_LETTERS = r"[a-zA-Z](?:\s*(?:[-–—]|,|&|and)\s*[a-zA-Z])*"
_PAREN = re.compile(rf"\((?P<letters>{_LETTERS})\)")
# A bare marker opens a clause: "a Comparison", "b, Left", "A. Map", "c–e Quantification".
_BARE = re.compile(
    rf"(?:^|(?<=[.;:!?])\s*|(?<=[.;:!?)\]]\s))(?P<letters>{_LETTERS})(?P<punct>\s*[.,:)|])?\s+(?=\S)"
)
_RANGE = re.compile(r"([a-zA-Z])\s*[-–—]\s*([a-zA-Z])")


@dataclass
class SubCaption:
    labels: list[str]
    text: str
    start: int = 0  # offset of the marker in the caption


def _expand(letters: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"\s*(?:,|&|and)\s*", letters):
        match = _RANGE.fullmatch(part.strip())
        if match:
            a, b = match.groups()
            if a.islower() == b.islower() and ord(a) <= ord(b) and ord(b) - ord(a) < 12:
                out.extend(chr(c) for c in range(ord(a), ord(b) + 1))
        elif len(part.strip()) == 1:
            out.append(part.strip())
    return out


Marker = tuple[int, int, list[str]]  # start and end of the marker, letters


def _markers(caption: str) -> list[Marker]:
    found: list[Marker] = []
    for match in _PAREN.finditer(caption):
        letters = _expand(match.group("letters"))
        if letters:
            found.append((match.start(), match.end(), letters))
    for match in _BARE.finditer(caption):
        letters = _expand(match.group("letters"))
        if not letters:
            continue
        if letters[0].isupper() and not match.group("punct") and len(letters) == 1:
            continue
        if any(match.start("letters") < end and start < match.end() for start, end, _ in found):
            continue
        found.append((match.start("letters"), match.end(), letters))
    return sorted(found)


def _sequence(found: list[Marker], first: str) -> list[Marker]:
    """Markers that continue the sequence first, first+1... in order of appearance."""
    expected = ord(first)
    chosen = []
    for start, end, letters in found:
        if all(ord(x) == expected + i for i, x in enumerate(letters)):
            chosen.append((start, end, letters))
            expected += len(letters)
    return chosen


def _spans(text: str, markers: list[Marker]) -> list[tuple[list[str], str, int]]:
    out = []
    for i, (start, end, letters) in enumerate(markers):
        stop = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        out.append((letters, text[end:stop].strip(" ;,:"), start))
    return out


def parse_subcaptions(caption: str) -> tuple[str, list[SubCaption]]:
    """Split a caption into its common part and one sub-caption per panel marker.

    Markers must form the sequence a, b, c... (or A, B, C...) in order; later
    references such as "as in (a)" are not markers. Uppercase bare markers need
    punctuation ("A." or "A,") so that a sentence starting with "A" is not one.
    A group such as "(A-C) Micrographs of X. (A) 500x. (B) 2000x..." gives each
    panel the group's text followed by its own.
    """
    found = _markers(caption)
    best = max(
        (_sequence(found, first) for first in ("a", "A")), key=lambda c: sum(len(m[2]) for m in c)
    )
    if not best:
        return caption.strip(), []
    subs = []
    for letters, text, start in _spans(caption, best):
        inner = _sequence(_markers(text), letters[0]) if len(letters) > 1 else []
        if [x for m in inner for x in m[2]] == letters and all(len(m[2]) == 1 for m in inner):
            preface = text[: inner[0][0]].strip(" ;,:")
            for own_letters, own_text, _ in _spans(text, inner):
                joined = f"{preface} {own_text}".strip() if preface else own_text
                subs.append(SubCaption(labels=own_letters, text=joined, start=start))
        else:
            subs.append(SubCaption(labels=letters, text=text, start=start))
    return caption[: best[0][0]].strip(), subs


def caption_letters(caption: str) -> list[str]:
    return [label for sub in parse_subcaptions(caption)[1] for label in sub.labels]


# --- geometry ----------------------------------------------------------------------------


@dataclass
class SplitConfig:
    ink_contrast: int = 25  # difference from the background that counts as content
    noise: int = 2  # ink pixels tolerated in a gutter line (anti-aliasing, specks)...
    noise_fraction: float = 0.006  # ...or this fraction of the line, if larger
    min_gap_px: tuple[int, ...] = (16, 12, 8, 5, 3, 2)  # tried from coarse to fine
    min_side_fraction: float = 0.12  # thinner segments are merged into a neighbour
    min_side_px: int = 40


def _trim(mask: np.ndarray, box: PixelBox) -> PixelBox | None:
    x0, y0, x1, y1 = box
    sub = mask[y0:y1, x0:x1]
    rows = np.flatnonzero(sub.any(axis=1))
    cols = np.flatnonzero(sub.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        return None
    return (x0 + int(cols[0]), y0 + int(rows[0]), x0 + int(cols[-1]) + 1, y0 + int(rows[-1]) + 1)


def ink_masks(gray: np.ndarray, contrast: int = 25) -> list[np.ndarray]:
    """Content pixels under each plausible background.

    White first (most figures); then, if the border of the image is dark or gray,
    that colour too (black microscopy backgrounds). The border alone is not
    trusted because content often touches the edges of a tight crop.
    """
    masks = [gray < INK]
    border = np.concatenate(
        [gray[:2].ravel(), gray[-2:].ravel(), gray[:, :2].ravel(), gray[:, -2:].ravel()]
    )
    background = int(np.median(border))
    if background < INK - contrast:
        masks.append(np.abs(gray.astype(np.int16) - background) > contrast)
    return masks


def _gutters(profile: np.ndarray, noise: int, min_gap: int) -> list[tuple[int, int]]:
    """Runs of (almost) empty lines strictly inside the profile, at least min_gap long."""
    empty = profile <= noise
    runs, start = [], None
    for i, value in enumerate(empty):
        if value and start is None:
            start = i
        elif not value and start is not None:
            if i - start >= min_gap and start > 0:
                runs.append((start, i))
            start = None
    return runs


def _cut(
    mask: np.ndarray, box: PixelBox, axis: int, min_gap: int, config: SplitConfig, limit: int
) -> list[PixelBox]:
    """Split ``box`` across ``axis`` (0: horizontal cuts, 1: vertical cuts)."""
    x0, y0, x1, y1 = box
    sub = mask[y0:y1, x0:x1]
    profile = sub.sum(axis=1 if axis == 0 else 0)
    span = sub.shape[1] if axis == 0 else sub.shape[0]
    gutters = _gutters(profile, max(config.noise, int(config.noise_fraction * span)), min_gap)
    if not gutters:
        return [box]
    edges = [0] + [g for gutter in gutters for g in gutter] + [len(profile)]
    parts = [(edges[i], edges[i + 1]) for i in range(0, len(edges), 2)]
    gaps = [gutters[i][1] - gutters[i][0] for i in range(len(gutters))]
    # Merge thin parts (text lines, axis titles, panel letters on their own row)
    # into the neighbour across the narrower gap.
    while len(parts) > 1:
        sizes = [b - a for a, b in parts]
        thin = min(range(len(parts)), key=lambda i: sizes[i])
        if sizes[thin] >= limit:
            break
        if thin == 0:
            side = 0
        elif thin == len(parts) - 1:
            side = thin - 1
        else:
            side = thin - 1 if gaps[thin - 1] <= gaps[thin] else thin
        a, b = parts[side], parts[side + 1]
        parts[side : side + 2] = [(a[0], b[1])]
        del gaps[side]
    if axis == 0:
        return [(x0, y0 + a, x1, y0 + b) for a, b in parts]
    return [(x0 + a, y0, x0 + b, y1) for a, b in parts]


def xy_cut(mask: np.ndarray, min_gap: int, config: SplitConfig | None = None) -> list[PixelBox]:
    """Recursive whitespace segmentation; leaves in reading order (rows, then columns)."""
    config = config or SplitConfig()
    height, width = mask.shape
    limits = (
        max(config.min_side_px, int(config.min_side_fraction * height)),
        max(config.min_side_px, int(config.min_side_fraction * width)),
    )
    leaves: list[PixelBox] = []

    def recurse(box: PixelBox, depth: int) -> None:
        trimmed = _trim(mask, box)
        if trimmed is None:
            return
        if depth > 8:
            leaves.append(trimmed)
            return
        # Prefer horizontal cuts (rows) so that leaves come out in reading order.
        for axis in (0, 1):
            parts = _cut(mask, trimmed, axis, min_gap, config, limits[axis])
            if len(parts) > 1:
                for part in parts:
                    recurse(part, depth + 1)
                return
        leaves.append(trimmed)

    recurse((0, 0, width, height), 0)
    return leaves


def split_figure(
    gray: np.ndarray, expected: int | None = None, config: SplitConfig | None = None
) -> tuple[list[PixelBox], bool]:
    """Panels of a rendered figure and whether pieces had to be merged to get them.

    Without an expected number, the coarsest split. With the number of panels the
    caption announces, the split with the fewest pieces that reaches it, merged back
    down if needed (a panel often holds several images); else the finest split.
    """
    config = config or SplitConfig()
    candidates = [
        xy_cut(mask, gap, config)
        for mask in ink_masks(gray, config.ink_contrast)
        for gap in config.min_gap_px
    ]
    if not expected:
        return candidates[0], False
    exact = [boxes for boxes in candidates if len(boxes) == expected]
    if exact:
        return exact[0], False
    enough = [boxes for boxes in candidates if len(boxes) > expected]
    if not enough:
        return max(candidates, key=len), False
    boxes = min(enough, key=len)
    if len(boxes) == expected:
        return boxes, False
    return reading_order(merge_to(boxes, expected)), True


def _overlap(a: PixelBox, b: PixelBox) -> int:
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def _union(a: PixelBox, b: PixelBox) -> PixelBox:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _area(a: PixelBox) -> int:
    return (a[2] - a[0]) * (a[3] - a[1])


def merge_to(boxes: list[PixelBox], count: int) -> list[PixelBox]:
    """Merge neighbouring boxes until ``count`` remain, never creating overlaps.

    Each step merges the pair whose union wastes the least area (union minus the
    two boxes), so pieces of the same panel join before separate panels do.
    """
    boxes = list(boxes)
    while len(boxes) > count:
        best = None
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                union = _union(boxes[i], boxes[j])
                if any(
                    _overlap(union, boxes[k]) > 0.05 * _area(boxes[k])
                    for k in range(len(boxes))
                    if k not in (i, j)
                ):
                    continue
                waste = _area(union) - _area(boxes[i]) - _area(boxes[j])
                if best is None or waste < best[0]:
                    best = (waste, i, j, union)
        if best is None:
            break
        _, i, j, union = best
        boxes = [b for k, b in enumerate(boxes) if k not in (i, j)] + [union]
    return boxes


def reading_order(boxes: list[PixelBox]) -> list[PixelBox]:
    """Rows top to bottom (boxes overlapping vertically share a row), then left to right."""
    remaining = sorted(boxes, key=lambda b: (b[1], b[0]))
    ordered: list[PixelBox] = []
    while remaining:
        top = remaining[0]
        row = [b for b in remaining if b[1] < top[1] + 0.5 * (top[3] - top[1])]
        row.sort(key=lambda b: b[0])
        ordered.extend(row)
        remaining = [b for b in remaining if b not in row]
    return ordered


# --- figure-level result -----------------------------------------------------------------

CONFIDENCE_EXACT = 0.8  # the split gives the caption's number of panels directly
CONFIDENCE_MERGED = 0.6  # pieces had to be merged to reach it
# Boxes are shown to users only from this confidence. Against 185 human panel boxes (41
# figures, docs/reports/stage5-panels.md) direct splits were right for 73 % of panels and
# merged ones for 29 %; neither reaches the plan, so no boxes are shown yet. Letters and
# sub-captions (all correct) are always shown.
PUBLISH_MIN_CONFIDENCE = 0.9


@dataclass
class DetectedPanel:
    label: str
    box: PixelBox | None
    subcaption: str
    confidence: float


@dataclass
class PanelResult:
    layout: str  # single | split | unmatched (letters known, boxes not reliable)
    panels: list[DetectedPanel]
    common_caption: str = ""
    pieces: int = 0


def detect_panels(
    gray: np.ndarray | None, caption: str | None, config: SplitConfig | None = None
) -> PanelResult:
    """Panels of one figure from its rendering and caption.

    Figures whose caption names fewer than two panels are left whole. Letters are
    given to boxes in reading order, which is only trusted when the split yields
    exactly as many panels as the caption announces.
    """
    common, subs = parse_subcaptions(caption or "")
    labelled = [(label, sub.text) for sub in subs for label in sub.labels]
    if len(labelled) < 2:
        return PanelResult(layout="single", panels=[], common_caption=common)
    boxes, merged = split_figure(gray, len(labelled), config) if gray is not None else ([], False)
    if len(boxes) != len(labelled):
        return PanelResult(
            layout="unmatched",
            panels=[DetectedPanel(label, None, text, 0.0) for label, text in labelled],
            common_caption=common,
            pieces=len(boxes),
        )
    confidence = CONFIDENCE_MERGED if merged else CONFIDENCE_EXACT
    return PanelResult(
        layout="split",
        panels=[
            DetectedPanel(label, box, text, confidence)
            for (label, text), box in zip(labelled, boxes, strict=True)
        ],
        common_caption=common,
        pieces=len(boxes),
    )


# --- panels anchored on their printed letters ---------------------------------------------

CONFIDENCE_ANCHORED = 0.85  # every caption letter found printed in the figure


def letter_key(text: str) -> str:
    """'(a)', 'A.', 'b)' -> 'a', 'a', 'b'; anything else is not a lone panel letter."""
    return re.sub(r"[()\[\].,:;\s]", "", text).lower()


def _in_text(box: PixelBox, tokens: list[tuple[str, PixelBox, float]]) -> bool:
    """Is the token part of a line of text ("Subclade C and D", "Time (d)")?

    True when another token sits just to its left on the same line, or another short
    token just above or below it (vertical text read one letter at a time). A panel
    letter often has its title to the right, so that side does not count.
    """
    x0, y0, x1, y1 = box
    h = max(1, y1 - y0)
    for text, (a0, b0, a1, b1), _ in tokens:
        if (a0, b0, a1, b1) == box:
            continue
        rows = min(y1, b1) - max(y0, b0)
        cols = min(x1, a1) - max(x0, a0)
        if rows > 0.5 * min(h, b1 - b0) and a0 < x0 and x0 - 1.5 * h <= a1 <= x0 + 0.3 * h:
            return True
        stacked = 0 <= y0 - b1 <= 0.5 * h or 0 <= b0 - y1 <= 0.5 * h
        if cols > 0 and stacked and len(text.strip()) <= 2:
            return True
    return False


def _surrounding_ink(mask: np.ndarray, box: PixelBox) -> float:
    """Share of ink in a band left of and above the token: high inside a photo or a plot,
    low for a panel letter printed on the margin."""
    x0, y0, x1, y1 = box
    h = max(1, y1 - y0)
    left = mask[y0:y1, max(0, x0 - h) : x0]
    above = mask[max(0, y0 - h) : y0, max(0, x0 - h) : x1]
    total = left.size + above.size
    return float(left.sum() + above.sum()) / total if total else 0.0


def find_anchors(
    tokens: list[tuple[str, PixelBox, float]],
    letters: list[str],
    mask: np.ndarray | None = None,
) -> dict[str, PixelBox]:
    """The printed letter of each panel among the figure's text tokens.

    Candidates are tokens that read exactly one caption letter. Panel letters share a
    size, so candidates far from the typical height are dropped, and so are letters
    inside a line of text. Among the rest, one on a clear background (with ``mask``)
    beats one inside a photo or a plot, then the exact case wins, then the OCR
    confidence, then the top-left one.
    """
    wanted = {x.lower(): x for x in letters}
    candidates: dict[str, list[tuple[str, PixelBox, float]]] = {}
    for text, box, confidence in tokens:
        key = letter_key(text)
        if len(key) == 1 and key in wanted:
            candidates.setdefault(key, []).append((text, box, confidence))
    heights = sorted(b[3] - b[1] for found in candidates.values() for _, b, _ in found)
    if not heights:
        return {}
    typical = heights[len(heights) // 2]
    anchors = {}
    for key, found in candidates.items():
        sized = [
            t
            for t in found
            if 0.5 * typical <= t[1][3] - t[1][1] <= 2.0 * typical and not _in_text(t[1], tokens)
        ]
        if not sized:
            continue
        exact = wanted[key]

        def rank(t, exact=exact):
            clear = mask is None or _surrounding_ink(mask, t[1]) < CLEAR_INK
            return (clear, exact in t[0], t[2], -t[1][1], -t[1][0])

        anchors[exact] = max(sized, key=rank)[1]
    return anchors


CLEAR_INK = 0.15  # surrounding ink share below which a letter stands on a clear margin


def _labels_below(mask: np.ndarray, anchors: dict[str, PixelBox]) -> bool:
    """Do letters sit under their panel ("(a)" centred below a plot)?

    Votes on the ink close to each letter: a top-left letter has its panel starting
    just below and to the right of it; a letter under its panel has the plot right
    above it. The windows are short so the next row of panels does not count.
    """

    def ink(region: np.ndarray) -> float:
        return float(region.mean()) if region.size else 0.0

    below_votes = 0
    for x0, y0, x1, y1 in anchors.values():
        h = max(1, y1 - y0)
        reach = int(1.5 * h)
        diagonal = ink(mask[y1 : y1 + reach, x1 : x1 + reach])
        above = ink(mask[max(0, y0 - reach) : y0, max(0, x0 - h) : x1 + h])
        below_votes += above > 2 * max(diagonal, 1e-3)
    return below_votes > len(anchors) / 2


def letter_cut(
    mask: np.ndarray, anchors: dict[str, PixelBox], min_gap: int = 3
) -> list[tuple[PixelBox, list[str]]]:
    """Recursive whitespace cuts that never separate a panel from its letter.

    Only gutters with letters on both sides, a panel-sized region on each and a
    letter next to the gutter are cut, the widest first (rows or columns), so a tall
    panel spanning two rows of its neighbours stays whole and a letter printed under
    or beside its plot stays with it. Returns the regions with
    the letters they hold: one letter means one panel; several mean no gutter
    separates them.
    """
    config = SplitConfig()
    height, width = mask.shape
    size = sorted(b[3] - b[1] for b in anchors.values())[len(anchors) // 2] if anchors else 0
    leaves: list[tuple[PixelBox, list[str]]] = []

    def panel_sized(box: PixelBox) -> bool:
        trimmed = _trim(mask, box)
        return bool(trimmed) and min(trimmed[2] - trimmed[0], trimmed[3] - trimmed[1]) >= (
            MIN_PANEL_LETTERS * size
        )

    def recurse(box: PixelBox, keys: list[str], depth: int) -> None:
        trimmed = _trim(mask, box) or box
        if len(keys) <= 1 or depth > 12:
            leaves.append((trimmed, keys))
            return
        x0, y0, x1, y1 = trimmed
        sub = mask[y0:y1, x0:x1]
        best = None
        for axis in (0, 1):
            profile = sub.sum(axis=1 if axis == 0 else 0)
            span = sub.shape[1] if axis == 0 else sub.shape[0]
            noise = max(config.noise, int(config.noise_fraction * span))
            offset = y0 if axis == 0 else x0
            for a, b in _gutters(profile, noise, min_gap):
                cut = offset + (a + b) // 2
                before = [k for k in keys if anchors[k][3 - axis] <= cut]
                after = [k for k in keys if anchors[k][1 - axis] >= cut]
                if before and after and len(before) + len(after) == len(keys):
                    # The gutter must border a letter: the next panel's, starting just
                    # after it, or, between rows, the previous panel's printed under it.
                    start, end = 1 - axis, 3 - axis
                    reach = NEAR_LETTERS * size
                    if not (
                        any(anchors[k][start] - (offset + b) <= reach for k in after)
                        or axis == 0
                        and any((offset + a) - anchors[k][end] <= reach for k in before)
                    ):
                        continue
                    if axis == 0:
                        sides = ((x0, y0, x1, cut), (x0, cut, x1, y1))
                    else:
                        sides = ((x0, y0, cut, y1), (cut, y0, x1, y1))
                    if not all(panel_sized(side) for side in sides):
                        continue
                    if best is None or b - a > best[0]:
                        best = (b - a, axis, cut, before, after)
        if best is None:
            leaves.append((trimmed, keys))
            return
        _, axis, cut, before, after = best
        if axis == 0:
            recurse((x0, y0, x1, cut), before, depth + 1)
            recurse((x0, cut, x1, y1), after, depth + 1)
        else:
            recurse((x0, y0, cut, y1), before, depth + 1)
            recurse((cut, y0, x1, y1), after, depth + 1)

    recurse((0, 0, width, height), list(anchors), 0)
    return leaves


MIN_PANEL_LETTERS = 3  # a panel is at least this many letter heights wide and tall
NEAR_LETTERS = 1.5  # a cut between panels lies within this many letter heights of one


def anchored_split(mask: np.ndarray, anchors: dict[str, PixelBox], letters: list[str]):
    """One region per letter, trimmed to its ink.

    First whitespace cuts between letters (``letter_cut``). Letters that no gutter
    separates share a region, which is divided by the letters' positions
    (``grid_split``).
    """
    order = [x for x in letters if x in anchors]
    regions: dict[str, PixelBox] = {}
    for (x0, y0, x1, y1), keys in letter_cut(mask, {k: anchors[k] for k in order}):
        if len(keys) == 1:
            regions[keys[0]] = (x0, y0, x1, y1)
            continue
        local = {
            k: (a0 - x0, b0 - y0, a1 - x0, b1 - y0)
            for k, (a0, b0, a1, b1) in anchors.items()
            if k in keys
        }
        for key, (a0, b0, a1, b1) in grid_split(mask[y0:y1, x0:x1], local, letters):
            regions[key] = (a0 + x0, b0 + y0, a1 + x0, b1 + y0)
    return [(key, regions[key]) for key in order]


UNCOVERED_SHARE = 0.05  # share of the ink one reading must leave out beyond the other


def grid_split(mask: np.ndarray, anchors: dict[str, PixelBox], letters: list[str]):
    """One region per letter, bounded by the neighbouring letters, trimmed to its ink.

    Top-left letters: a panel runs right to the next letter of its row and down to the
    next letter whose panel overlaps its columns. Letters under their panels: rows of
    letters, each panel spans between the midpoints to its row neighbours and up to the
    previous row of letters. Both readings are built; the one that leaves clearly less
    ink outside the panels is kept.
    """
    height, width = mask.shape
    order = [x for x in letters if x in anchors]
    size = sorted(anchors[x][3] - anchors[x][1] for x in order)[len(order) // 2]
    row_tol = 1.5 * size

    def same_row(a: PixelBox, b: PixelBox) -> bool:
        return abs(a[1] - b[1]) <= row_tol

    below: dict[str, PixelBox] = {}
    rows: list[list[str]] = []
    for x in sorted(order, key=lambda k: (anchors[k][1], anchors[k][0])):
        for row in rows:
            if same_row(anchors[row[0]], anchors[x]):
                row.append(x)
                break
        else:
            rows.append([x])
    previous_bottom = 0
    for row in rows:
        row.sort(key=lambda k: anchors[k][0])
        centres = [(anchors[k][0] + anchors[k][2]) / 2 for k in row]
        for i, key in enumerate(row):
            left = 0 if i == 0 else int((centres[i - 1] + centres[i]) / 2)
            right = width if i == len(row) - 1 else int((centres[i] + centres[i + 1]) / 2)
            below[key] = (left, previous_bottom, right, anchors[key][3] + 1)
        previous_bottom = max(anchors[k][3] for k in row) + 1

    top_left: dict[str, PixelBox] = {}
    margin = max(2, size // 3)
    starts = {k: (max(0, anchors[k][0] - margin), max(0, anchors[k][1] - margin)) for k in order}
    rights = {}
    for k in order:
        x, _ = starts[k]
        to_right = [
            starts[j][0]
            for j in order
            if j != k and same_row(anchors[j], anchors[k]) and starts[j][0] > x
        ]
        rights[k] = min(to_right, default=width)
    for k in order:
        x, y = starts[k]
        lower = [
            starts[j][1]
            for j in order
            if j != k and starts[j][1] > y + row_tol and starts[j][0] < rights[k] and rights[j] > x
        ]
        top_left[k] = (x, y, rights[k], min(lower, default=height))

    # Whichever reading leaves clearly less ink outside every panel wins: letters at
    # the top leave the ink above the first row of letters out, letters at the bottom
    # the ink below the last. When neither does, the ink next to the letters decides.
    def uncovered(boxes: dict[str, PixelBox]) -> int:
        covered = np.zeros_like(mask, dtype=bool)
        for x0, y0, x1, y1 in boxes.values():
            covered[y0:y1, x0:x1] = True
        return int((mask & ~covered).sum())

    left_out = {"below": uncovered(below), "top": uncovered(top_left)}
    ink = max(1, int(mask.sum()))
    lesser, greater = sorted(left_out, key=left_out.get)
    if left_out[greater] - left_out[lesser] > UNCOVERED_SHARE * ink:
        boxes = below if lesser == "below" else top_left
    else:
        boxes = below if _labels_below(mask, anchors) else top_left
    out = []
    for key in order:
        trimmed = _trim(mask, boxes[key])
        out.append((key, trimmed or boxes[key]))
    return out


def detect_anchored_panels(
    gray: np.ndarray, caption: str | None, tokens: list[tuple[str, PixelBox, float]]
) -> PanelResult | None:
    """Panels from printed letters when every caption letter is found (or all but one,
    whose place is inferred from the grid of the others); else None."""
    common, subs = parse_subcaptions(caption or "")
    labelled = [(label, sub.text) for sub in subs for label in sub.labels]
    letters = [x for x, _ in labelled]
    if len(letters) < 2:
        return None
    mask = ink_masks(gray)[0]
    anchors = find_anchors(tokens, letters, mask)
    confidence = CONFIDENCE_ANCHORED
    missing = [x for x in letters if x not in anchors]
    if len(missing) == 1 and len(letters) >= 3:
        inferred = infer_anchor(anchors, letters, missing[0], gray.shape[1])
        if inferred is not None:
            anchors[missing[0]] = inferred
            confidence = CONFIDENCE_INFERRED
    if len(anchors) < len(letters):
        return None
    # An inferred letter is only roughly placed: cutting gutters next to it would
    # misplace panel edges, so its figure is divided by the letter grid alone.
    split = anchored_split if confidence == CONFIDENCE_ANCHORED else grid_split
    regions = dict(split(mask, anchors, letters))
    return PanelResult(
        layout="split",
        panels=[DetectedPanel(label, regions[label], text, confidence) for label, text in labelled],
        common_caption=common,
        pieces=len(regions),
    )


CONFIDENCE_INFERRED = 0.75  # one letter's place inferred from the grid of the others


def infer_anchor(
    anchors: dict[str, PixelBox], letters: list[str], missing: str, width: int
) -> PixelBox | None:
    """Where the one unread letter should be, assuming letters run in reading order
    (rows top to bottom, left to right) on a grid of rows and columns.

    The letter goes to the first free grid slot after the previous letter: further
    along the previous letter's row if a column exists there, else at the start of
    the next row. Returns None when the grid does not determine a place.
    """
    found = [x for x in letters if x in anchors]
    size = sorted(anchors[x][3] - anchors[x][1] for x in found)[len(found) // 2]
    tol = 1.5 * size

    def cluster(values: list[int]) -> list[int]:
        groups: list[list[int]] = []
        for v in sorted(values):
            if groups and v - groups[-1][-1] <= tol:
                groups[-1].append(v)
            else:
                groups.append([v])
        return [g[0] for g in groups]

    rows = cluster([anchors[x][1] for x in found])
    columns = cluster([anchors[x][0] for x in found])

    def slot(box: PixelBox) -> tuple[int, int]:
        row = min(range(len(rows)), key=lambda i: abs(rows[i] - box[1]))
        col = min(range(len(columns)), key=lambda i: abs(columns[i] - box[0]))
        return row, col

    taken = {slot(anchors[x]) for x in found}
    index = letters.index(missing)
    if index == 0:
        target = (0, 0)
    else:
        previous = anchors.get(letters[index - 1])
        if previous is None:
            return None
        row, col = slot(previous)
        later = [(row, c) for c in range(col + 1, len(columns))]
        target = next((s for s in later if s not in taken), None)
        if target is None and row + 1 < len(rows):
            target = (row + 1, 0)
    if target is None or target in taken:
        return None
    following = letters[index + 1] if index + 1 < len(letters) else None
    if following in anchors and slot(anchors[following]) <= target:
        return None  # the next letter would come before the inferred one: not a grid
    x, y = columns[target[1]], rows[target[0]]
    return (x, y, min(width, x + size), y + size)
