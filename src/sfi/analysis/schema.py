"""Explanation contract (docs/EXPLANATION_SCHEMA.md), version explanation/0.2.

``Explanation`` is what the model must return. It is sent to the provider as a
strict JSON Schema, so every field is required (optional values are nullable,
never omitted) and no extra keys are allowed.

``FigureAnalysis`` is the stored entity: the explanation plus the figure it
belongs to, the article passages sent as context, where each text quote was
found (page, section, offsets), validation issues and the provenance of the call
(model, prompt version, tokens, cost, latency). Analyses are append-only, like runs.

Fields added after 0.1 have defaults so that stored 0.1 analyses still load; the
schema sent to the model still requires every field (see strict_json_schema).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sfi.domain.models import utcnow

EXPLANATION_SCHEMA_VERSION = "explanation/0.2"

ClaimType = Literal["observed", "author_stated", "model_inference", "uncertain"]
Confidence = Literal["high", "medium", "low", "n/a"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Panel(_Strict):
    label: str = Field(description="Panel label exactly as printed, e.g. 'A', 'b', 'iii'.")
    content: str = Field(description="What the panel shows, in one sentence.")


class Layout(_Strict):
    description: str = Field(description="How the figure is organised and how to read it.")
    panels: list[Panel]


class Axis(_Strict):
    panel: str | None
    axis: Literal["x", "y", "z", "color", "other"]
    label: str | None = Field(description="Axis title as printed; null if absent.")
    unit: str | None
    range: str | None = Field(description="Visible range, e.g. '0–90'; null if unreadable.")
    scale: Literal["linear", "log", "categorical", "other", "unknown"]


class LegendEntry(_Strict):
    panel: str | None
    symbol: str = Field(description="Colour, marker or line style, e.g. 'red dashed line'.")
    meaning: str


class ScaleBar(_Strict):
    panel: str | None
    value: str = Field(description="Value as printed, e.g. '200 nm'.")
    source: Literal["observed", "caption"]


class VisualEncoding(_Strict):
    axes: list[Axis]
    legend: list[LegendEntry]
    scale_bars: list[ScaleBar]
    other: list[str] = Field(description="Other important colours, symbols or annotations.")


class Evidence(_Strict):
    kind: Literal["figure_region", "caption", "text_span"]
    panel: str | None = Field(description="Panel label for figure_region evidence; else null.")
    quote: str | None = Field(
        description="For caption or text_span evidence: a fragment copied verbatim."
    )
    passage_id: str | None = Field(
        default=None, description="For text_span evidence: the id of the passage quoted."
    )


class Claim(_Strict):
    id: str = Field(description="c1, c2, ...")
    type: ClaimType
    text: str
    panels: list[str]
    evidence: list[Evidence]
    approximate: bool = Field(description="True when a value is estimated by reading the plot.")
    confidence: Confidence


class Interpretation(_Strict):
    text: str
    claim_ids: list[str]


class RoleInArticle(_Strict):
    text: str = Field(description="Which result or conclusion of the article the figure supports.")
    claim_ids: list[str]


class Explanation(_Strict):
    summary: str = Field(description="What the figure represents, in 1-3 sentences.")
    figure_type: list[str] = Field(description="snake_case types, e.g. chart, micrograph, map.")
    layout: Layout
    visual_encoding: VisualEncoding
    claims: list[Claim]
    main_findings: list[str] = Field(description="Ids of the claims with the main results.")
    interpretation: Interpretation
    role_in_article: RoleInArticle = Field(
        default_factory=lambda: RoleInArticle(text="", claim_ids=[])
    )
    limitations: list[str] = Field(description="Ids of 'uncertain' claims.")
    limitations_justification: str | None = Field(
        description="Only if limitations is empty: why nothing is uncertain."
    )


class AnalysisStatus(StrEnum):
    OK = "ok"
    INCOMPLETE = "incomplete"  # truncated or missing required content
    INVALID = "invalid"  # malformed, refused or breaks a validation rule
    FAILED = "failed"  # the call itself failed; nothing to show
    SKIPPED = "skipped"  # not analysed: no region, limit or budget reached


class ValidationIssue(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    message: str
    claim_id: str | None = None


class FigureRef(BaseModel):
    document_id: str
    figure_id: str
    label: str | None
    page: int = Field(description="1-based page number")


class ContextPassage(BaseModel):
    """An article passage sent to the model, as sent (possibly a window of it)."""

    ref: str = Field(description="Id shown to the model, e.g. 'p12'")
    passage_id: str
    page: int = Field(description="1-based page where the sent text starts")
    section: str | None
    text: str
    offset: int = Field(description="Offset of the sent text inside the full passage")
    mentions: list[str] = Field(description="Mentions of the figure in the sent text")
    truncated: bool = False
    segments: list[tuple[int, int]] = Field(
        default_factory=list,
        description="(1-based page, offset in the full passage) where each page portion starts",
    )

    def page_at(self, offset: int) -> int:
        """1-based page of the character at ``offset`` of the full passage."""
        page = self.page
        for segment_page, start in self.segments:
            if start <= offset:
                page = segment_page
        return page


class SpanRef(BaseModel):
    """Where a text_span quote was found: passage, page, section and offsets."""

    claim_id: str
    evidence_index: int
    ref: str
    passage_id: str
    page: int = Field(description="1-based page of the quote")
    section: str | None
    start: int = Field(description="Offset of the quote in the full passage text")
    end: int


class TokenRef(BaseModel):
    """A number a claim reads in the figure, linked to where it is printed."""

    claim_id: str
    value: str
    text: str = Field(description="The figure token that contains the value")
    bbox_normalized: tuple[float, float, float, float] = Field(description="Page fractions")
    source: str = Field(description="pdf | pdf-ocr | ocr:<engine>-<version>")


class AnalysisRun(BaseModel):
    """Provenance of one model call (the 'run' block of the explanation contract)."""

    provider: str
    model: str = Field(description="Model id requested")
    model_version: str | None = Field(description="Model id reported by the provider")
    prompt_version: str
    response_id: str | None = None
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    provider_status: str | None = None
    incomplete_reason: str | None = None


class FigureAnalysis(BaseModel):
    id: str
    figure_id: str
    document_id: str
    cache_key: str
    config_hash: str
    config: dict
    schema_version: str = EXPLANATION_SCHEMA_VERSION
    figure_ref: FigureRef
    status: AnalysisStatus
    explanation: Explanation | None = None
    context: list[ContextPassage] = Field(default_factory=list)
    context_note: str | None = None
    spans: list[SpanRef] = Field(default_factory=list)
    token_refs: list[TokenRef] = Field(
        default_factory=list, description="Numbers of claims found in the figure text"
    )
    raw_output: str | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)
    validator_version: str | None = None
    run: AnalysisRun | None = None
    error: str | None = None
    reused_from: str | None = Field(
        default=None, description="Analysis id whose result was reused (no new spend)."
    )
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def cost_usd(self) -> float:
        """Money actually spent by this record (zero when reused from the cache)."""
        if self.reused_from or self.run is None:
            return 0.0
        return self.run.estimated_cost_usd
