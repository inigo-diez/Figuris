"""Stages 2-3: explain each extracted figure with a multimodal model, within budget.

For every figure with a region the analyzer sends the crop, its caption and the
article passages that mention it to the configured model, parses the structured
answer, validates it (including every quote) and stores the result with its
provenance and the location of each quoted passage. Results are cached by content
(crop, caption, label, context) plus the analysis configuration (model, prompt
version, limits), so re-running never pays twice for the same thing.

Spending is bounded before each call by a worst-case estimate (all input plus the
maximum output) against the per-document limit and the total budget. When a limit
is reached the remaining figures are reported as skipped, never dropped silently.
The total budget is computed from the calls recorded in the local database.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import uuid
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from PIL import Image
from pydantic import ValidationError

from sfi.analysis.prompt import PROMPT_VERSION, build_instructions, build_user_text
from sfi.analysis.providers import (
    ModelRequest,
    ModelResult,
    MultimodalModel,
    ProviderError,
    ProviderFatalError,
)
from sfi.analysis.schema import (
    EXPLANATION_SCHEMA_VERSION,
    AnalysisRun,
    AnalysisStatus,
    ContextPassage,
    Explanation,
    FigureAnalysis,
    FigureRef,
    SpanRef,
    ValidationIssue,
)
from sfi.analysis.validate import (
    VALIDATOR_VERSION,
    locate_text_spans,
    resolve_token_refs,
    status_from_issues,
    validate_explanation,
)
from sfi.config import AnalysisSettings
from sfi.context.select import ContextConfig, FigureContext, select_context
from sfi.domain.models import Document, Figure, Passage, utcnow
from sfi.storage.blobs import BlobStore
from sfi.storage.repository import Repository

# Results worth reusing. Failed calls are retried on the next run.
CACHEABLE = [AnalysisStatus.OK, AnalysisStatus.INCOMPLETE, AnalysisStatus.INVALID]


class AnalysisUnavailable(Exception):
    """Analysis cannot run (e.g. no API key); extraction results are still valid."""


@dataclass
class FigureOutcome:
    figure: Figure
    status: AnalysisStatus
    source: str  # model | cache | skipped
    analysis: FigureAnalysis | None = None
    message: str | None = None


@dataclass
class DocumentAnalysis:
    document: Document
    outcomes: list[FigureOutcome] = field(default_factory=list)
    spent_usd: float = 0.0
    stopped: str | None = None  # why analysis stopped early, if it did
    fatal: bool = False  # the provider cannot be used at all (auth, quota, model)


@dataclass
class _Job:
    index: int
    figure: Figure
    cache_key: str
    request: ModelRequest
    estimate_usd: float
    context: FigureContext


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def prepare_image(png: bytes, max_long_side: int) -> tuple[bytes, tuple[int, int]]:
    """Flatten transparency and downscale so the long side is at most ``max_long_side``."""
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        if image.mode not in ("RGB", "L"):
            background = Image.new("RGB", image.size, "white")
            rgba = image.convert("RGBA")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        scale = max_long_side / max(image.size)
        if scale < 1:
            size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            image = image.resize(size, Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), image.size


def resolve_spans(explanation: Explanation, context: list[ContextPassage]) -> list[SpanRef]:
    """Page, section and offsets in the full passage of every quoted text span."""
    spans = []
    for claim_id, index, passage, start, end in locate_text_spans(explanation, context):
        offset = passage.offset + start
        spans.append(
            SpanRef(
                claim_id=claim_id,
                evidence_index=index,
                ref=passage.ref,
                passage_id=passage.passage_id,
                page=passage.page_at(offset),
                section=passage.section,
                start=offset,
                end=passage.offset + end,
            )
        )
    return spans


def estimate_input_tokens(text: str, image_size: tuple[int, int]) -> int:
    """Deliberately pessimistic: ~3 characters per token and one token per 32x32 patch."""
    width, height = image_size
    image_tokens = min(4000, math.ceil(width / 32) * math.ceil(height / 32)) + 100
    return math.ceil(len(text) / 3) + image_tokens


class FigureAnalyzer:
    def __init__(
        self,
        settings: AnalysisSettings,
        repository: Repository,
        blobs: BlobStore,
        model: MultimodalModel,
    ):
        self.settings = settings
        self.repository = repository
        self.blobs = blobs
        self.model = model
        self.pricing = settings.pricing(model.model)
        self.instructions = build_instructions(settings.language)
        self.context_config = ContextConfig(max_chars=settings.max_context_chars)

    def config(self) -> dict:
        return {
            "provider": self.model.provider,
            "model": self.model.model,
            "prompt_version": PROMPT_VERSION,
            "schema_version": EXPLANATION_SCHEMA_VERSION,
            "language": self.settings.language,
            "max_image_long_side_px": self.settings.max_image_long_side_px,
            "image_detail": self.settings.image_detail,
            "reasoning_effort": self.settings.reasoning_effort,
            "max_output_tokens": self.settings.max_output_tokens,
            "context": self.context_config.as_dict(),
        }

    @property
    def config_hash(self) -> str:
        return _hash(json.dumps(self.config(), sort_keys=True))[:16]

    def cache_key(self, figure: Figure, context: FigureContext | None = None) -> str:
        caption = figure.caption.text if figure.caption else ""
        sent = json.dumps(
            [[p.page, p.section, p.text] for p in (context.passages if context else [])],
            ensure_ascii=False,
        )
        return _hash(
            figure.crop_artifact_id or "", figure.label or "", caption, sent, self.config_hash
        )[:32]

    def context_for(self, figure: Figure, passages: list[Passage]) -> FigureContext:
        return select_context(figure, passages, self.context_config)

    def total_spent(self) -> float:
        return sum(row[3] for row in self.repository.analysis_spend())

    def analyze(
        self,
        document: Document,
        figures: list[Figure],
        force: bool = False,
        max_figures: int | None = None,
        progress: Callable[[FigureOutcome], None] | None = None,
        passages: list[Passage] | None = None,
    ) -> DocumentAnalysis:
        """Explain ``figures``; ``passages`` defaults to the text stored with their run."""
        result = DocumentAnalysis(document)
        if passages is None:
            passages = self.repository.list_passages(figures[0].run_id) if figures else []
        outcomes: dict[int, FigureOutcome] = {}

        def finish(index: int, outcome: FigureOutcome) -> None:
            outcomes[index] = outcome
            if progress:
                progress(outcome)

        limit = max_figures or self.settings.max_figures_per_document
        jobs: list[_Job] = []
        analysable = 0
        for index, figure in enumerate(figures):
            if not figure.crop_artifact_id:
                finish(
                    index, self._skipped(figure, "Sin región de imagen: solo se detectó el pie.")
                )
                continue
            analysable += 1
            if analysable > limit:
                finish(
                    index,
                    self._skipped(figure, f"Límite de {limit} figuras por documento alcanzado."),
                )
                result.stopped = result.stopped or f"límite de {limit} figuras por documento"
                continue
            context = self.context_for(figure, passages)
            key = self.cache_key(figure, context)
            cached = None if force else self.repository.cached_analysis(key, CACHEABLE)
            if cached is not None:
                stale = cached.validator_version != VALIDATOR_VERSION
                if cached.figure_id != figure.id or stale:
                    cached = self._reuse(cached, figure)
                finish(index, FigureOutcome(figure, cached.status, "cache", cached))
                continue
            jobs.append(self._job(index, document, figure, key, context))

        self._run_jobs(document, jobs, result, finish)
        result.outcomes = [outcomes[i] for i in sorted(outcomes)]
        return result

    def _job(
        self, index: int, document: Document, figure: Figure, key: str, context: FigureContext
    ) -> _Job:
        artifact = self.repository.get_artifact(figure.crop_artifact_id)
        png, size = prepare_image(
            self.blobs.path(artifact.storage_key).read_bytes(), self.settings.max_image_long_side_px
        )
        scanned = document.pages[figure.page_index].is_scanned
        text = build_user_text(figure, scanned, context.passages, context.note)
        request = ModelRequest(
            instructions=self.instructions,
            text=text,
            image_png=png,
            output_schema=Explanation,
            max_output_tokens=self.settings.max_output_tokens,
            image_detail=self.settings.image_detail,
            reasoning_effort=self.settings.reasoning_effort,
        )
        estimate = self.pricing.cost(
            estimate_input_tokens(self.instructions + text, size), self.settings.max_output_tokens
        )
        return _Job(index, figure, key, request, estimate, context)

    def _run_jobs(
        self,
        document: Document,
        jobs: list[_Job],
        result: DocumentAnalysis,
        finish: Callable[[int, FigureOutcome], None],
    ) -> None:
        if not jobs:
            return
        spent_total = self.total_spent()
        reserved = 0.0
        queue = list(jobs)
        running: dict[Future, _Job] = {}

        def stop(reason: str) -> None:
            result.stopped = result.stopped or reason
            while queue:
                job = queue.pop(0)
                finish(job.index, self._skipped(job.figure, f"No analizada: {reason}."))

        with ThreadPoolExecutor(max_workers=self.settings.concurrency) as pool:
            while queue or running:
                while queue and len(running) < self.settings.concurrency and not result.fatal:
                    job = queue[0]
                    if spent_total + reserved + job.estimate_usd > self.settings.total_budget_usd:
                        stop(
                            f"presupuesto total de {self.settings.total_budget_usd:.2f} USD "
                            f"agotado ({spent_total:.4f} USD gastados)"
                        )
                        break
                    if (
                        result.spent_usd + reserved + job.estimate_usd
                        > self.settings.max_cost_per_document_usd
                    ):
                        stop(
                            f"límite de {self.settings.max_cost_per_document_usd:.2f} USD "
                            "por documento alcanzado"
                        )
                        break
                    queue.pop(0)
                    reserved += job.estimate_usd
                    running[pool.submit(self.model.generate, job.request)] = job
                if not running:
                    break
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in done:
                    job = running.pop(future)
                    reserved -= job.estimate_usd
                    try:
                        model_result = future.result()
                    except ProviderFatalError as exc:
                        result.fatal = True
                        finish(job.index, self._failed(job, exc))
                        stop(str(exc))
                        continue
                    except ProviderError as exc:
                        finish(job.index, self._failed(job, exc))
                        continue
                    analysis = self._record(job, model_result)
                    spent_total += analysis.cost_usd
                    result.spent_usd += analysis.cost_usd
                    finish(job.index, FigureOutcome(job.figure, analysis.status, "model", analysis))

    def _figure_ref(self, figure: Figure) -> FigureRef:
        return FigureRef(
            document_id=figure.document_id,
            figure_id=figure.id,
            label=figure.label,
            page=figure.page_index + 1,
        )

    def _new_analysis(self, figure: Figure, key: str, **values) -> FigureAnalysis:
        return FigureAnalysis(
            id="an_" + uuid.uuid4().hex[:20],
            figure_id=figure.id,
            document_id=figure.document_id,
            cache_key=key,
            config_hash=self.config_hash,
            config=self.config(),
            figure_ref=self._figure_ref(figure),
            **values,
        )

    def _skipped(self, figure: Figure, message: str) -> FigureOutcome:
        return FigureOutcome(figure, AnalysisStatus.SKIPPED, "skipped", message=message)

    def _reuse(self, cached: FigureAnalysis, figure: Figure) -> FigureAnalysis:
        """Link a stored result to this figure without paying again.

        Used for the same crop and caption under another extraction run, and when the
        validation rules changed: the stored output is revalidated locally.
        """
        status, issues, spans = cached.status, cached.issues, cached.spans
        token_refs = cached.token_refs
        # Under another extraction run the same paragraphs have new ids: point the
        # passages that were sent to their copies in this run, so quotes stay traceable.
        context = remap_context(cached.context, self.repository.list_passages(figure.run_id))
        if cached.explanation is not None:
            caption = figure.caption.text if figure.caption else None
            truncated = [i for i in cached.issues if i.code == "truncated"]
            issues = (
                validate_explanation(cached.explanation, caption, context, figure_text(figure))
                + truncated
            )
            status = AnalysisStatus.INCOMPLETE if truncated else status_from_issues(issues)
            spans = resolve_spans(cached.explanation, context)
            token_refs = resolve_token_refs(cached.explanation, figure.tokens)
        analysis = cached.model_copy(
            update={
                "status": status,
                "issues": issues,
                "spans": spans,
                "context": context,
                "token_refs": token_refs,
                "validator_version": VALIDATOR_VERSION,
                "id": "an_" + uuid.uuid4().hex[:20],
                "figure_id": figure.id,
                "figure_ref": self._figure_ref(figure),
                "reused_from": cached.reused_from or cached.id,
                "created_at": utcnow(),
            }
        )
        self.repository.save_analysis(analysis)
        return analysis

    def _failed(self, job: _Job, exc: Exception) -> FigureOutcome:
        analysis = self._new_analysis(
            job.figure,
            job.cache_key,
            status=AnalysisStatus.FAILED,
            error=str(exc),
            context=job.context.passages,
            context_note=job.context.note,
        )
        self.repository.save_analysis(analysis)
        return FigureOutcome(job.figure, analysis.status, "model", analysis, message=str(exc))

    def _record(self, job: _Job, response: ModelResult) -> FigureAnalysis:
        run = AnalysisRun(
            provider=self.model.provider,
            model=self.model.model,
            model_version=response.model_version,
            prompt_version=PROMPT_VERSION,
            response_id=response.response_id,
            input_tokens=response.input_tokens,
            cached_input_tokens=response.cached_input_tokens,
            output_tokens=response.output_tokens,
            reasoning_tokens=response.reasoning_tokens,
            # Cached input is billed at a discount; charging full price keeps this an upper bound.
            estimated_cost_usd=round(
                self.pricing.cost(response.input_tokens, response.output_tokens), 8
            ),
            latency_ms=response.latency_ms,
            provider_status=response.provider_status,
            incomplete_reason=response.incomplete_reason,
        )
        truncated = response.provider_status == "incomplete"
        explanation = None
        issues: list[ValidationIssue] = []
        spans: list[SpanRef] = []
        token_refs: list = []
        context = job.context.passages
        if response.refusal:
            status = AnalysisStatus.INVALID
            issues.append(
                ValidationIssue(
                    code="refusal",
                    severity="error",
                    message=f"The model refused: {response.refusal}",
                )
            )
        elif not response.raw_text:
            status = AnalysisStatus.INCOMPLETE if truncated else AnalysisStatus.INVALID
            issues.append(
                ValidationIssue(
                    code="truncated" if truncated else "empty_response",
                    severity="error",
                    message=f"No output ({response.incomplete_reason or response.provider_status}).",
                )
            )
        else:
            try:
                explanation = Explanation.model_validate_json(response.raw_text)
            except ValidationError as exc:
                status = AnalysisStatus.INCOMPLETE if truncated else AnalysisStatus.INVALID
                issues.append(
                    ValidationIssue(
                        code="truncated" if truncated else "schema_violation",
                        severity="error",
                        message=(
                            f"Output cut off ({response.incomplete_reason})."
                            if truncated
                            else f"Output does not match the schema: {exc.error_count()} errors."
                        ),
                    )
                )
            else:
                caption = job.figure.caption.text if job.figure.caption else None
                issues = validate_explanation(
                    explanation, caption, context, figure_text(job.figure)
                )
                status = status_from_issues(issues)
                spans = resolve_spans(explanation, context)
                token_refs = resolve_token_refs(explanation, job.figure.tokens)
                if truncated:
                    status = AnalysisStatus.INCOMPLETE
                    issues.append(
                        ValidationIssue(
                            code="truncated",
                            severity="error",
                            message=f"Output cut off ({response.incomplete_reason}).",
                        )
                    )
        analysis = self._new_analysis(
            job.figure,
            job.cache_key,
            status=status,
            explanation=explanation,
            raw_output=response.raw_text,
            issues=issues,
            validator_version=VALIDATOR_VERSION,
            run=run,
            context=context,
            context_note=job.context.note,
            spans=spans,
            token_refs=token_refs,
        )
        self.repository.save_analysis(analysis)
        return analysis


def remap_context(context: list[ContextPassage], passages: list[Passage]) -> list[ContextPassage]:
    """Give each sent passage the id of the paragraph with the same text in ``passages``."""
    out = []
    for sent in context:
        match = next(
            (
                p
                for p in passages
                if p.text[sent.offset : sent.offset + len(sent.text)] == sent.text
                and p.page_index + 1 <= sent.page
            ),
            None,
        )
        out.append(sent.model_copy(update={"passage_id": match.id}) if match else sent)
    return out


def figure_text(figure: Figure) -> str | None:
    """Text printed in the figure, or None when no evidence layer ran for it."""
    return " ".join(t.text for t in figure.tokens) if figure.tokens else None


def build_analyzer(
    settings: AnalysisSettings,
    repository: Repository,
    blobs: BlobStore,
    model_id: str | None = None,
) -> FigureAnalyzer:
    """Analyzer for the configured provider; raise AnalysisUnavailable if it cannot run."""
    import os

    model_id = model_id or settings.primary_model
    if model_id not in settings.allowed_models:
        raise AnalysisUnavailable(f"Model {model_id!r} is not in SFI_ALLOWED_MODELS.")
    settings.pricing(model_id)
    if not os.environ.get("OPENAI_API_KEY"):
        raise AnalysisUnavailable("OPENAI_API_KEY is not set (see .env.example).")
    from sfi.analysis.providers import OpenAIMultimodalModel

    model = OpenAIMultimodalModel(model_id, timeout_s=settings.timeout_s)
    try:
        model.check()
    except ProviderFatalError as exc:
        raise AnalysisUnavailable(str(exc)) from exc
    return FigureAnalyzer(settings, repository, blobs, model)
