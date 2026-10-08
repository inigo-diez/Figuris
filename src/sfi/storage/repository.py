"""Persistence of IR entities. SQLite for the prototype; PostgreSQL from M3.

Entities are stored as validated JSON documents plus the columns needed for
lookups. Runs and figures are append-only: reprocessing with a different
configuration creates a new run instead of overwriting the previous one.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

from sfi.analysis.schema import FigureAnalysis
from sfi.domain.models import (
    Artifact,
    Document,
    Figure,
    Job,
    JobStatus,
    Passage,
    ProcessorRun,
    utcnow,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS figures (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    document_id TEXT NOT NULL REFERENCES documents(id),
    page_index INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    figure_id TEXT NOT NULL,  -- no FK: forced re-extraction rewrites figure rows
    document_id TEXT NOT NULL REFERENCES documents(id),
    cache_key TEXT NOT NULL,
    status TEXT NOT NULL,
    model TEXT,
    cost_usd REAL NOT NULL,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS passages (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    document_id TEXT NOT NULL REFERENCES documents(id),
    ordinal INTEGER NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS passages_by_run ON passages(run_id, ordinal);
CREATE INDEX IF NOT EXISTS runs_by_document ON runs(document_id, started_at);
CREATE INDEX IF NOT EXISTS figures_by_run ON figures(run_id, ordinal);
CREATE INDEX IF NOT EXISTS analyses_by_figure ON analyses(figure_id, created_at);
CREATE INDEX IF NOT EXISTS analyses_by_key ON analyses(cache_key, created_at);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    document_id TEXT,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_by_status ON jobs(status, created_at);
"""


class Repository(Protocol):
    def save_document(self, document: Document) -> None: ...
    def get_document(self, document_id: str) -> Document | None: ...
    def find_documents(self, id_prefix: str = "") -> list[Document]: ...
    def save_artifact(self, artifact: Artifact) -> None: ...
    def get_artifact(self, artifact_id: str) -> Artifact | None: ...
    def save_run(self, run: ProcessorRun) -> None: ...
    def get_run(self, run_id: str) -> ProcessorRun | None: ...
    def latest_completed_run(self, document_id: str) -> ProcessorRun | None: ...
    def replace_figures(self, run_id: str, figures: list[Figure]) -> None: ...
    def list_figures(self, run_id: str) -> list[Figure]: ...
    def get_figure(self, figure_id: str) -> Figure | None: ...
    def replace_passages(self, run_id: str, passages: list[Passage]) -> None: ...
    def list_passages(self, run_id: str) -> list[Passage]: ...
    def save_analysis(self, analysis: FigureAnalysis) -> None: ...
    def save_job(self, job: Job) -> None: ...
    def get_job(self, job_id: str) -> Job | None: ...
    def list_jobs(self, limit: int = 50) -> list[Job]: ...
    def claim_next_job(self) -> Job | None: ...
    def latest_analysis(self, figure_id: str) -> FigureAnalysis | None: ...
    def cached_analysis(self, cache_key: str, statuses: list[str]) -> FigureAnalysis | None: ...
    def analysis_spend(self) -> list[tuple[str, str, int, float]]: ...


class SQLiteRepository:
    def __init__(self, path: Path, check_same_thread: bool = True):
        path.parent.mkdir(parents=True, exist_ok=True)
        # One connection per thread or request; the web server and the job worker share the
        # file. WAL lets readers proceed while the worker writes; the timeout waits for locks.
        # A request's connection may be opened and used in different threads by the web
        # framework, but never concurrently, so the same-thread check can be relaxed there.
        self.connection = sqlite3.connect(path, timeout=30, check_same_thread=check_same_thread)
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def save_document(self, document: Document) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO documents (id, filename, created_at, body) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET body = excluded.body",
                (
                    document.id,
                    document.filename,
                    document.created_at.isoformat(),
                    document.model_dump_json(),
                ),
            )

    def get_document(self, document_id: str) -> Document | None:
        row = self.connection.execute(
            "SELECT body FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        return Document.model_validate_json(row[0]) if row else None

    def find_documents(self, id_prefix: str = "") -> list[Document]:
        rows = self.connection.execute(
            "SELECT body FROM documents WHERE id LIKE ? OR id LIKE ? ORDER BY created_at",
            (f"{id_prefix}%", f"sha256:{id_prefix}%"),
        ).fetchall()
        return [Document.model_validate_json(row[0]) for row in rows]

    def save_artifact(self, artifact: Artifact) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO artifacts (id, kind, body) VALUES (?, ?, ?)",
                (artifact.id, artifact.kind, artifact.model_dump_json()),
            )

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        row = self.connection.execute(
            "SELECT body FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        return Artifact.model_validate_json(row[0]) if row else None

    def save_run(self, run: ProcessorRun) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO runs (id, document_id, status, started_at, body) VALUES (?, ?, ?, ?, ?)",
                (
                    run.id,
                    run.document_id,
                    run.status,
                    run.started_at.isoformat(),
                    run.model_dump_json(),
                ),
            )

    def get_run(self, run_id: str) -> ProcessorRun | None:
        row = self.connection.execute("SELECT body FROM runs WHERE id = ?", (run_id,)).fetchone()
        return ProcessorRun.model_validate_json(row[0]) if row else None

    def latest_completed_run(self, document_id: str) -> ProcessorRun | None:
        row = self.connection.execute(
            "SELECT body FROM runs WHERE document_id = ? AND status = 'completed' "
            "ORDER BY started_at DESC LIMIT 1",
            (document_id,),
        ).fetchone()
        return ProcessorRun.model_validate_json(row[0]) if row else None

    def replace_figures(self, run_id: str, figures: list[Figure]) -> None:
        """Store the figures of one run (a retried run replaces its own partial output)."""
        with self.connection:
            self.connection.execute("DELETE FROM figures WHERE run_id = ?", (run_id,))
            self.connection.executemany(
                "INSERT INTO figures (id, run_id, document_id, page_index, ordinal, body) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (f.id, run_id, f.document_id, f.page_index, i, f.model_dump_json())
                    for i, f in enumerate(figures)
                ],
            )

    def get_figure(self, figure_id: str) -> Figure | None:
        row = self.connection.execute(
            "SELECT body FROM figures WHERE id = ?", (figure_id,)
        ).fetchone()
        return Figure.model_validate_json(row[0]) if row else None

    def list_figures(self, run_id: str) -> list[Figure]:
        rows = self.connection.execute(
            "SELECT body FROM figures WHERE run_id = ? ORDER BY ordinal", (run_id,)
        ).fetchall()
        return [Figure.model_validate_json(row[0]) for row in rows]

    def replace_passages(self, run_id: str, passages: list[Passage]) -> None:
        """Store the article text of one run (a retried run replaces its own output)."""
        with self.connection:
            self.connection.execute("DELETE FROM passages WHERE run_id = ?", (run_id,))
            self.connection.executemany(
                "INSERT INTO passages (id, run_id, document_id, ordinal, body) VALUES (?, ?, ?, ?, ?)",
                [(p.id, run_id, p.document_id, p.ordinal, p.model_dump_json()) for p in passages],
            )

    def list_passages(self, run_id: str) -> list[Passage]:
        rows = self.connection.execute(
            "SELECT body FROM passages WHERE run_id = ? ORDER BY ordinal", (run_id,)
        ).fetchall()
        return [Passage.model_validate_json(row[0]) for row in rows]

    def save_analysis(self, analysis: FigureAnalysis) -> None:
        """Append one analysis attempt; earlier attempts are kept for audit and cost."""
        with self.connection:
            self.connection.execute(
                "INSERT INTO analyses (id, figure_id, document_id, cache_key, status, model, cost_usd, created_at, body) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    analysis.id,
                    analysis.figure_id,
                    analysis.document_id,
                    analysis.cache_key,
                    analysis.status.value,
                    analysis.run.model if analysis.run else None,
                    analysis.cost_usd,
                    analysis.created_at.isoformat(),
                    analysis.model_dump_json(),
                ),
            )

    def latest_analysis(self, figure_id: str) -> FigureAnalysis | None:
        row = self.connection.execute(
            "SELECT body FROM analyses WHERE figure_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (figure_id,),
        ).fetchone()
        return FigureAnalysis.model_validate_json(row[0]) if row else None

    def cached_analysis(self, cache_key: str, statuses: list[str]) -> FigureAnalysis | None:
        marks = ", ".join("?" for _ in statuses)
        row = self.connection.execute(
            f"SELECT body FROM analyses WHERE cache_key = ? AND status IN ({marks}) "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (cache_key, *statuses),
        ).fetchone()
        return FigureAnalysis.model_validate_json(row[0]) if row else None

    def analysis_spend(self) -> list[tuple[str, str, int, float]]:
        """(document_id, model, calls, usd) for every model call ever recorded."""
        return self.connection.execute(
            "SELECT document_id, model, COUNT(*), SUM(cost_usd) FROM analyses "
            "WHERE model IS NOT NULL AND cost_usd > 0 GROUP BY document_id, model ORDER BY document_id"
        ).fetchall()

    def save_job(self, job: Job) -> None:
        job.updated_at = utcnow()
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO jobs (id, status, document_id, created_at, body) VALUES (?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.status.value,
                    job.document_id,
                    job.created_at.isoformat(),
                    job.model_dump_json(),
                ),
            )

    def get_job(self, job_id: str) -> Job | None:
        row = self.connection.execute("SELECT body FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def list_jobs(self, limit: int = 50) -> list[Job]:
        rows = self.connection.execute(
            "SELECT body FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Job.model_validate_json(row[0]) for row in rows]

    def claim_next_job(self) -> Job | None:
        """Take the oldest queued job, marking it as started in the same transaction."""
        with self.connection:
            row = self.connection.execute(
                "SELECT body FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            job = Job.model_validate_json(row[0])
            job.status = JobStatus.EXTRACTING
            job.stage = "Extrayendo figuras y texto"
            job.updated_at = utcnow()
            claimed = self.connection.execute(
                "UPDATE jobs SET status = ?, body = ? WHERE id = ? AND status = 'queued'",
                (job.status.value, job.model_dump_json(), job.id),
            ).rowcount
        return job if claimed else None

    def requeue_interrupted_jobs(self) -> int:
        """Jobs left running by a stopped server are queued again (they are idempotent)."""
        count = 0
        for row in self.connection.execute(
            "SELECT body FROM jobs WHERE status IN ('extracting', 'analyzing')"
        ).fetchall():
            job = Job.model_validate_json(row[0])
            job.status = JobStatus.QUEUED
            job.stage = "En cola (reanudado tras reiniciar)"
            self.save_job(job)
            count += 1
        return count

    def latest_job_for_document(self, document_id: str) -> Job | None:
        row = self.connection.execute(
            "SELECT body FROM jobs WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
            (document_id,),
        ).fetchone()
        return Job.model_validate_json(row[0]) if row else None
