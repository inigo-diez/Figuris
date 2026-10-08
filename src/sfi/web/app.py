"""Local web application (Figuris): upload PDFs, follow progress, browse figures.

A typed JSON API (FastAPI) plus a static, build-free frontend in ``static/``. The
API is the contract: a React/TypeScript client can replace the frontend later
(ADR 0006). Bound to localhost; everything shown comes from the local database.

Text from PDFs is untrusted: the API returns it as JSON data and the frontend only
inserts it with ``textContent``, never as HTML.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import pypdfium2 as pdfium
from fastapi import FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from sfi.analysis.schema import AnalysisStatus, FigureAnalysis
from sfi.config import Settings
from sfi.domain.models import Document, Figure, Job
from sfi.extract.panels import PUBLISH_MIN_CONFIDENCE
from sfi.extract.render import render_page_png
from sfi.ingest import InvalidDocumentError, open_pdf, validate_pdf_bytes
from sfi.storage.blobs import LocalBlobStore
from sfi.storage.repository import SQLiteRepository
from sfi.web.deps import PAGE_DPI, THUMB_DPI, Repo, render_lock, short_id
from sfi.web.jobs import AnalyzerFactory, JobRunner, default_analyzer_factory, invalid_message
from sfi.web.review import create_review_router

STATIC = Path(__file__).parent / "static"
CROP_PADDING = 2.0  # points added around a figure by render_region_png


def create_app(
    settings: Settings | None = None,
    analyzer_factory: AnalyzerFactory = default_analyzer_factory,
    start_worker: bool = True,
) -> FastAPI:
    settings = settings or Settings.from_env()
    runner = JobRunner(settings, analyzer_factory)
    blobs = LocalBlobStore(settings.blob_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_worker:
            runner.start()
        yield
        if start_worker:
            runner.stop()

    app = FastAPI(title="Figuris", version="0.5.0", lifespan=lifespan)
    app.state.runner = runner
    app.state.settings = settings

    def get_document(repo: SQLiteRepository, document_id: str) -> Document:
        found = repo.find_documents(document_id) if len(document_id) >= 8 else []
        if len(found) != 1:
            raise HTTPException(404, "Documento no encontrado.")
        return found[0]

    def document_figures(repo: SQLiteRepository, document: Document) -> list[Figure]:
        run = repo.latest_completed_run(document.id)
        return repo.list_figures(run.id) if run else []

    # --- status and documents -----------------------------------------------------------

    @app.get("/api/status")
    def status(repo: Repo) -> dict:
        analysis = settings.analysis
        spent = sum(row[3] for row in repo.analysis_spend())
        return {
            "analysis_configured": bool(os.environ.get("OPENAI_API_KEY")),
            "model": analysis.primary_model,
            "budget_usd": analysis.total_budget_usd,
            "spent_usd": round(spent, 4),
            "max_pdf_mb": settings.max_pdf_mb,
            "max_pages": settings.max_pages,
        }

    @app.get("/api/documents")
    def list_documents(repo: Repo) -> list[dict]:
        out = []
        for document in reversed(repo.find_documents()):
            figures = document_figures(repo, document)
            analyses = [a for f in figures if (a := repo.latest_analysis(f.id))]
            job = repo.latest_job_for_document(document.id)
            out.append(
                {
                    "id": short_id(document.id),
                    "filename": document.filename,
                    "pages": document.page_count,
                    "figures": len(figures),
                    "explained": sum(1 for a in analyses if a.status == AnalysisStatus.OK),
                    "unreliable": sum(
                        1
                        for a in analyses
                        if a.status in (AnalysisStatus.INVALID, AnalysisStatus.INCOMPLETE)
                    ),
                    "created_at": document.created_at.isoformat(),
                    "job": job_json(job) if job else None,
                }
            )
        return out

    @app.post("/api/documents", status_code=202)
    async def upload(file: UploadFile, repo: Repo) -> dict:
        limit = settings.max_pdf_mb * 1024 * 1024
        data = await file.read(limit + 1)
        try:
            validate_pdf_bytes(data, limit)
            open_pdf(data, settings.max_pages).close()
        except InvalidDocumentError as exc:
            raise HTTPException(400, {"code": exc.code, "message": invalid_message(exc)}) from exc
        name = Path(file.filename or "documento.pdf").name
        job = runner.submit(repo, name, data=data)
        return job_json(job)

    @app.get("/api/jobs")
    def list_jobs(repo: Repo) -> list[dict]:
        return [job_json(j) for j in repo.list_jobs(30)]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, repo: Repo) -> dict:
        job = repo.get_job(job_id)
        if job is None:
            raise HTTPException(404, "Trabajo no encontrado.")
        return job_json(job)

    @app.post("/api/documents/{document_id}/reprocess", status_code=202)
    def reprocess(document_id: str, repo: Repo) -> dict:
        """Queue the document again: cached results are reused, failed figures retried."""
        document = get_document(repo, document_id)
        active = repo.latest_job_for_document(document.id)
        if active and active.active:
            raise HTTPException(409, "El documento ya se está procesando.")
        original = repo.get_artifact(document.source_artifact_id)
        job = runner.submit(
            repo, document.filename, path=blobs.path(original.storage_key), document_id=document.id
        )
        return job_json(job)

    @app.get("/api/documents/{document_id}")
    def document_detail(document_id: str, repo: Repo) -> dict:
        document = get_document(repo, document_id)
        run = repo.latest_completed_run(document.id)
        figures = document_figures(repo, document)
        items = []
        for figure in figures:
            analysis = repo.latest_analysis(figure.id)
            page = document.pages[figure.page_index]
            items.append(
                {
                    "id": figure.id,
                    "label": figure.label,
                    "kind": figure.kind,
                    "page": figure.page_index + 1,
                    "status": figure.status,
                    "confidence": figure.confidence,
                    "box": figure.bbox_normalized,
                    "caption_box": figure.caption.bbox.normalized(page.width, page.height)
                    if figure.caption
                    else None,
                    "caption_page": figure.caption.page_index + 1 if figure.caption else None,
                    "has_image": figure.crop_artifact_id is not None,
                    "caption": figure.caption.text if figure.caption else None,
                    "panels": len(figure.panels),
                    "analysis_status": analysis.status.value if analysis else None,
                    "figure_type": analysis.explanation.figure_type
                    if analysis and analysis.explanation
                    else [],
                    "summary": analysis.explanation.summary
                    if analysis and analysis.explanation
                    else None,
                }
            )
        job = repo.latest_job_for_document(document.id)
        return {
            "id": short_id(document.id),
            "filename": document.filename,
            "pages": document.page_count,
            "page_sizes": [[p.width, p.height] for p in document.pages],
            "figures": items,
            "warnings": [w.message for w in run.warnings if w.code.value != "scanned_page"]
            if run
            else [],
            "job": job_json(job) if job else None,
        }

    @app.get("/api/documents/{document_id}/figures/{figure_id}")
    def figure_detail(document_id: str, figure_id: str, repo: Repo) -> dict:
        document = get_document(repo, document_id)
        figures = document_figures(repo, document)
        index = next((i for i, f in enumerate(figures) if f.id == figure_id), None)
        if index is None:
            raise HTTPException(404, "Figura no encontrada.")
        figure = figures[index]
        page = document.pages[figure.page_index]
        analysis = repo.latest_analysis(figure.id)
        passages = {p.id: p for p in repo.list_passages(figure.run_id)}
        cited = {}
        if analysis:
            for span in analysis.spans:
                passage = passages.get(span.passage_id)
                if passage and passage.id not in cited:
                    cited[passage.id] = {
                        "id": passage.id,
                        "section": passage.section,
                        "segments": [
                            {"page": s.page_index + 1, "box": s.bbox_normalized}
                            for s in passage.segments
                        ],
                    }
        return {
            "id": figure.id,
            "document_id": short_id(document.id),
            "filename": document.filename,
            "pages": document.page_count,
            "label": figure.label,
            "kind": figure.kind,
            "page": figure.page_index + 1,
            "status": figure.status,
            "confidence": figure.confidence,
            "box": figure.bbox_normalized,
            "size_pt": [round(figure.bbox.width, 1), round(figure.bbox.height, 1)]
            if figure.bbox
            else None,
            "figure_type": analysis.explanation.figure_type
            if analysis and analysis.explanation
            else [],
            "caption": figure.caption.text if figure.caption else None,
            "caption_box": figure.caption.bbox.normalized(page.width, page.height)
            if figure.caption
            else None,
            "caption_page": figure.caption.page_index + 1 if figure.caption else None,
            "warnings": [w.message for w in figure.warnings],
            "has_image": figure.crop_artifact_id is not None,
            "panel_layout": figure.panel_layout,
            "panels": panels_json(figure, page.width, page.height),
            "previous": figures[index - 1].id if index > 0 else None,
            "next": figures[index + 1].id if index + 1 < len(figures) else None,
            "position": index + 1,
            "count": len(figures),
            "analysis": analysis_json(analysis) if analysis else None,
            "token_refs": token_refs_json(analysis, figure, page.width, page.height)
            if analysis
            else [],
            "tokens": len(figure.tokens),
            "passages": list(cited.values()),
        }

    # --- binary content ------------------------------------------------------------------

    @app.get("/api/figures/{figure_id}/image")
    def figure_image(figure_id: str, repo: Repo, download: bool = False):
        figure = repo.get_figure(figure_id)
        if figure is None:
            raise HTTPException(404, "Figura no encontrada.")
        if not figure.crop_artifact_id:
            raise HTTPException(404, "La figura no tiene imagen.")
        artifact = repo.get_artifact(figure.crop_artifact_id)
        headers = {"Cache-Control": "max-age=86400, immutable"}
        if download:
            document = repo.get_document(figure.document_id)
            stem = Path(document.filename).stem if document else "figura"
            label = figure.label or f"figura-p{figure.page_index + 1}"
            headers["Content-Disposition"] = (
                f'attachment; filename="{safe_filename(f"{stem}-{label}")}.png"'
            )
        return FileResponse(
            blobs.path(artifact.storage_key), media_type="image/png", headers=headers
        )

    @app.get("/api/documents/{document_id}/pages/{number}")
    def page_image(document_id: str, number: int, repo: Repo, thumb: bool = False):
        document = get_document(repo, document_id)
        if not 1 <= number <= document.page_count:
            raise HTTPException(404, "Página fuera de rango.")
        dpi = THUMB_DPI if thumb else PAGE_DPI
        target = settings.data_dir / "pages" / short_id(document.id) / f"p{number}-{dpi}.png"
        if not target.exists():
            original = repo.get_artifact(document.source_artifact_id)
            with render_lock:
                if not target.exists():
                    pdf = pdfium.PdfDocument(blobs.path(original.storage_key))
                    try:
                        png = render_page_png(pdf[number - 1], dpi)
                    finally:
                        pdf.close()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(png)
        return FileResponse(
            target, media_type="image/png", headers={"Cache-Control": "max-age=86400"}
        )

    @app.get("/api/documents/{document_id}/export")
    def export_document(
        document_id: str,
        repo: Repo,
        figures: str | None = Query(None, description="Comma-separated figure ids; all if absent"),
    ) -> Response:
        """The document's figures as a JSON file: region, caption, panels and explanation."""
        document = get_document(repo, document_id)
        chosen = set(figures.split(",")) if figures else None
        items = []
        for figure in document_figures(repo, document):
            if chosen is not None and figure.id not in chosen:
                continue
            analysis = repo.latest_analysis(figure.id)
            explanation = analysis.explanation if analysis else None
            items.append(
                {
                    "id": figure.id,
                    "label": figure.label,
                    "kind": figure.kind,
                    "page": figure.page_index + 1,
                    "box_normalized": figure.bbox_normalized,
                    "detection_confidence": figure.confidence,
                    "status": figure.status,
                    "caption": figure.caption.text if figure.caption else None,
                    "panels": [
                        {"label": p.label, "subcaption": p.subcaption} for p in figure.panels
                    ],
                    "analysis_status": analysis.status.value if analysis else None,
                    "explanation": explanation.model_dump() if explanation else None,
                }
            )
        body = {
            "document": {
                "id": short_id(document.id),
                "filename": document.filename,
                "pages": document.page_count,
            },
            "exported_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "figures": items,
        }
        name = safe_filename(f"{Path(document.filename).stem}-figuras")
        return Response(
            json.dumps(body, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}.json"'},
        )

    @app.get("/api/documents/{document_id}/pdf")
    def original_pdf(document_id: str, repo: Repo):
        document = get_document(repo, document_id)
        original = repo.get_artifact(document.source_artifact_id)
        return FileResponse(
            blobs.path(original.storage_key),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{short_id(document.id)}.pdf"'},
        )

    # --- frontend ------------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "frame-ancestors 'none'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    app.include_router(create_review_router(settings, document_figures))
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def safe_filename(text: str) -> str:
    """An ASCII download name without quotes, separators or control characters."""
    return re.sub(r"[^\w.-]+", "_", text, flags=re.ASCII).strip("._")[:120] or "figuris"


def job_json(job: Job) -> dict:
    return {
        "id": job.id,
        "filename": job.filename,
        "status": job.status.value,
        "active": job.active,
        "stage": job.stage,
        "document_id": short_id(job.document_id) if job.document_id else None,
        "figures_total": job.figures_total,
        "figures_done": job.figures_done,
        "warnings": job.warnings,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def crop_box(figure: Figure, page_width: float, page_height: float):
    """The region of the figure image on the page (render_region_png adds CROP_PADDING)."""
    if not figure.bbox_normalized:
        return None
    x0, y0, x1, y1 = figure.bbox_normalized
    px, py = CROP_PADDING / page_width, CROP_PADDING / page_height
    return (max(0.0, x0 - px), max(0.0, y0 - py), min(1.0, x1 + px), min(1.0, y1 + py))


def in_image(box, crop) -> list[float] | None:
    """A page-normalized box as fractions of the figure image."""
    if not box or not crop:
        return None
    width, height = crop[2] - crop[0], crop[3] - crop[1]
    return [
        round((box[0] - crop[0]) / width, 4),
        round((box[1] - crop[1]) / height, 4),
        round((box[2] - crop[0]) / width, 4),
        round((box[3] - crop[1]) / height, 4),
    ]


def token_refs_json(analysis: FigureAnalysis, figure: Figure, page_width, page_height) -> list:
    crop = crop_box(figure, page_width, page_height)
    return [
        {
            "claim_id": ref.claim_id,
            "value": ref.value,
            "text": ref.text,
            "source": ref.source,
            "box": ref.bbox_normalized,
            "image_box": in_image(ref.bbox_normalized, crop),
        }
        for ref in analysis.token_refs
    ]


def panels_json(figure: Figure, page_width: float, page_height: float) -> list[dict]:
    """Panels with their box on the page and on the figure image."""
    crop = crop_box(figure, page_width, page_height)
    out = []
    for panel in figure.panels:
        # Boxes below the calibrated confidence stay stored (for evaluation) but unshown.
        box = panel.bbox_normalized if panel.confidence >= PUBLISH_MIN_CONFIDENCE else None
        in_crop = in_image(box, crop)
        out.append(
            {
                "label": panel.label,
                "box": box,
                "image_box": in_crop,
                "subcaption": panel.subcaption,
                "confidence": panel.confidence,
            }
        )
    return out


def analysis_json(analysis: FigureAnalysis) -> dict:
    run = analysis.run
    return {
        "status": analysis.status.value,
        "explanation": analysis.explanation.model_dump() if analysis.explanation else None,
        "issues": [i.model_dump() for i in analysis.issues],
        "spans": [s.model_dump() for s in analysis.spans],
        "context": [
            {
                "ref": c.ref,
                "page": c.page,
                "section": c.section,
                "text": c.text,
                "truncated": c.truncated,
            }
            for c in analysis.context
        ],
        "context_note": analysis.context_note,
        "error": analysis.error,
        "run": {
            "model": run.model_version or run.model,
            "prompt_version": run.prompt_version,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "cost_usd": run.estimated_cost_usd,
            "latency_s": round(run.latency_ms / 1000, 1),
            "reused": analysis.reused_from is not None,
            "created_at": analysis.created_at.isoformat(),
        }
        if run
        else None,
    }
