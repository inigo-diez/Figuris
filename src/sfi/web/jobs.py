"""Background processing of uploaded PDFs: a persistent job queue with one worker.

Jobs live in SQLite, so the queue survives a restart: jobs left running are queued
again when the worker starts. Re-running a job is safe and cheap because extraction
and explanations are cached by content; only what is missing costs money.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from sfi.analysis.analyzer import (
    AnalysisUnavailable,
    FigureAnalyzer,
    FigureOutcome,
    build_analyzer,
)
from sfi.analysis.schema import AnalysisStatus
from sfi.config import Settings
from sfi.domain.models import Job, JobStatus
from sfi.ingest import InvalidDocumentError
from sfi.pipeline import FigurePipeline
from sfi.storage.blobs import BlobStore
from sfi.storage.repository import Repository, SQLiteRepository

log = logging.getLogger(__name__)

AnalyzerFactory = Callable[[Settings, Repository, BlobStore], FigureAnalyzer]

INVALID_MESSAGES = {
    "empty": "El archivo está vacío.",
    "too_large": "El archivo supera el tamaño máximo permitido.",
    "not_pdf": "El archivo no es un PDF.",
    "encrypted": "El PDF está protegido con contraseña.",
    "unreadable": "El PDF está dañado o no se puede leer.",
    "no_pages": "El PDF no tiene páginas.",
    "too_many_pages": "El PDF tiene más páginas de las permitidas.",
}


def invalid_message(error: InvalidDocumentError) -> str:
    return INVALID_MESSAGES.get(error.code, "El PDF no se puede procesar.") + f" ({error})"


def default_analyzer_factory(
    settings: Settings, repository: Repository, blobs: BlobStore
) -> FigureAnalyzer:
    return build_analyzer(settings.analysis, repository, blobs)


class JobRunner:
    def __init__(
        self,
        settings: Settings,
        analyzer_factory: AnalyzerFactory = default_analyzer_factory,
        poll_seconds: float = 2.0,
    ):
        self.settings = settings
        self.analyzer_factory = analyzer_factory
        self.poll_seconds = poll_seconds
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def upload_dir(self) -> Path:
        return self.settings.data_dir / "uploads"

    def submit(
        self,
        repository: Repository,
        filename: str,
        data: bytes | None = None,
        path: Path | None = None,
        force_analysis: bool = False,
        document_id: str | None = None,
    ) -> Job:
        """Queue a PDF given as bytes (an upload) or as an existing file (a retry)."""
        job_id = "job_" + uuid.uuid4().hex[:16]
        if data is not None:
            self.upload_dir.mkdir(parents=True, exist_ok=True)
            path = self.upload_dir / f"{job_id}.pdf"
            path.write_bytes(data)
        job = Job(
            id=job_id,
            filename=filename,
            upload_path=str(path),
            force_analysis=force_analysis,
            document_id=document_id,  # known when reprocessing a stored document
        )
        repository.save_job(job)
        self._wake.set()
        return job

    def start(self) -> None:
        repository = SQLiteRepository(self.settings.database_path)
        resumed = repository.requeue_interrupted_jobs()
        repository.close()
        if resumed:
            log.info("Resuming %d interrupted job(s)", resumed)
        self._thread = threading.Thread(target=self._loop, name="sfi-jobs", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def _loop(self) -> None:
        pipeline = FigurePipeline.from_settings(self.settings)  # own connection for this thread
        while not self._stop.is_set():
            if not self.run_next(pipeline):
                self._wake.wait(self.poll_seconds)
                self._wake.clear()

    def run_pending(self) -> int:
        """Process every queued job in the calling thread (for tests and scripts)."""
        pipeline = FigurePipeline.from_settings(self.settings)
        count = 0
        while self.run_next(pipeline):
            count += 1
        return count

    def run_next(self, pipeline: FigurePipeline) -> bool:
        job = pipeline.repository.claim_next_job()
        if job is None:
            return False
        try:
            self._run(pipeline, job)
        except Exception as exc:  # never let one job kill the worker
            log.exception("Job %s failed", job.id)
            job.status = JobStatus.FAILED
            job.stage = "Error inesperado"
            job.error = f"{type(exc).__name__}: {exc}"
            pipeline.repository.save_job(job)
        return True

    def _run(self, pipeline: FigurePipeline, job: Job) -> None:
        repository = pipeline.repository
        repository.save_job(job)
        try:
            result = pipeline.process(Path(job.upload_path), filename=job.filename)
        except InvalidDocumentError as exc:
            job.status, job.stage, job.error = (
                JobStatus.FAILED,
                "PDF no válido",
                invalid_message(exc),
            )
            repository.save_job(job)
            self._cleanup(job)
            return
        except FileNotFoundError:
            job.status, job.stage = JobStatus.FAILED, "Archivo no encontrado"
            job.error = "El archivo subido ya no está disponible; vuelve a subirlo."
            repository.save_job(job)
            return

        job.document_id = result.document.id
        job.figures_total = len(result.figures)
        job.figures_done = 0
        job.status, job.stage = JobStatus.ANALYZING, "Explicando las figuras"
        repository.save_job(job)
        self._cleanup(job)  # the original is now in the blob store

        try:
            analyzer = self.analyzer_factory(self.settings, repository, pipeline.blobs)
        except AnalysisUnavailable as exc:
            job.warnings.append(f"Figuras extraídas pero sin explicar: {exc}")
            job.status, job.stage = JobStatus.COMPLETED, "Completado sin explicaciones"
            repository.save_job(job)
            return

        def progress(outcome: FigureOutcome) -> None:
            job.figures_done += 1
            repository.save_job(job)

        analysis = analyzer.analyze(
            result.document,
            result.figures,
            force=job.force_analysis,
            progress=progress,
            passages=result.passages,
        )
        statuses = [o.status for o in analysis.outcomes]
        failed = statuses.count(AnalysisStatus.FAILED)
        unreliable = statuses.count(AnalysisStatus.INVALID) + statuses.count(
            AnalysisStatus.INCOMPLETE
        )
        if analysis.stopped:
            job.warnings.append(f"Análisis detenido: {analysis.stopped}.")
        if failed:
            job.warnings.append(
                f"{failed} figura(s) no se pudieron explicar por un error del servicio; "
                "reprocesa el documento para reintentarlo."
            )
        if unreliable:
            job.warnings.append(f"{unreliable} explicación(es) marcadas como no fiables.")
        if analysis.fatal:
            job.status, job.stage = JobStatus.FAILED, "El servicio del modelo no está disponible"
            job.error = analysis.stopped
        else:
            job.status, job.stage = JobStatus.COMPLETED, "Completado"
        repository.save_job(job)

    def _cleanup(self, job: Job) -> None:
        path = Path(job.upload_path)
        if path.parent.resolve() == self.upload_dir.resolve():
            path.unlink(missing_ok=True)
