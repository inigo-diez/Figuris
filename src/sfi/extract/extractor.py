"""Figure extraction from PDFs: the FigureExtractor contract and a pdfium baseline.

The baseline is heuristic and dependency-light (pypdfium2 + numpy). It is the
reference point that heavier parsers (Docling, GROBID, PDFFigures2) must beat
in experiment E01; they will implement the same ``FigureExtractor`` protocol.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Protocol

import numpy as np
import pypdfium2 as pdfium

from sfi.domain.models import ExtractionWarning, WarningCode
from sfi.extract.captions import (
    STRONG_CAPTION_SCORE,
    CaptionCandidate,
    attach_continuation,
    find_caption_candidates,
)
from sfi.extract.layout import Box, PageLayout, TextLine, read_page_layout
from sfi.extract.panels import SplitConfig, caption_letters, detect_panels
from sfi.extract.regions import (
    RegionConfig,
    assign_regions,
    build_clusters,
    classify_body,
    estimate_body_size,
    mark_margins,
    trim_against_captions,
    union_box,
)

MIN_UNLABELLED_AREA = 0.02  # fraction of the page
PANEL_DPI = 100  # rendering used to split multipanel figures
LEGEND_ELSEWHERE = re.compile(
    r"see (the )?legend on (the )?(previous|next|following|facing) page", re.I
)


@dataclass
class ExtractedPanel:
    label: str
    box: Box | None  # page points, top-left origin; None when the split is not reliable
    subcaption: str
    confidence: float


@dataclass
class ExtractedFigure:
    label: str | None
    kind: str
    number: str | None
    page_index: int
    box: Box | None
    caption: CaptionCandidate | None
    status: str  # ok | caption_only | region_only
    confidence: float
    relation: str | None = None
    warnings: list[ExtractionWarning] = field(default_factory=list)
    panel_layout: str | None = None  # single | split | unmatched (see sfi.extract.panels)
    panels: list[ExtractedPanel] = field(default_factory=list)


@dataclass
class ExtractionResult:
    pages: list[PageLayout]
    figures: list[ExtractedFigure]
    warnings: list[ExtractionWarning]
    tables_detected: int
    table_captions: list[CaptionCandidate] = field(default_factory=list)


class FigureExtractor(Protocol):
    name: str
    version: str

    def config(self) -> dict: ...

    def extract(self, pdf: pdfium.PdfDocument) -> ExtractionResult: ...


def _confidence(
    caption: CaptionCandidate | None, relation: str | None, cost: float | None, scanned: bool
) -> float:
    score = 0.35
    if caption is not None:
        score += 0.1 * min(caption.score, 4)
    if relation in {"caption_below", "caption_beside", "inside"}:
        score += 0.15
    if cost is not None and cost < 25:
        score += 0.1
    if scanned:
        score -= 0.15
    return round(max(0.05, min(score, 0.95)), 2)


class PdfiumFigureExtractor:
    name = "pdfium-heuristic"
    # 0.2: captions that end on a page are not continued on the next
    # 0.3: multipanel figures are split into panels linked to sub-captions
    # 0.3.1: a caption continued and joined is no longer reported as possibly truncated
    version = "0.3.1"

    def __init__(
        self, region_config: RegionConfig | None = None, panel_config: SplitConfig | None = None
    ):
        self.region_config = region_config or RegionConfig()
        self.panel_config = panel_config or SplitConfig()

    def config(self) -> dict:
        return {
            "region": asdict(self.region_config),
            "panels": {"dpi": PANEL_DPI, **asdict(self.panel_config)},
        }

    def extract(self, pdf: pdfium.PdfDocument) -> ExtractionResult:
        layouts = [read_page_layout(pdf[i], i) for i in range(len(pdf))]
        for layout in layouts:
            mark_margins(layout)
        _mark_running_headers(layouts)
        body_size = _document_body_size(layouts)
        for layout in layouts:
            layout.body_size = (
                estimate_body_size(layout) if _char_total(layout) > 1500 else body_size
            )

        candidates_by_page = [find_caption_candidates(layout) for layout in layouts]
        for layout, candidates in zip(layouts, candidates_by_page, strict=True):
            for candidate in candidates:
                for line in candidate.lines:
                    line.role = "caption"
            _absorb_caption_fragments(layout, candidates)
        for index, candidates in enumerate(candidates_by_page):
            next_layout = layouts[index + 1] if index + 1 < len(layouts) else None
            for candidate in candidates:
                if candidate.score >= STRONG_CAPTION_SCORE and candidate.kind != "table":
                    attach_continuation(candidate, layouts[index], next_layout)
                    for line in candidate.continuation_lines:
                        line.role = "caption"
        for layout in layouts:
            classify_body(layout)

        figures: list[ExtractedFigure] = []
        warnings: list[ExtractionWarning] = []
        table_captions: list[CaptionCandidate] = []
        for layout, candidates in zip(layouts, candidates_by_page, strict=True):
            page_image = self._page_image(pdf, layout) if layout.is_scanned else None
            clusters = build_clusters(layout, self.region_config, page_image)
            regions = assign_regions(layout, clusters, candidates, self.region_config)
            if layout.is_scanned and (candidates or clusters):
                warnings.append(
                    ExtractionWarning(
                        code=WarningCode.SCANNED_PAGE,
                        page_index=layout.index,
                        message="Scanned page: regions come from image analysis and OCR text.",
                    )
                )

            for candidate in candidates:
                members = regions.assigned.get(id(candidate), [])
                if candidate.kind == "table":
                    table_captions.append(candidate)
                    continue
                if not members and candidate.score < STRONG_CAPTION_SCORE:
                    continue  # most likely an in-text reference starting a line
                relation = members[0].relation if members else None
                figure = ExtractedFigure(
                    label=candidate.label,
                    kind=candidate.kind,
                    number=candidate.number,
                    page_index=layout.index,
                    box=(
                        trim_against_captions(union_box([m.box for m in members]), relation, layout)
                        if members
                        else None
                    ),
                    caption=candidate,
                    status="ok" if members else "caption_only",
                    relation=members[0].relation if members else None,
                    confidence=_confidence(
                        candidate,
                        members[0].relation if members else None,
                        members[0].cost if members else None,
                        layout.is_scanned,
                    ),
                )
                if not members:
                    figure.confidence = 0.2
                    figure.warnings.append(
                        ExtractionWarning(
                            code=WarningCode.CAPTION_WITHOUT_REGION,
                            page_index=layout.index,
                            figure_label=candidate.label,
                            message="Caption found but no graphic region could be associated.",
                        )
                    )
                ends_sentence = candidate.text.rstrip().endswith((".", ")", "]", "!", "?"))
                if candidate.continued_on_next_page and candidate.continuation_lines:
                    figure.warnings.append(
                        ExtractionWarning(
                            code=WarningCode.CAPTION_CONTINUED,
                            page_index=layout.index,
                            figure_label=candidate.label,
                            message="Caption reaches the page bottom; "
                            "continuation taken from the next page.",
                        )
                    )
                elif candidate.continued_on_next_page and not ends_sentence:
                    figure.warnings.append(
                        ExtractionWarning(
                            code=WarningCode.CAPTION_MAY_CONTINUE,
                            page_index=layout.index,
                            figure_label=candidate.label,
                            message="Caption reaches the page bottom; it may be truncated.",
                        )
                    )
                figures.append(figure)

            page_area = layout.width * layout.height
            for cluster in clusters:
                if (
                    cluster.caption is None
                    and cluster.box.area >= MIN_UNLABELLED_AREA * page_area
                    and cluster.looks_like_figure(layout)
                ):
                    figures.append(
                        ExtractedFigure(
                            label=None,
                            kind="figure",
                            number=None,
                            page_index=layout.index,
                            box=cluster.box,
                            caption=None,
                            status="region_only",
                            confidence=0.2,
                            warnings=[
                                ExtractionWarning(
                                    code=WarningCode.REGION_WITHOUT_CAPTION,
                                    page_index=layout.index,
                                    message="Graphic region without an associated caption.",
                                )
                            ],
                        )
                    )

        figures = _deduplicate(figures)
        for figure in figures:
            self._split_panels(pdf, layouts[figure.page_index], figure)
        warnings.extend(_sequence_warnings(figures))
        for figure in figures:
            if figure.status == "ok" and figure.confidence < 0.5:
                figure.warnings.append(
                    ExtractionWarning(
                        code=WarningCode.LOW_CONFIDENCE,
                        page_index=figure.page_index,
                        figure_label=figure.label,
                        message="Low confidence region/caption match.",
                    )
                )
        return ExtractionResult(
            pages=layouts,
            figures=figures,
            warnings=warnings,
            tables_detected=len(table_captions),
            table_captions=table_captions,
        )

    def _split_panels(
        self, pdf: pdfium.PdfDocument, layout: PageLayout, figure: ExtractedFigure
    ) -> None:
        caption = figure.caption.text if figure.caption else None
        gray = None
        if figure.box is not None and len(caption_letters(caption or "")) >= 2:
            box = figure.box
            crop = (box.x0, layout.height - box.y1, layout.width - box.x1, box.y0)
            bitmap = pdf[layout.index].render(scale=PANEL_DPI / 72, crop=crop, grayscale=True)
            array = bitmap.to_numpy()
            gray = array[..., 0] if array.ndim == 3 else array
        result = detect_panels(gray, caption, self.panel_config)
        figure.panel_layout = result.layout
        scale = 72 / PANEL_DPI
        for panel in result.panels:
            page_box = None
            if panel.box is not None:
                x0, y0, x1, y1 = panel.box
                page_box = Box(
                    figure.box.x0 + x0 * scale,
                    figure.box.y0 + y0 * scale,
                    min(figure.box.x1, figure.box.x0 + x1 * scale),
                    min(figure.box.y1, figure.box.y0 + y1 * scale),
                )
            figure.panels.append(
                ExtractedPanel(panel.label, page_box, panel.subcaption, panel.confidence)
            )

    def _page_image(self, pdf: pdfium.PdfDocument, layout: PageLayout) -> np.ndarray:
        bitmap = pdf[layout.index].render(scale=self.region_config.ink_render_scale, grayscale=True)
        array = bitmap.to_numpy()
        return array[..., 0] if array.ndim == 3 else array


def _mark_running_headers(layouts: list[PageLayout]) -> None:
    """Text repeated at the same height on many pages (journal name, page x of y) is margin."""
    if len(layouts) < 3:
        return

    def key(line: TextLine) -> tuple[str, int]:
        return re.sub(r"\d+", "#", line.stripped.lower()), round(line.box.y0 / 4)

    pages_with: dict[tuple[str, int], set[int]] = {}
    for layout in layouts:
        for line in layout.lines:
            if line.char_count >= 3:
                pages_with.setdefault(key(line), set()).add(layout.index)
    threshold = max(3, 0.3 * len(layouts))
    repeated = {k for k, pages in pages_with.items() if len(pages) >= threshold}
    for layout in layouts:
        for line in layout.lines:
            if key(line) in repeated:
                line.role = "margin"


def _absorb_caption_fragments(layout: PageLayout, candidates: list[CaptionCandidate]) -> None:
    """Text drawn on top of a caption (duplicate text layers) belongs to that caption.

    If the fragment adds text that the caption line lacks (e.g. the visible
    line was split in two objects), it is merged into the caption text in
    reading order.
    """
    for line in layout.lines:
        if line.role in {"caption", "margin"} or line.box.area <= 0:
            continue
        for candidate in candidates:
            host = next(
                (
                    c
                    for c in candidate.lines
                    if line.box.x_overlap(c.box) * line.box.y_overlap(c.box) > 0.5 * line.box.area
                ),
                None,
            )
            if host is None:
                continue
            line.role = "caption"
            if line.stripped not in host.stripped:
                candidate.lines = _reading_order(candidate.lines + [line])
            break


def _reading_order(lines: list[TextLine]) -> list[TextLine]:
    """Sort lines top-to-bottom, grouping lines on the same row left-to-right."""
    rows: list[list[TextLine]] = []
    for line in sorted(lines, key=lambda ln: ln.box.y0):
        if rows and line.box.y0 < rows[-1][0].box.y0 + 0.5 * line.size:
            rows[-1].append(line)
        else:
            rows.append([line])
    return [line for row in rows for line in sorted(row, key=lambda ln: ln.box.x0)]


def _char_total(layout: PageLayout) -> int:
    return sum(line.char_count for line in layout.lines)


def _document_body_size(layouts: list[PageLayout]) -> float:
    from collections import Counter

    counts: Counter[float] = Counter()
    for layout in layouts:
        for line in layout.lines:
            if line.role != "margin":
                counts[round(line.size * 2) / 2] += line.char_count
    return counts.most_common(1)[0][0] if counts else 0.0


def _deduplicate(figures: list[ExtractedFigure]) -> list[ExtractedFigure]:
    """Keep one figure per label; prefer a located region, then caption score."""
    by_label: dict[str, list[ExtractedFigure]] = {}
    result: list[ExtractedFigure] = []
    for figure in figures:
        if figure.label is None:
            result.append(figure)
        else:
            by_label.setdefault(figure.label, []).append(figure)
    for label, group in by_label.items():
        group.sort(
            key=lambda f: (
                f.status != "ok",
                -(f.caption.score if f.caption else 0),
                -(f.box.area if f.box else 0),
            )
        )
        best = group[0]
        others = [f for f in group[1:] if f.status == "ok" or (f.caption and f.caption.score >= 3)]
        if best.caption and LEGEND_ELSEWHERE.search(best.caption.text):
            # "Fig. 2 (See legend on previous page.)": the real legend is the other caption.
            full = max(
                (f for f in group[1:] if f.caption and not LEGEND_ELSEWHERE.search(f.caption.text)),
                key=lambda f: len(f.caption.text),
                default=None,
            )
            if full is not None:
                best.caption = full.caption
                best.warnings.append(
                    ExtractionWarning(
                        code=WarningCode.CAPTION_ON_OTHER_PAGE,
                        page_index=best.page_index,
                        figure_label=label,
                        message=f"Legend printed on page {full.page_index + 1}, away from the figure.",
                    )
                )
                others = [f for f in others if f is not full]
        if others:
            pages = ", ".join(str(f.page_index + 1) for f in others)
            best.warnings.append(
                ExtractionWarning(
                    code=WarningCode.DUPLICATE_LABEL,
                    page_index=best.page_index,
                    figure_label=label,
                    message=f"Label also detected on page(s) {pages}; kept page {best.page_index + 1}.",
                )
            )
        result.append(best)
    result.sort(
        key=lambda f: (f.page_index, f.box.y0 if f.box else (f.caption.box.y0 if f.caption else 0))
    )
    return result


def _sequence_warnings(figures: list[ExtractedFigure]) -> list[ExtractionWarning]:
    groups: dict[str, set[int]] = {}
    for figure in figures:
        if figure.label and figure.number and figure.number.isdigit():
            prefix = re.sub(r"\s*\d+$", "", figure.label)
            groups.setdefault(prefix, set()).add(int(figure.number))
    warnings = []
    for prefix, numbers in groups.items():
        for missing in sorted(set(range(1, max(numbers) + 1)) - numbers):
            warnings.append(
                ExtractionWarning(
                    code=WarningCode.MISSING_IN_SEQUENCE,
                    figure_label=f"{prefix} {missing}",
                    message=f"{prefix} {missing} not found although higher numbers exist.",
                )
            )
    return warnings
