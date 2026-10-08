"""Group page content into figure regions and assign them to captions.

Pipeline per page:

1. classify text lines: margin (running headers/footers), caption, body,
   figure_text (short labels inside figures);
2. rasterize graphic elements (or ink, for scanned pages) and figure text
   onto an occupancy grid where body and caption lines act as walls;
3. dilate and label connected components -> clusters;
4. assign each cluster to the nearest compatible caption (figure or table);
5. absorb leftover clusters that touch an assigned region.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from sfi.extract.captions import CaptionCandidate
from sfi.extract.grid import Grid, dilate, label_components
from sfi.extract.layout import Box, PageLayout, TextLine

MARGIN_BAND = 0.06
MIN_REGION_SIDE = 12.0
MAX_CAPTION_GAP = 0.25  # fraction of page height
ABSORB_GAP = 30.0


@dataclass
class RegionConfig:
    cell: float = 2.0
    merge_gap: float = 16.0
    merge_gap_scanned: float = 8.0
    ink_render_scale: float = 1.0
    blocking_line_tolerance: int = 2
    text_attach_gap: float = 10.0
    text_chain_gap: float = 2.0


@dataclass
class Cluster:
    box: Box
    has_graphic: bool
    element_count: int
    images: int = 0
    paths: int = 0
    image_area: float = 0.0
    caption: CaptionCandidate | None = None
    cost: float | None = None
    relation: str | None = None

    def looks_like_figure(self, layout: PageLayout) -> bool:
        """Is an uncaptioned region plausibly a figure (not a text box, table, logo or form)?

        Reported uncaptioned regions are warnings for the user, so this errs on
        the side of precision: publisher banners, abstract boxes, checklists and
        tables are mostly text with little imagery.
        """
        area = self.box.area
        if area < 0.03 * layout.width * layout.height:
            return False
        overlapping = [
            ln
            for ln in layout.lines
            if ln.role in {"body", "figure_text", "caption"}
            and ln.box.x_overlap(self.box) * ln.box.y_overlap(self.box) > 0.5 * ln.box.area
        ]
        body_lines = sum(1 for ln in overlapping if ln.role in {"body", "caption"})
        # Text area clipped to the region, counting lines that only partly enter it.
        text_ratio = (
            sum(
                ln.box.x_overlap(self.box) * ln.box.y_overlap(self.box)
                for ln in layout.lines
                if ln.role != "margin"
            )
            / area
        )
        if body_lines > 3:
            return False
        if layout.is_scanned:
            return text_ratio < 0.25
        return (self.image_area >= 0.4 * area and text_ratio < 0.3) or (
            self.paths >= 30 and text_ratio < 0.25
        )


@dataclass
class PageRegions:
    clusters: list[Cluster]
    assigned: dict[int, list[Cluster]] = field(default_factory=dict)  # id(caption) -> clusters


def mark_margins(layout: PageLayout) -> None:
    band = MARGIN_BAND * layout.height
    for line in layout.lines:
        if (
            line.box.y1 < band
            or line.box.y0 > layout.height - band
            or (
                line.box.x1 < MARGIN_BAND * layout.width
                or line.box.x0 > (1 - MARGIN_BAND) * layout.width
                or line.box.height > 6 * max(line.box.width, 1)
                and (line.box.x1 < 0.1 * layout.width or line.box.x0 > 0.9 * layout.width)
            )
        ):
            line.role = "margin"


def estimate_body_size(layout: PageLayout) -> float:
    counts: Counter[float] = Counter()
    for line in layout.lines:
        if line.role != "margin":
            counts[round(line.size * 2) / 2] += line.char_count
    return counts.most_common(1)[0][0] if counts else 0.0


LEGEND_MARKER = re.compile(r"^\s*([-–—.·•○●■□▲△◆◇*]\s*){2,}")


def classify_body(layout: PageLayout) -> None:
    """Mark body text; everything left unclassified becomes figure_text."""
    for line in layout.lines:
        # Legend entries such as "--- USA White" or "···· Japan" belong to figures.
        if line.role == "unknown" and LEGEND_MARKER.match(line.text):
            line.role = "figure_text"
    content = [ln for ln in layout.lines if ln.role == "unknown" and ln.char_count >= 20]
    if content:
        content_width = max(ln.box.x1 for ln in content) - min(ln.box.x0 for ln in content)
    else:
        content_width = layout.width
    layout.content_box = Box(0, 0, layout.width, layout.height)

    def body_sized(line: TextLine) -> bool:
        return abs(line.size - layout.body_size) <= (4.0 if layout.is_scanned else 1.0)

    for line in layout.lines:
        if (
            line.role == "unknown"
            and line.char_count >= 40
            and body_sized(line)
            and line.box.width >= 0.35 * content_width
        ):
            line.role = "body"
    _mark_paragraph_stacks(layout, body_sized)

    # Short lines inside a paragraph (last lines, headings glued to text) are body too.
    changed = True
    while changed:
        changed = False
        body = [ln for ln in layout.lines if ln.role == "body"]
        for line in layout.lines:
            if line.role != "unknown" or not body_sized(line):
                continue
            for other in body:
                vertical_gap = max(other.box.y0 - line.box.y1, line.box.y0 - other.box.y1)
                if vertical_gap < 0.5 * line.size and line.box.x_overlap(other.box) > 0.5 * min(
                    line.box.width, other.box.width
                ):
                    line.role = "body"
                    changed = True
                    break

    for line in layout.lines:
        if line.role == "unknown":
            line.role = "figure_text"


def _mark_paragraph_stacks(layout: PageLayout, body_sized) -> None:
    """Narrow text columns beside figures: 3+ left-aligned lines of prose are body text.

    Labels inside figures rarely form runs of long, left-aligned lines with a
    regular line pitch.
    """
    candidates = sorted(
        (ln for ln in layout.lines if ln.role == "unknown" and body_sized(ln)),
        key=lambda ln: ln.box.y0,
    )
    used: set[int] = set()
    for start in candidates:
        if id(start) in used:
            continue
        stack = [start]
        for line in candidates:
            last = stack[-1]
            if id(line) in used or line is last or line.box.y0 <= last.box.y0:
                continue
            gap = line.box.y0 - last.box.y1
            if abs(line.box.x0 - start.box.x0) <= 3 and -0.5 * line.size < gap < 0.6 * line.size:
                stack.append(line)
        long_lines = [ln for ln in stack if ln.char_count >= 25]
        if len(stack) >= 3 and len(long_lines) >= 0.6 * len(stack):
            for line in stack:
                line.role = "body"
                used.add(id(line))


def _in_margin(box: Box, layout: PageLayout) -> bool:
    """Running headers/footers, publisher bars and side banners."""
    band = MARGIN_BAND * layout.height
    side = MARGIN_BAND * layout.width
    return (
        box.y1 <= band
        or box.y0 >= layout.height - band
        or box.x1 <= side
        or box.x0 >= layout.width - side
    )


def _is_rule(box: Box, layout: PageLayout) -> bool:
    """Thin horizontal/vertical lines spanning much of the page (separators)."""
    return (box.height <= 2.5 and box.width >= 0.4 * layout.width) or (
        box.width <= 2.5 and box.height >= 0.4 * layout.height
    )


def _ink_mask(page_image: np.ndarray, layout: PageLayout, grid: Grid, scale: float) -> np.ndarray:
    """Cells containing dark pixels outside body/caption/margin text."""
    gray = page_image.astype(np.int16)
    background = int(np.median(gray))
    ink = gray < min(200, background - 60)
    for line in layout.lines:
        if line.role in {"body", "caption", "margin"}:
            # OCR boxes are tight; scanned glyphs (ascenders, bold, blur) spill past them.
            pad = 0.4 * line.box.height
            b = Box(line.box.x0 - 3, line.box.y0 - pad, line.box.x1 + 3, line.box.y1 + pad)
            ink[
                max(0, int(b.y0 * scale)) : int(b.y1 * scale) + 1,
                max(0, int(b.x0 * scale)) : int(b.x1 * scale) + 1,
            ] = False
    cells = grid.empty()
    step = grid.cell * scale
    ys, xs = np.nonzero(ink)
    cells[
        (ys / step).astype(int).clip(0, grid.rows - 1),
        (xs / step).astype(int).clip(0, grid.cols - 1),
    ] = True
    return cells


def build_clusters(
    layout: PageLayout, config: RegionConfig, page_image: np.ndarray | None = None
) -> list[Cluster]:
    grid = Grid(layout.width, layout.height, config.cell)
    occupancy = grid.empty()
    walls = grid.empty()

    for line in layout.lines:
        if line.role in {"body", "caption"}:
            shrink = 0.2 * line.box.height
            grid.fill(
                walls, Box(line.box.x0, line.box.y0 + shrink, line.box.x1, line.box.y1 - shrink)
            )

    scanned = layout.is_scanned and page_image is not None
    elements: list[tuple[Box, str]] = []
    if scanned:
        occupancy = _ink_mask(page_image, layout, grid, config.ink_render_scale)
    else:
        band, side = MARGIN_BAND * layout.height, MARGIN_BAND * layout.width
        content = Box(side, band, layout.width - side, layout.height - band)
        for element in layout.graphics:
            if not _is_rule(element.box, layout) and not _in_margin(element.box, layout):
                clipped = Box(
                    max(element.box.x0, content.x0),
                    max(element.box.y0, content.y0),
                    min(element.box.x1, content.x1),
                    min(element.box.y1, content.y1),
                )
                elements.append((clipped, element.kind))
        # Only graphics form the grid; text joins afterwards (see _attach_text) so
        # that table rows or stray labels cannot bridge two separate figures.
        for box, _ in elements:
            grid.fill(occupancy, box)

    gap = config.merge_gap_scanned if scanned else config.merge_gap
    radius = max(1, int(round(gap / 2 / config.cell)))
    merged = dilate(occupancy, radius) & ~walls
    merged |= occupancy & ~walls
    labels, count = label_components(merged)

    clusters: list[Cluster] = []
    if scanned:
        for label in range(1, count + 1):
            rows, cols = np.nonzero((labels == label) & occupancy)
            if len(rows) == 0:
                continue
            clusters.append(
                Cluster(
                    box=grid.box_of(rows, cols), has_graphic=True, element_count=len(rows), images=1
                )
            )
    else:
        groups: dict[int, list[tuple[Box, str]]] = {}
        for box, kind in elements:
            cell_labels = labels[grid.cells(box)]
            nonzero = cell_labels[cell_labels > 0]
            if nonzero.size == 0:
                continue
            groups.setdefault(int(np.bincount(nonzero).argmax()), []).append((box, kind))
        caption_lines = [ln.box for ln in layout.lines if ln.role == "caption"]
        split_groups: list[list[tuple[Box, str]]] = []
        for members in groups.values():
            split_groups.extend(_split_at_captions(members, caption_lines))
        _attach_text(split_groups, [ln for ln in layout.lines if ln.role == "figure_text"], config)
        for members in split_groups:
            box = union_box([b for b, _ in members])
            kinds = Counter(kind for _, kind in members)
            image_boxes = [b for b, kind in members if kind == "image"]
            clusters.append(
                Cluster(
                    box=box.clip(layout.width, layout.height),
                    has_graphic=kinds["image"] + kinds["path"] + kinds["shading"] > 0,
                    element_count=len(members),
                    images=kinds["image"],
                    paths=kinds["path"] + kinds["shading"],
                    image_area=min(box.area, sum(b.area for b in image_boxes)),
                )
            )

    band = MARGIN_BAND * layout.height
    return [
        c
        for c in clusters
        if c.has_graphic
        and c.box.width >= MIN_REGION_SIDE
        and c.box.height >= MIN_REGION_SIDE
        and not (c.box.y1 < band * 1.2 or c.box.y0 > layout.height - band * 1.2)
    ]


def _attach_text(
    groups: list[list[tuple[Box, str]]], lines: list[TextLine], config: RegionConfig
) -> None:
    """Add figure text (axis labels, legends, panel letters) to the nearest graphic group.

    A line joins a group when it lies within ``text_attach_gap`` of the group's
    graphics, or directly touches a line already attached (multi-line titles
    and legends). Text never links two graphic groups together.
    """
    boxes = [union_box([b for b, _ in members]) for members in groups]
    attached: dict[int, int] = {}
    pending = list(lines)
    changed = True
    while changed and pending:
        changed = False
        for line in list(pending):
            best: tuple[float, int] | None = None
            for index, box in enumerate(boxes):
                distance = _distance(line.box, box)
                if distance <= config.text_attach_gap and (best is None or distance < best[0]):
                    best = (distance, index)
            if best is None:
                for other_id, index in attached.items():
                    other = next(ln for ln in lines if id(ln) == other_id)
                    if _distance(
                        line.box, other.box
                    ) <= config.text_chain_gap and line.box.x_overlap(other.box) > 0.3 * min(
                        line.box.width, other.box.width
                    ):
                        best = (0.0, index)
                        break
            if best is not None:
                index = best[1]
                groups[index].append((line.box, "text"))
                attached[id(line)] = index
                pending.remove(line)
                changed = True


def _split_at_captions(
    members: list[tuple[Box, str]], captions: list[Box]
) -> list[list[tuple[Box, str]]]:
    """Split a group of elements that a caption line crosses horizontally.

    Element bounds can overlap a caption (oversized image boxes, tables drawn
    as images next to figures), merging two figures into one group. Elements
    spanning the caption (frames) are dropped from the split parts.
    """
    box = union_box([b for b, _ in members])
    cuts = sorted(
        (
            c
            for c in captions
            if c.y0 > box.y0 + MIN_REGION_SIDE
            and c.y1 < box.y1 - MIN_REGION_SIDE
            and c.x_overlap(box) > 0.5 * c.width
        ),
        key=lambda c: c.y0,
    )
    if not cuts:
        return [members]
    bounds = [box.y0] + [c.cy for c in cuts] + [box.y1 + 1]
    parts: list[list[tuple[Box, str]]] = [[] for _ in range(len(bounds) - 1)]
    for element in members:
        element_box = element[0]
        if any(element_box.y0 < c.y0 and element_box.y1 > c.y1 for c in cuts):
            continue  # frame or background spanning a caption
        for index in range(len(parts)):
            if bounds[index] <= element_box.cy < bounds[index + 1]:
                parts[index].append(element)
                break
    return [part for part in parts if part]


def _gap_box(a: Box, b: Box) -> Box | None:
    """The empty space between two boxes that overlap on one axis."""
    if a.x_overlap(b) > 0:
        x0, x1 = max(a.x0, b.x0), min(a.x1, b.x1)
        if a.y1 <= b.y0:
            return Box(x0, a.y1, x1, b.y0)
        if b.y1 <= a.y0:
            return Box(x0, b.y1, x1, a.y0)
    if a.y_overlap(b) > 0:
        y0, y1 = max(a.y0, b.y0), min(a.y1, b.y1)
        if a.x1 <= b.x0:
            return Box(a.x1, y0, b.x0, y1)
        if b.x1 <= a.x0:
            return Box(b.x1, y0, a.x0, y1)
    return None


def _blocking_lines(gap: Box | None, layout: PageLayout, ignore: list[TextLine]) -> int:
    """Number of body/caption lines lying in the space between two boxes."""
    if gap is None:
        return 0
    ignore_ids = {id(line) for line in ignore}
    count = 0
    for line in layout.lines:
        if line.role not in {"body", "caption"} or id(line) in ignore_ids:
            continue
        inner = line.box.expand(-0.25 * line.box.height)
        if inner.intersects(gap):
            count += 1
    return count


def _blocked(gap: Box | None, layout: PageLayout, ignore: list[TextLine]) -> bool:
    return _blocking_lines(gap, layout, ignore) > 0


def _relation_cost(
    cluster: Box, caption: CaptionCandidate, layout: PageLayout, tolerance: int = 0
) -> tuple[float, str, Box] | None:
    """Cost of pairing a region with a caption, the relation and the trimmed region.

    Vector paths often declare bounds larger than what is drawn, so a region may
    slightly overlap its caption; the region is trimmed back to the caption edge.
    """
    cap = caption.box
    max_gap = MAX_CAPTION_GAP * layout.height
    min_width = min(cluster.width, cap.width)
    figure_like = caption.kind != "table"
    options: list[tuple[float, str, Box]] = []

    # Caption inside a frame drawn around figure + caption (born-digital layouts only:
    # on scans, residual ink around a caption would fake a frame).
    if (
        not layout.is_scanned
        and cluster.x0 - 2 <= cap.x0
        and cap.x1 <= cluster.x1 + 2
        and cluster.y0 - 2 <= cap.y0
        and cap.y1 <= cluster.y1 + 2
    ):
        options.append((5.0, "inside", cluster))
    if cluster.x_overlap(cap) >= 0.3 * min_width:
        if cluster.cy < cap.y0 and cluster.y0 < cap.y0 - MIN_REGION_SIDE:  # caption below
            trimmed = Box(cluster.x0, cluster.y0, cluster.x1, min(cluster.y1, cap.y0 - 1))
            gap = cap.y0 - trimmed.y1
            if gap <= max_gap:
                weight = 1.0 if figure_like else 1.5
                options.append(
                    (gap * weight + (0 if figure_like else 10), "caption_below", trimmed)
                )
        if cluster.cy > cap.y1 and cluster.y1 > cap.y1 + MIN_REGION_SIDE:  # caption above
            trimmed = Box(cluster.x0, max(cluster.y0, cap.y1 + 1), cluster.x1, cluster.y1)
            gap = trimmed.y0 - cap.y1
            if gap <= max_gap:
                weight = 1.5 if figure_like else 1.0
                options.append(
                    (gap * weight + (10 if figure_like else 0), "caption_above", trimmed)
                )
    if cluster.y_overlap(cap) >= 0.3 * min(cluster.height, cap.height):
        if cluster.cx > cap.x1:
            trimmed = Box(max(cluster.x0, cap.x1 + 1), cluster.y0, cluster.x1, cluster.y1)
            gap = trimmed.x0 - cap.x1
        else:
            trimmed = Box(cluster.x0, cluster.y0, min(cluster.x1, cap.x0 - 1), cluster.y1)
            gap = cap.x0 - trimmed.x1
        if gap <= 0.15 * layout.width and trimmed.width >= MIN_REGION_SIDE:
            options.append((gap + 15, "caption_beside", trimmed))
    if not options:
        return None
    for cost, relation, trimmed in sorted(options, key=lambda option: option[0]):
        blocking = (
            0
            if relation == "inside"
            else _blocking_lines(_gap_box(trimmed, cap), layout, caption.lines)
        )
        if blocking <= tolerance:
            return cost + 20 * blocking + 15 * (3 - min(caption.score, 3)), relation, trimmed
    return None


def assign_regions(
    layout: PageLayout,
    clusters: list[Cluster],
    captions: list[CaptionCandidate],
    config: RegionConfig | None = None,
) -> PageRegions:
    tolerance = (config or RegionConfig()).blocking_line_tolerance
    result = PageRegions(clusters=clusters)
    for cluster in clusters:
        best: tuple[float, str, Box, CaptionCandidate] | None = None
        for caption in captions:
            scored = _relation_cost(cluster.box, caption, layout, tolerance)
            if scored and (best is None or scored[0] < best[0]):
                best = (*scored, caption)
        if best:
            cluster.cost, cluster.relation, cluster.box, cluster.caption = best
            result.assigned.setdefault(id(cluster.caption), []).append(cluster)

    # A figure lies on one side of its caption: drop clusters on the opposite side
    # (e.g. text below a caption whose figure is above it).
    by_id = {id(c): c for c in captions}
    for key, members in list(result.assigned.items()):
        members.sort(key=lambda m: m.cost)
        kept = [members[0]] + [m for m in members[1:] if _same_side(m.box, members[0], by_id[key])]
        for member in members:
            if member not in kept:
                member.caption, member.relation, member.cost = None, None, None
        result.assigned[key] = kept

    # Absorb leftover clusters touching an assigned region (stacked panel rows).
    changed = True
    while changed:
        changed = False
        for cluster in clusters:
            if cluster.caption is not None:
                continue
            for caption in captions:
                members = result.assigned.get(id(caption))
                if not members or not _same_side(cluster.box, members[0], caption):
                    continue
                region = union_box([m.box for m in members])
                gap = _gap_box(cluster.box, region)
                distance = _distance(cluster.box, region)
                if distance <= ABSORB_GAP and (
                    gap is None
                    and cluster.box.intersects(region.expand(ABSORB_GAP))
                    or gap is not None
                    and not _blocked(gap, layout, [])
                ):
                    cluster.caption, cluster.relation = caption, "absorbed"
                    members.append(cluster)
                    changed = True
                    break
    return result


def _same_side(box: Box, anchor: Cluster, caption: CaptionCandidate) -> bool:
    """A cluster may only join a figure from the caption's figure side."""
    cap = caption.box
    if anchor.relation == "caption_below":
        return box.cy < cap.y0
    if anchor.relation == "caption_above":
        return box.cy > cap.y1
    if anchor.relation == "caption_beside":
        return (box.cx > cap.x1) == (anchor.box.cx > cap.x1)
    return anchor.relation == "inside"


def _distance(a: Box, b: Box) -> float:
    dx = max(0.0, max(a.x0, b.x0) - min(a.x1, b.x1))
    dy = max(0.0, max(a.y0, b.y0) - min(a.y1, b.y1))
    return max(dx, dy)


def trim_against_captions(region: Box, relation: str | None, layout: PageLayout) -> Box:
    """Cut a figure region back so it never covers caption text on its caption side.

    Needed when the same caption exists in several overlapping text layers or
    when absorbed clusters reach past the caption edge.
    """
    captions = [ln for ln in layout.lines if ln.role == "caption" and ln.box.x_overlap(region) > 0]
    x0, y0, x1, y1 = region.x0, region.y0, region.x1, region.y1
    if relation == "caption_below":
        below = [ln.box.y0 for ln in captions if ln.box.cy > region.cy and ln.box.y0 < y1]
        if below:
            y1 = min(below) - 1
    elif relation == "caption_above":
        above = [ln.box.y1 for ln in captions if ln.box.cy < region.cy and ln.box.y1 > y0]
        if above:
            y0 = max(above) + 1
    trimmed = Box(x0, y0, x1, y1)
    trimmed = trim_against_body(trimmed, layout)
    return (
        trimmed
        if trimmed.height >= MIN_REGION_SIDE and trimmed.width >= MIN_REGION_SIDE
        else region
    )


def trim_against_body(region: Box, layout: PageLayout) -> Box:
    """Remove strips of body text at the edges of a region.

    Raster images often declare bounds wider than their visible content, so a
    region can spill over an adjacent text column. Body text never belongs to
    a figure, so a block of body lines on one side is cut away.
    """
    inside = [
        ln.box
        for ln in layout.lines
        if ln.role == "body"
        and ln.box.x_overlap(region) * ln.box.y_overlap(region) > 0.5 * ln.box.area
    ]
    if not inside:
        return region
    x0, y0, x1, y1 = region.x0, region.y0, region.x1, region.y1
    right = [b for b in inside if b.x0 > region.cx]
    left = [b for b in inside if b.x1 < region.cx]
    below = [b for b in inside if b.y0 > region.cy and b not in right and b not in left]
    above = [b for b in inside if b.y1 < region.cy and b not in right and b not in left]
    # A single stray line (e.g. an OCR line spanning a gutter) is not a text column.
    if len(right) >= 3:
        x1 = min(b.x0 for b in right) - 2
    if len(left) >= 3:
        x0 = max(b.x1 for b in left) + 2
    if len(below) >= 2:
        y1 = min(b.y0 for b in below) - 2
    if len(above) >= 2:
        y0 = max(b.y1 for b in above) + 2
    return Box(x0, y0, x1, y1)


def union_box(boxes: list[Box]) -> Box:
    box = boxes[0]
    for other in boxes[1:]:
        box = box.union(other)
    return box
