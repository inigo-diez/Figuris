"""Stage 4: local web application, API and background jobs.

The worker runs synchronously (``run_pending``) and the model is the scripted fake.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sfi.analysis.analyzer import AnalysisUnavailable, FigureAnalyzer
from sfi.config import AnalysisSettings, Settings
from sfi.domain.models import JobStatus
from sfi.storage.repository import SQLiteRepository
from sfi.web.app import create_app
from tests.test_analysis import FakeModel
from tests.test_context import build_article


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", render_dpi=72, max_pdf_mb=1, max_pages=5)


@pytest.fixture
def model():
    return FakeModel()


@pytest.fixture
def app(settings, model):
    def factory(settings, repository, blobs):
        return FigureAnalyzer(AnalysisSettings(concurrency=1), repository, blobs, model)

    return create_app(settings, analyzer_factory=factory, start_worker=False)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def upload(client, data: bytes, name: str = "article.pdf"):
    return client.post("/api/documents", files={"file": (name, data, "application/pdf")})


def process(client, app) -> dict:
    job = upload(client, build_article()).json()
    assert job["status"] == "queued" and job["active"]
    assert app.state.runner.run_pending() == 1
    return client.get(f"/api/jobs/{job['id']}").json()


def test_frontend_is_served_with_a_restrictive_policy(client):
    page = client.get("/")
    assert page.status_code == 200 and "/static/app.js" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "empty"),
        (b"<html>not a pdf</html>", "not_pdf"),
        (b"%PDF-1.7\nbroken", "unreadable"),
    ],
)
def test_invalid_uploads_are_rejected_before_queueing(client, data, code):
    response = upload(client, data)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == code
    assert client.get("/api/jobs").json() == []


def test_upload_is_processed_and_browsable(client, app, model):
    job = process(client, app)
    assert job["status"] == "completed", job
    assert job["figures_done"] == job["figures_total"] == 1
    doc_id = job["document_id"]

    [document] = client.get("/api/documents").json()
    assert (document["id"], document["figures"], document["explained"]) == (doc_id, 1, 1)

    detail = client.get(f"/api/documents/{doc_id}").json()
    [figure] = detail["figures"]
    assert figure["label"] == "Figure 1" and figure["analysis_status"] == "ok"
    assert figure["summary"] == "Dos patrones de difracción."

    full = client.get(f"/api/documents/{doc_id}/figures/{figure['id']}").json()
    assert full["analysis"]["status"] == "ok"
    assert full["analysis"]["explanation"]["claims"][0]["id"] == "c1"
    assert full["analysis"]["context"], "the passages that mention Figure 1 are sent"
    assert full["pages"] == 2 and full["position"] == 1 and full["next"] is None
    x0, y0, x1, y1 = full["box"]
    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1

    image = client.get(f"/api/figures/{figure['id']}/image")
    assert image.headers["content-type"] == "image/png" and image.content[:4] == b"\x89PNG"
    page = client.get(f"/api/documents/{doc_id}/pages/2")
    assert page.content[:4] == b"\x89PNG"
    assert client.get(f"/api/documents/{doc_id}/pages/3").status_code == 404
    pdf = client.get(f"/api/documents/{doc_id}/pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert len(model.requests) == 1


def test_reprocessing_reuses_cached_results(client, app, model):
    doc_id = process(client, app)["document_id"]
    job = client.post(f"/api/documents/{doc_id}/reprocess")
    assert job.status_code == 202
    assert client.post(f"/api/documents/{doc_id}/reprocess").status_code == 409  # still queued
    app.state.runner.run_pending()
    assert client.get(f"/api/jobs/{job.json()['id']}").json()["status"] == "completed"
    assert len(model.requests) == 1  # nothing paid twice


def test_missing_api_key_still_extracts_and_warns(settings):
    def unavailable(settings, repository, blobs):
        raise AnalysisUnavailable("OPENAI_API_KEY is not set")

    app = create_app(settings, analyzer_factory=unavailable, start_worker=False)
    with TestClient(app) as client:
        job = process(client, app)
    assert job["status"] == "completed"
    assert "sin explicar" in job["warnings"][0]
    assert job["figures_total"] == 1


def test_interrupted_jobs_are_resumed(client, app, settings):
    job_id = upload(client, build_article()).json()["id"]
    repository = SQLiteRepository(settings.database_path)
    job = repository.get_job(job_id)
    job.status = JobStatus.ANALYZING  # the server stopped while this job was running
    repository.save_job(job)
    assert repository.requeue_interrupted_jobs() == 1
    repository.close()
    app.state.runner.run_pending()
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "completed"


def test_unknown_resources_return_404(client):
    assert client.get("/api/documents/abcdef123456").status_code == 404
    assert client.get("/api/jobs/job_missing").status_code == 404
    assert client.get("/api/figures/fig_missing/image").status_code == 404


def test_documents_keep_the_uploaded_file_name(client, app):
    job = upload(client, build_article(), name="Smith 2024 - results.pdf").json()
    app.state.runner.run_pending()
    [document] = client.get("/api/documents").json()
    assert document["filename"] == "Smith 2024 - results.pdf"
    assert client.get(f"/api/jobs/{job['id']}").json()["filename"] == "Smith 2024 - results.pdf"


def test_figures_can_be_downloaded_and_exported(client, app):
    doc_id = process(client, app)["document_id"]
    [figure] = client.get(f"/api/documents/{doc_id}").json()["figures"]
    assert figure["box"] and figure["confidence"] > 0 and figure["kind"] == "figure"

    image = client.get(f"/api/figures/{figure['id']}/image?download=1")
    assert image.headers["content-disposition"] == 'attachment; filename="article-Figure_1.png"'

    thumb = client.get(f"/api/documents/{doc_id}/pages/1?thumb=1")
    full = client.get(f"/api/documents/{doc_id}/pages/1")
    assert thumb.content[:4] == b"\x89PNG" and len(thumb.content) < len(full.content)

    export = client.get(f"/api/documents/{doc_id}/export")
    assert export.headers["content-disposition"] == 'attachment; filename="article-figuras.json"'
    body = export.json()
    assert body["document"]["filename"] == "article.pdf"
    [item] = body["figures"]
    assert item["label"] == "Figure 1" and item["explanation"]["claims"][0]["id"] == "c1"
    assert client.get(f"/api/documents/{doc_id}/export?figures=other").json()["figures"] == []
