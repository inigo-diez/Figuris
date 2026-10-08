"""Pipeline: validation, persistence, provenance and caching."""

from __future__ import annotations

import pytest

from sfi.config import Settings
from sfi.ingest import InvalidDocumentError
from sfi.pipeline import FigurePipeline
from sfi.report import write_document_report
from tests.pdf_factory import Page, build_pdf, caption, paragraph, rect


@pytest.fixture
def pipeline(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", render_dpi=72, max_pdf_mb=1, max_pages=5)
    return FigurePipeline.from_settings(settings)


@pytest.fixture
def sample_pdf(tmp_path):
    page = Page(
        paragraph(60, 740, 8)
        + rect(100, 350, 400, 250)
        + caption(60, 335, "Figure 1.", "A synthetic chart.")
        + paragraph(60, 300, 10)
    )
    path = tmp_path / "sample.pdf"
    path.write_bytes(build_pdf([page]))
    return path


def test_process_persists_document_figures_and_crops(pipeline, sample_pdf):
    result = pipeline.process(sample_pdf)
    assert not result.cached
    assert result.run.status == "completed"
    [figure] = result.figures
    assert figure.label == "Figure 1"
    assert figure.document_id == result.document.id
    # Provenance: crop is stored and linked to the original PDF.
    crop = pipeline.repository.get_artifact(figure.crop_artifact_id)
    assert crop.parent_ids == [result.document.source_artifact_id]
    assert pipeline.blobs.path(crop.storage_key).read_bytes().startswith(b"\x89PNG")
    # Normalized box uses a top-left origin and page fractions.
    x0, y0, x1, y1 = figure.bbox_normalized
    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
    assert pipeline.repository.list_figures(result.run.id) == result.figures


def test_reprocessing_uses_cache_and_does_not_duplicate(pipeline, sample_pdf):
    first = pipeline.process(sample_pdf)
    second = pipeline.process(sample_pdf)
    assert second.cached
    assert second.run.id == first.run.id
    assert [f.id for f in second.figures] == [f.id for f in first.figures]
    assert len(pipeline.repository.find_documents()) == 1


def test_force_reprocessing_keeps_ids_stable(pipeline, sample_pdf):
    first = pipeline.process(sample_pdf)
    forced = pipeline.process(sample_pdf, force=True)
    assert not forced.cached
    assert [f.id for f in forced.figures] == [f.id for f in first.figures]


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"", "empty"),
        (b"<html>not a pdf</html>", "not_pdf"),
        (b"%PDF-1.7\nthis is not a valid document", "unreadable"),
    ],
)
def test_invalid_inputs_are_rejected_with_codes(pipeline, tmp_path, content, code):
    path = tmp_path / "bad.pdf"
    path.write_bytes(content)
    with pytest.raises(InvalidDocumentError) as error:
        pipeline.process(path)
    assert error.value.code == code


def test_limits_are_enforced(pipeline, tmp_path):
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.7\n" + b"0" * (2 * 1024 * 1024))
    with pytest.raises(InvalidDocumentError) as error:
        pipeline.process(big)
    assert error.value.code == "too_large"

    many = tmp_path / "many.pdf"
    many.write_bytes(build_pdf([Page(paragraph(60, 740, 3)) for _ in range(6)]))
    with pytest.raises(InvalidDocumentError) as error:
        pipeline.process(many)
    assert error.value.code == "too_many_pages"


def test_report_links_figures_to_their_page(pipeline, sample_pdf, tmp_path):
    result = pipeline.process(sample_pdf)
    path = write_document_report(
        result.document,
        result.run,
        result.figures,
        pipeline.repository,
        pipeline.blobs,
        tmp_path / "reports",
    )
    html = path.read_text(encoding="utf-8")
    figure = result.figures[0]
    assert f'id="page-1-{figure.id}"' in html
    assert f'href="#page-1-{figure.id}"' in html
    assert (path.parent / "figures" / f"{figure.id}.png").is_file()
