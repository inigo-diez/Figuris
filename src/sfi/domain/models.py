"""Document IR entities for figure extraction.

Coordinates follow two conventions, both stored explicitly:

- ``bbox``: PDF user space in points, origin at the bottom-left of the page
  (``coordinate_space = "pdf_points"``), i.e. ``(left, bottom, right, top)``.
- ``bbox_normalized``: fractions of page width/height with origin at the
  top-left, i.e. ``(x0, y0, x1, y1)`` in ``[0, 1]``. This is what viewers use.

Derived entities never overwrite earlier results: each extraction belongs to a
``ProcessorRun`` identified by document, producer version and config hash.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

SCHEMA_VERSION = "ir/0.1"


def utcnow() -> datetime:
    return datetime.now(UTC)


class BBox(BaseModel):
    """Box in PDF points, origin bottom-left: (left, bottom, right, top)."""

    left: float
    bottom: float
    right: float
    top: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.top - self.bottom

    def normalized(
        self, page_width: float, page_height: float
    ) -> tuple[float, float, float, float]:
        """Return (x0, y0, x1, y1) as page fractions with a top-left origin."""
        return (
            round(self.left / page_width, 5),
            round((page_height - self.top) / page_height, 5),
            round(self.right / page_width, 5),
            round((page_height - self.bottom) / page_height, 5),
        )


class WarningCode(StrEnum):
    CAPTION_WITHOUT_REGION = "caption_without_region"
    REGION_WITHOUT_CAPTION = "region_without_caption"
    DUPLICATE_LABEL = "duplicate_label"
    MISSING_IN_SEQUENCE = "missing_in_sequence"
    CAPTION_MAY_CONTINUE = "caption_may_continue"
    CAPTION_CONTINUED = "caption_continued"  # continued on the next page and joined
    SCANNED_PAGE = "scanned_page"
    LOW_CONFIDENCE = "low_confidence"
    LIMIT_REACHED = "limit_reached"
    ROTATED_PAGE = "rotated_page"
    CAPTION_ON_OTHER_PAGE = "caption_on_other_page"


class ExtractionWarning(BaseModel):
    code: WarningCode
    message: str
    page_index: int | None = None
    figure_label: str | None = None


class PageInfo(BaseModel):
    index: int = Field(description="0-based page index")
    width: float
    height: float
    rotation: int = 0
    is_scanned: bool = False


class Document(BaseModel):
    id: str = Field(description="sha256 of the original bytes, prefixed 'sha256:'")
    filename: str
    source_artifact_id: str
    page_count: int
    pages: list[PageInfo]
    created_at: datetime = Field(default_factory=utcnow)
    schema_version: str = SCHEMA_VERSION


class Artifact(BaseModel):
    """An immutable blob: original PDF, rendered crop, page preview."""

    id: str = Field(description="sha256 of the bytes")
    kind: str = Field(description="original_pdf | figure_crop | page_render")
    media_type: str
    byte_size: int
    storage_key: str
    parent_ids: list[str] = Field(default_factory=list)
    producer: str
    producer_version: str
    created_at: datetime = Field(default_factory=utcnow)


class Caption(BaseModel):
    label: str = Field(description="Normalized label, e.g. 'Fig. 3', 'Extended Data Fig. 1'")
    kind: str = Field(description="figure | table | scheme")
    number: str
    text: str
    page_index: int
    bbox: BBox
    score: float = Field(description="Heuristic caption likelihood; higher is more certain")


class EvidenceToken(BaseModel):
    """Text printed inside a figure (a word, number or label) and where it is."""

    text: str
    bbox_normalized: tuple[float, float, float, float] = Field(
        description="Page fractions, top-left origin"
    )
    confidence: float
    source: str = Field(description="pdf | pdf-ocr (text layer of a scan) | ocr:<engine>-<v>")


class Panel(BaseModel):
    """One panel of a multipanel figure ("a", "b"...) and its part of the caption."""

    label: str = Field(description="Panel letter as in the caption")
    bbox: BBox | None = Field(description="Panel region; None when the split is not reliable")
    bbox_normalized: tuple[float, float, float, float] | None = None
    subcaption: str = Field(description="Text of the caption that describes this panel")
    confidence: float
    method: str = Field(description="How the region was found, e.g. 'xy-cut+caption-order'")


class Figure(BaseModel):
    id: str
    document_id: str
    run_id: str
    label: str | None
    kind: str = "figure"
    number: str | None = None
    page_index: int
    bbox: BBox | None = Field(description="Figure region without the caption; None if not found")
    bbox_normalized: tuple[float, float, float, float] | None = None
    coordinate_space: str = "pdf_points"
    caption: Caption | None = None
    crop_artifact_id: str | None = None
    status: str = Field(description="ok | caption_only | region_only")
    confidence: float
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    panel_layout: str | None = Field(
        default=None, description="single | split | unmatched (letters known, no boxes)"
    )
    panels: list[Panel] = Field(default_factory=list)
    tokens: list[EvidenceToken] = Field(
        default_factory=list, description="Text inside the figure (evidence layer)"
    )
    producer: str
    producer_version: str
    schema_version: str = SCHEMA_VERSION


class ProcessorRun(BaseModel):
    id: str = Field(description="Deterministic: hash of document id, producer, version, config")
    document_id: str
    producer: str
    producer_version: str
    config_hash: str
    config: dict
    status: str = Field(description="running | completed | failed")
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    duration_ms: int | None = None
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    error: str | None = None


class FigureMention(BaseModel):
    """A reference to a figure inside a passage: 'Fig. 2C,D' -> Figure 2, panels C, D."""

    label: str
    panels: list[str] = Field(default_factory=list)
    start: int = Field(description="Character offset in the passage text")
    end: int
    text: str


class PassageSegment(BaseModel):
    """The part of a passage on one page and column."""

    page_index: int
    char_start: int = Field(description="Offset of the segment's first character in the passage")
    bbox: BBox
    bbox_normalized: tuple[float, float, float, float]


class Passage(BaseModel):
    """A paragraph of the article body, in reading order, with its location."""

    id: str
    document_id: str
    run_id: str
    ordinal: int
    page_index: int = Field(description="0-based page where the passage starts")
    section: str | None
    back_matter: bool = Field(description="References, acknowledgements, declarations")
    text: str
    segments: list[PassageSegment]
    mentions: list[FigureMention] = Field(default_factory=list)
    producer: str
    producer_version: str
    schema_version: str = SCHEMA_VERSION

    def page_at(self, offset: int) -> int:
        """0-based page of the character at ``offset``."""
        page = self.page_index
        for segment in self.segments:
            if segment.char_start <= offset:
                page = segment.page_index
        return page


class JobStatus(StrEnum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(BaseModel):
    """Processing of one uploaded PDF: extraction, then explanation of its figures.

    Jobs are idempotent: re-running one reuses the cached extraction and explanations,
    so a job interrupted by a restart is simply queued again.
    """

    id: str
    filename: str
    upload_path: str
    status: JobStatus = JobStatus.QUEUED
    stage: str = "En cola"
    document_id: str | None = None
    figures_total: int = 0
    figures_done: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    force_analysis: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def active(self) -> bool:
        return self.status in {JobStatus.QUEUED, JobStatus.EXTRACTING, JobStatus.ANALYZING}
