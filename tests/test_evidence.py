"""Stage 5: evidence layer, the text inside figures (PDF text layer and OCR)."""

from __future__ import annotations

import numpy as np
import pypdfium2 as pdfium
import pytest

from sfi.analysis.schema import Explanation
from sfi.analysis.validate import resolve_token_refs, validate_explanation
from sfi.config import Settings
from sfi.domain.models import EvidenceToken
from sfi.extract.evidence import (
    SCANNED_LAYER_CONFIDENCE,
    figure_tokens,
    numbers_in,
    ocr_tokens,
    pdf_tokens,
)
from sfi.extract.layout import Box
from sfi.pipeline import FigurePipeline
from sfi.storage.blobs import LocalBlobStore
from sfi.storage.repository import SQLiteRepository
from tests.pdf_factory import Page, build_pdf, caption, paragraph, rect, text
from tests.test_analysis import explanation

# A figure (grey rectangle) with a value printed inside it, as in a vector chart.
FIGURE = Box(100, 142, 400, 342)  # top-left origin: rect(100, 450, 300, 200) on a 792 pt page


def article() -> bytes:
    page = Page(
        rect(100, 450, 300, 200, gray=0.85)
        + text(150, 600, "Peak 42.5 mV", size=14)
        + caption(100, 430, "Figure 1.", "Membrane potential of treated cells.")
        + paragraph(72, 380, 12)
    )
    return build_pdf([page])


class FakeOcr:
    name = "fake"
    version = "1"

    def __init__(self, lines):
        self.lines = lines
        self.images = []

    def read(self, image):
        self.images.append(image.shape)
        return self.lines


def test_pdf_words_inside_the_figure_become_tokens():
    pdf = pdfium.PdfDocument(article())
    tokens = pdf_tokens(pdf[0], FIGURE)
    assert [t.text for t in tokens] == ["Peak", "42.5", "mV"]
    assert all(t.source == "pdf" and t.confidence == 1.0 for t in tokens)
    value = tokens[1].box
    assert FIGURE.x0 < value.x0 < value.x1 < FIGURE.x1 and FIGURE.y0 < value.y0 < FIGURE.y1
    assert pdf_tokens(pdf[0], Box(400, 0, 612, 100)) == []  # nothing printed there
    scanned = pdf_tokens(pdf[0], FIGURE, scanned=True)
    assert {(t.source, t.confidence) for t in scanned} == {("pdf-ocr", SCANNED_LAYER_CONFIDENCE)}


def test_ocr_adds_what_the_pdf_text_does_not_cover():
    pdf = pdfium.PdfDocument(article())
    # Pixels at 72 dpi equal points: one line over the PDF word "42.5", one elsewhere.
    native = pdf_tokens(pdf[0], FIGURE)[1].box
    over = [
        [native.x0 - FIGURE.x0, native.y0 - FIGURE.y0],
        [native.x1 - FIGURE.x0, native.y0 - FIGURE.y0],
        [native.x1 - FIGURE.x0, native.y1 - FIGURE.y0],
        [native.x0 - FIGURE.x0, native.y1 - FIGURE.y0],
    ]
    elsewhere = [[10, 150], [60, 150], [60, 170], [10, 170]]
    engine = FakeOcr([("42.5", over, 0.99), ("n=12", elsewhere, 0.8)])
    tokens = figure_tokens(pdf[0], FIGURE, engine, dpi=72)
    assert engine.images == [(200, 300, 3)]
    assert [(t.text, t.source) for t in tokens] == [
        ("Peak", "pdf"),
        ("42.5", "pdf"),
        ("mV", "pdf"),
        ("n=12", "ocr:fake-1"),
    ]
    added = tokens[-1].box
    assert (added.x0, added.y0, added.x1, added.y1) == (110, 292, 160, 312)
    assert numbers_in("−0.5 to 10,2") == ["-0.5", "10,2"]


def claim(text, kind="observed", approximate=False):
    return {
        "id": "c1",
        "type": kind,
        "text": text,
        "panels": [],
        "evidence": [{"kind": "figure_region", "panel": None, "quote": None}],
        "approximate": approximate,
        "confidence": "high",
    }


def figure_issues(text, figure_text, **kind):
    data = explanation(claims=[claim(text, **kind)], main_findings=["c1"], limitations=[])
    data["interpretation"] = {"text": "x", "claim_ids": ["c1"]}
    data["role_in_article"] = {"text": "x", "claim_ids": ["c1"]}
    data["limitations_justification"] = "Nada incierto."
    return {
        i.code: i.severity
        for i in validate_explanation(Explanation.model_validate(data), None, (), figure_text)
    }


def test_numbers_read_in_the_figure_are_checked_against_its_text():
    assert figure_issues("El pico vale 42.5 mV.", "Peak 42.5 mV") == {}
    assert figure_issues("El pico vale 42,5 mV.", "Peak 42.5 mV") == {}  # decimal comma
    assert figure_issues("El pico vale 47.5 mV.", "Peak 42.5 mV") == {
        "number_not_in_figure": "warning"
    }
    assert figure_issues("El pico vale 47.5 mV.", "Peak 42.5", approximate=True) == {}
    assert figure_issues("El pico vale 47.5 mV.", None) == {}  # no evidence layer ran


def test_claim_values_link_to_where_they_are_printed():
    tokens = [
        EvidenceToken(
            text="42.5", bbox_normalized=(0.2, 0.2, 0.3, 0.25), confidence=1.0, source="pdf"
        ),
        EvidenceToken(
            text="10", bbox_normalized=(0.1, 0.9, 0.12, 0.92), confidence=0.9, source="ocr:x-1"
        ),
    ]
    data = explanation(claims=[claim("Sube de 10 a 42.5; nunca llega a 50.")])
    refs = resolve_token_refs(Explanation.model_validate(data), tokens)
    assert [(r.value, r.text, r.source) for r in refs] == [
        ("10", "10", "ocr:x-1"),
        ("42.5", "42.5", "pdf"),
    ]
    data = explanation(claims=[claim("Sube a 42.5.", approximate=True)])
    assert resolve_token_refs(Explanation.model_validate(data), tokens) == []


def test_pipeline_stores_the_tokens_and_the_ocr_in_the_run(tmp_path):
    path = tmp_path / "article.pdf"
    path.write_bytes(article())
    settings = Settings(data_dir=tmp_path / "data", render_dpi=72, max_pdf_mb=1, max_pages=5)
    pipeline = FigurePipeline(
        settings,
        SQLiteRepository(settings.database_path),
        LocalBlobStore(settings.blob_dir),
        ocr_engine=FakeOcr([]),
    )
    result = pipeline.process(path)
    [figure] = result.figures
    assert [t.text for t in figure.tokens] == ["Peak", "42.5", "mV"]
    x0, y0, x1, y1 = figure.tokens[1].bbox_normalized
    assert 0 < x0 < x1 < 1 and 0 < y0 < y1 < 1
    assert result.run.config["evidence"]["ocr"] == "fake-1"
    without = FigurePipeline(
        settings, SQLiteRepository(settings.database_path), LocalBlobStore(settings.blob_dir)
    )
    assert without.config()["evidence"]["ocr"] is None
    assert without.process(path).run.id != result.run.id  # OCR is part of the run identity


def test_rapidocr_reads_a_rendered_value():
    rapidocr = pytest.importorskip("rapidocr")
    assert rapidocr
    from sfi.extract.evidence import RapidOcrEngine

    pdf = pdfium.PdfDocument(article())
    tokens = ocr_tokens(pdf[0], FIGURE, RapidOcrEngine())
    assert any("42.5" in t.text for t in tokens)
    assert all(t.source.startswith("ocr:rapidocr-") for t in tokens)


def test_ocr_is_kept_over_the_old_text_layer_of_a_scan():
    pdf = pdfium.PdfDocument(article())
    native = pdf_tokens(pdf[0], FIGURE)[1].box  # "42.5"
    over = [
        [native.x0 - FIGURE.x0, native.y0 - FIGURE.y0],
        [native.x1 - FIGURE.x0, native.y0 - FIGURE.y0],
        [native.x1 - FIGURE.x0, native.y1 - FIGURE.y0],
        [native.x0 - FIGURE.x0, native.y1 - FIGURE.y0],
    ]
    engine = FakeOcr([("42.5", over, 0.99)])
    tokens = figure_tokens(pdf[0], FIGURE, engine, dpi=72, scanned=True)
    assert [(t.text, t.source) for t in tokens][-1] == ("42.5", "ocr:fake-1")
    assert [t.source for t in tokens[:-1]] == ["pdf-ocr"] * 3


def test_reading_one_letter_does_not_turn_off_detection_for_later_reads():
    pytest.importorskip("rapidocr")
    import cv2

    from sfi.extract.evidence import RapidOcrEngine

    engine = RapidOcrEngine()
    line = np.full((80, 300, 3), 255, np.uint8)
    cv2.putText(line, "Hello 123", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    letter = np.full((60, 60, 3), 255, np.uint8)
    cv2.putText(letter, "b", (18, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    assert engine.read_line(letter)[0] == "b"
    assert [text for text, _, _ in engine.read(line)] == ["Hello", "123"]
