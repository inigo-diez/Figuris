"""Extraction pipeline: PDF -> validated document -> figures with captions and crops,
plus the article text as passages with their figure mentions."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from sfi.config import Settings
from sfi.context.mentions import MENTIONS_VERSION, find_mentions
from sfi.domain.models import (
    Artifact,
    BBox,
    Caption,
    Document,
    EvidenceToken,
    ExtractionWarning,
    Figure,
    FigureMention,
    PageInfo,
    Panel,
    Passage,
    PassageSegment,
    ProcessorRun,
    WarningCode,
    utcnow,
)
from sfi.extract.evidence import (
    EVIDENCE_VERSION,
    OCR_DPI,
    PANEL_ANCHORS_VERSION,
    OcrEngine,
    anchor_panels,
    figure_tokens,
    ocr_engine_for,
)
from sfi.extract.extractor import (
    PANEL_DPI,
    ExtractedFigure,
    FigureExtractor,
    PdfiumFigureExtractor,
)
from sfi.extract.layout import Box
from sfi.extract.render import render_region_png
from sfi.extract.text import TEXT_VERSION, TextPassage, passages_from_extraction
from sfi.ingest import open_pdf, validate_pdf_bytes
from sfi.storage.blobs import BlobStore, LocalBlobStore
from sfi.storage.repository import Repository, SQLiteRepository


@dataclass
class ProcessResult:
    document: Document
    run: ProcessorRun
    figures: list[Figure]
    cached: bool
    passages: list[Passage] = field(default_factory=list)


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _to_bbox(box: Box, page_height: float) -> BBox:
    left, bottom, right, top = box.to_pdf_bbox(page_height)
    return BBox(
        left=round(left, 2), bottom=round(bottom, 2), right=round(right, 2), top=round(top, 2)
    )


class FigurePipeline:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        blobs: BlobStore,
        extractor: FigureExtractor | None = None,
        ocr_engine: OcrEngine | None = None,
    ):
        self.settings = settings
        self.repository = repository
        self.blobs = blobs
        self.extractor = extractor or PdfiumFigureExtractor()
        self.ocr_engine = ocr_engine

    @classmethod
    def from_settings(cls, settings: Settings) -> FigurePipeline:
        return cls(
            settings,
            SQLiteRepository(settings.database_path),
            LocalBlobStore(settings.blob_dir),
            ocr_engine=ocr_engine_for(settings.figure_ocr),
        )

    def config(self) -> dict:
        engine = self.ocr_engine
        return {
            "extractor": self.extractor.config(),
            "render_dpi": self.settings.render_dpi,
            "text": TEXT_VERSION,
            "mentions": MENTIONS_VERSION,
            # Part of the run identity: changing the OCR engine yields a new run.
            "evidence": {
                "version": EVIDENCE_VERSION,
                "panels": PANEL_ANCHORS_VERSION,
                "ocr": f"{engine.name}-{engine.version}" if engine else None,
                "ocr_params": getattr(engine, "params", {}) if engine else None,
                "ocr_dpi": OCR_DPI if engine else None,
            },
        }

    def process(
        self, path: Path, force: bool = False, filename: str | None = None
    ) -> ProcessResult:
        """Process a PDF file; ``filename`` is the name to show (default: the file name)."""
        data = path.read_bytes()
        validate_pdf_bytes(data, self.settings.max_pdf_mb * 1024 * 1024)
        pdf = open_pdf(data, self.settings.max_pages)
        try:
            return self._process(pdf, data, filename or path.name, force)
        finally:
            pdf.close()

    def _process(self, pdf, data: bytes, filename: str, force: bool) -> ProcessResult:
        digest, key = self.blobs.put(data, "pdf")
        original = Artifact(
            id=digest,
            kind="original_pdf",
            media_type="application/pdf",
            byte_size=len(data),
            storage_key=key,
            producer="ingest",
            producer_version="0.1.0",
        )
        self.repository.save_artifact(original)

        pages = []
        for index in range(len(pdf)):
            page = pdf[index]
            left, bottom, right, top = page.get_cropbox()
            pages.append(
                PageInfo(
                    index=index,
                    width=round(right - left, 2),
                    height=round(top - bottom, 2),
                    rotation=page.get_rotation(),
                )
            )
        document = Document(
            id=f"sha256:{digest}",
            filename=filename,
            source_artifact_id=digest,
            page_count=len(pdf),
            pages=pages,
        )
        self.repository.save_document(document)

        config = self.config()
        config_hash = _hash(json.dumps(config, sort_keys=True))[:16]
        run_id = _hash(document.id, self.extractor.name, self.extractor.version, config_hash)[:32]
        existing = self.repository.get_run(run_id)
        if existing and existing.status == "completed" and not force:
            stored = self.repository.get_document(document.id) or document
            return ProcessResult(
                stored,
                existing,
                self.repository.list_figures(run_id),
                cached=True,
                passages=self.repository.list_passages(run_id),
            )

        run = ProcessorRun(
            id=run_id,
            document_id=document.id,
            producer=self.extractor.name,
            producer_version=self.extractor.version,
            config_hash=config_hash,
            config=config,
            status="running",
        )
        self.repository.save_run(run)
        started = time.perf_counter()
        try:
            result = self.extractor.extract(pdf)
            scanned = {layout.index for layout in result.pages if layout.is_scanned}
            figures = [
                self._persist_figure(pdf, document, run, extracted, ordinal, scanned)
                for ordinal, extracted in enumerate(result.figures)
            ]
            warnings = list(result.warnings)
            for page in document.pages:
                if page.rotation:
                    warnings.append(
                        ExtractionWarning(
                            code=WarningCode.ROTATED_PAGE,
                            page_index=page.index,
                            message=f"Page rotated {page.rotation}°: region coordinates may be off.",
                        )
                    )
            document.pages = [
                p.model_copy(update={"is_scanned": p.index in scanned}) for p in document.pages
            ]
            self.repository.save_document(document)
            self.repository.replace_figures(run.id, figures)
            passages = [
                self._to_passage(document, run, passage)
                for passage in passages_from_extraction(result)
            ]
            self.repository.replace_passages(run.id, passages)
            run.status = "completed"
            run.warnings = warnings
        except Exception as exc:
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            run.finished_at = utcnow()
            run.duration_ms = int((time.perf_counter() - started) * 1000)
            self.repository.save_run(run)
        return ProcessResult(document, run, figures, cached=False, passages=passages)

    def _to_passage(self, document: Document, run: ProcessorRun, passage: TextPassage) -> Passage:
        segments = []
        for segment in passage.segments:
            page = document.pages[segment.page_index]
            bbox = _to_bbox(segment.box, page.height)
            segments.append(
                PassageSegment(
                    page_index=segment.page_index,
                    char_start=segment.char_start,
                    bbox=bbox,
                    bbox_normalized=bbox.normalized(page.width, page.height),
                )
            )
        return Passage(
            id="psg_" + _hash(run.id, str(passage.ordinal))[:16],
            document_id=document.id,
            run_id=run.id,
            ordinal=passage.ordinal,
            page_index=passage.page_index,
            section=passage.section,
            back_matter=passage.back_matter,
            text=passage.text,
            segments=segments,
            mentions=[
                FigureMention(label=m.label, panels=m.panels, start=m.start, end=m.end, text=m.text)
                for m in find_mentions(passage.text)
            ],
            producer="pdfium-text",
            producer_version=TEXT_VERSION,
        )

    def _persist_figure(
        self,
        pdf,
        document: Document,
        run: ProcessorRun,
        extracted: ExtractedFigure,
        ordinal: int,
        scanned_pages: set[int] = frozenset(),
    ) -> Figure:
        page_info = document.pages[extracted.page_index]
        identity = extracted.label or f"unlabelled-{ordinal}"
        figure_id = "fig_" + _hash(run.id, str(extracted.page_index), identity)[:16]
        crop_id = None
        bbox = None
        if extracted.box is not None:
            png = render_region_png(
                pdf[extracted.page_index], extracted.box, self.settings.render_dpi
            )
            crop_digest, crop_key = self.blobs.put(png, "png")
            self.repository.save_artifact(
                Artifact(
                    id=crop_digest,
                    kind="figure_crop",
                    media_type="image/png",
                    byte_size=len(png),
                    storage_key=crop_key,
                    parent_ids=[document.source_artifact_id],
                    producer=run.producer,
                    producer_version=run.producer_version,
                )
            )
            crop_id = crop_digest
            bbox = _to_bbox(extracted.box, page_info.height)

        caption = None
        if extracted.caption is not None:
            candidate = extracted.caption
            caption = Caption(
                label=candidate.label,
                kind=candidate.kind,
                number=candidate.number,
                text=candidate.text,
                page_index=candidate.page_index,
                bbox=_to_bbox(candidate.box, page_info.height),
                score=candidate.score,
            )

        tokens = []
        read: list = []
        if extracted.box is not None:
            read = figure_tokens(
                pdf[extracted.page_index],
                extracted.box,
                self.ocr_engine,
                scanned=extracted.page_index in scanned_pages,
            )
            for token in read:
                token_box = _to_bbox(token.box, page_info.height)
                tokens.append(
                    EvidenceToken(
                        text=token.text,
                        bbox_normalized=token_box.normalized(page_info.width, page_info.height),
                        confidence=token.confidence,
                        source=token.source,
                    )
                )
        # Panels: around the letters printed in the figure when they determine them
        # (E02, docs/reports/stage5-panels.md), else the extractor's whitespace split.
        found = [
            (
                p.label,
                p.box,
                p.subcaption,
                p.confidence,
                "xy-cut+caption-order" if p.box else "caption",
            )
            for p in extracted.panels
        ]
        if extracted.panels and extracted.box is not None:
            anchored = anchor_panels(
                pdf[extracted.page_index],
                extracted.box,
                extracted.caption.text if extracted.caption else "",
                read,
                PANEL_DPI,
                self.ocr_engine,
            )
            if anchored:
                found = [(*panel, PANEL_ANCHORS_VERSION) for panel in anchored]
        panels = []
        for label, box, subcaption, confidence, method in found:
            panel_bbox = _to_bbox(box, page_info.height) if box else None
            panels.append(
                Panel(
                    label=label,
                    bbox=panel_bbox,
                    bbox_normalized=panel_bbox.normalized(page_info.width, page_info.height)
                    if panel_bbox
                    else None,
                    subcaption=subcaption,
                    confidence=confidence,
                    method=method,
                )
            )
        return Figure(
            id=figure_id,
            document_id=document.id,
            run_id=run.id,
            label=extracted.label,
            kind=extracted.kind,
            number=extracted.number,
            page_index=extracted.page_index,
            bbox=bbox,
            bbox_normalized=bbox.normalized(page_info.width, page_info.height) if bbox else None,
            caption=caption,
            crop_artifact_id=crop_id,
            status=extracted.status,
            confidence=extracted.confidence,
            warnings=extracted.warnings,
            panel_layout=extracted.panel_layout,
            panels=panels,
            tokens=tokens,
            producer=run.producer,
            producer_version=run.producer_version,
        )
