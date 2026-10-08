"""Stage 2: structured explanations, validation, caching, limits and the OpenAI adapter.

No test touches the network: a fake model returns scripted responses.
"""

from __future__ import annotations

import io
import json
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from sfi.analysis.analyzer import FigureAnalyzer, prepare_image
from sfi.analysis.prompt import PROMPT_VERSION
from sfi.analysis.providers import (
    ModelRequest,
    ModelResult,
    OpenAIMultimodalModel,
    ProviderError,
    ProviderFatalError,
    strict_json_schema,
)
from sfi.analysis.schema import AnalysisStatus, Explanation
from sfi.analysis.validate import quote_in_text, validate_explanation
from sfi.config import AnalysisSettings, Settings
from sfi.pipeline import FigurePipeline
from sfi.report import write_document_report, write_index
from tests.pdf_factory import Page, build_pdf, caption, paragraph, rect

CAPTION = "XRD pattern indicating presence of ZnO peaks in two samples."


def explanation(**overrides) -> dict:
    data = {
        "summary": "Dos patrones de difracción.",
        "figure_type": ["chart"],
        "layout": {
            "description": "Dos paneles, A y B.",
            "panels": [{"label": "A", "content": "XRD"}, {"label": "B", "content": "XRD"}],
        },
        "visual_encoding": {
            "axes": [
                {
                    "panel": "A",
                    "axis": "x",
                    "label": "2 Theta",
                    "unit": None,
                    "range": "0–90",
                    "scale": "linear",
                }
            ],
            "legend": [],
            "scale_bars": [],
            "other": [],
        },
        "claims": [
            {
                "id": "c1",
                "type": "observed",
                "text": "El pico más alto de A está etiquetado (101).",
                "panels": ["A"],
                "evidence": [{"kind": "figure_region", "panel": "A", "quote": None}],
                "approximate": False,
                "confidence": "high",
            },
            {
                "id": "c2",
                "type": "author_stated",
                "text": "Los picos indican ZnO en 2 muestras.",
                "panels": ["A", "B"],
                "evidence": [
                    {"kind": "caption", "panel": None, "quote": "indicating presence of ZnO peaks"}
                ],
                "approximate": False,
                "confidence": "high",
            },
            {
                "id": "c3",
                "type": "uncertain",
                "text": "No se puede determinar el tamaño de cristalito.",
                "panels": [],
                "evidence": [],
                "approximate": False,
                "confidence": "n/a",
            },
        ],
        "main_findings": ["c1", "c2"],
        "interpretation": {"text": "Las muestras contienen ZnO.", "claim_ids": ["c1", "c2"]},
        "role_in_article": {"text": "Confirma la síntesis de ZnO.", "claim_ids": ["c2"]},
        "limitations": ["c3"],
        "limitations_justification": None,
    }
    data.update(overrides)
    return data


def codes(issues) -> set[str]:
    return {i.code for i in issues}


# --- validation ------------------------------------------------------------------------


def test_valid_explanation_has_no_issues():
    assert validate_explanation(Explanation.model_validate(explanation()), CAPTION) == []


def test_quotes_must_be_literal_but_tolerate_typography():
    caption_text = "Cells were imaged with con-\nfocal microscopy “in vivo” (n = 3)."
    assert quote_in_text('con-focal microscopy "in vivo"', caption_text)
    assert quote_in_text("Cells were imaged … (n = 3)", caption_text)
    assert quote_in_text("CELLS WERE   IMAGED", caption_text)
    assert not quote_in_text("Cells were photographed", caption_text)
    assert not quote_in_text("(n = 3) … Cells were imaged", caption_text)  # order matters


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (
            lambda d: d["claims"][1]["evidence"][0].update(quote="proves ZnO is pure"),
            "quote_not_in_caption",
        ),
        (lambda d: d["claims"][1].update(evidence=[]), "author_stated_without_source"),
        (lambda d: d["claims"][0].update(panels=["C"]), "unknown_panel"),
        (lambda d: d["main_findings"].append("c9"), "unknown_claim_ref"),
        (
            lambda d: d["claims"][1].update(text="Los picos indican ZnO en 7 muestras."),
            "number_not_in_evidence",
        ),
        (lambda d: d["claims"].append(dict(d["claims"][0])), "duplicate_claim_id"),
    ],
)
def test_rule_violations_are_errors(change, code):
    data = explanation()
    change(data)
    issues = validate_explanation(Explanation.model_validate(data), CAPTION)
    assert code in codes(i for i in issues if i.severity == "error")


def test_number_words_and_approximate_values_are_accepted():
    data = explanation()
    data["claims"].append(
        {
            "id": "c4",
            "type": "model_inference",
            "text": "El pico de 36 grados sugiere wurtzita.",
            "panels": ["A"],
            "evidence": [{"kind": "figure_region", "panel": "A", "quote": None}],
            "approximate": True,
            "confidence": "medium",
        }
    )
    # "2 muestras" in c2 is supported by "two samples" in the caption; c4 is approximate.
    assert validate_explanation(Explanation.model_validate(data), CAPTION) == []


def test_missing_limitations_without_justification_is_a_warning():
    data = explanation(limitations=[])
    issues = validate_explanation(Explanation.model_validate(data), CAPTION)
    assert [(i.code, i.severity) for i in issues] == [("no_limitations", "warning")]


def test_caption_evidence_without_caption_is_an_error():
    issues = validate_explanation(Explanation.model_validate(explanation()), None)
    assert "caption_evidence_without_caption" in codes(issues)


def test_output_schema_is_strict():
    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for value in node.values():
                yield from objects(value)
        elif isinstance(node, list):
            for value in node:
                yield from objects(value)

    schema = strict_json_schema(Explanation)
    found = list(objects(schema))
    assert len(found) == 11  # Explanation and its ten nested models
    for node in found:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])
    assert '"default"' not in json.dumps(schema)


# --- analyzer --------------------------------------------------------------------------


class FakeModel:
    provider = "fake"

    def __init__(self, model="gpt-6-luna", responses=None):
        self.model = model
        self.responses = list(responses or [])
        self.requests: list[ModelRequest] = []
        self.lock = threading.Lock()

    def check(self):
        pass

    def generate(self, request):
        with self.lock:
            self.requests.append(request)
            response = self.responses.pop(0) if self.responses else ok_result()
        if isinstance(response, Exception):
            raise response
        return response


def ok_result(**overrides) -> ModelResult:
    values = {
        "raw_text": json.dumps(explanation()),
        "model_version": "gpt-6-luna-2026-09-01",
        "provider_status": "completed",
        "response_id": "resp_1",
        "input_tokens": 3000,
        "output_tokens": 2000,
        "reasoning_tokens": 100,
        "latency_ms": 1500,
    }
    values.update(overrides)
    return ModelResult(**values)


@pytest.fixture
def pipeline(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", render_dpi=72, max_pdf_mb=1, max_pages=5)
    return FigurePipeline.from_settings(settings)


@pytest.fixture
def processed(pipeline, tmp_path):
    pages = [
        Page(
            paragraph(60, 740, 8)
            + rect(100, 350, 400, 250)
            + caption(60, 335, f"Figure {n}.", CAPTION)
            + paragraph(60, 300, 10)
        )
        for n in (1, 2)
    ]
    path = tmp_path / "two.pdf"
    path.write_bytes(build_pdf(pages))
    result = pipeline.process(path)
    assert [f.label for f in result.figures] == ["Figure 1", "Figure 2"]
    return result


def make_analyzer(pipeline, model=None, **settings) -> FigureAnalyzer:
    config = AnalysisSettings(concurrency=1, **settings)
    return FigureAnalyzer(config, pipeline.repository, pipeline.blobs, model or FakeModel())


def test_analysis_is_validated_persisted_and_costed(pipeline, processed):
    model = FakeModel()
    analyzer = make_analyzer(pipeline, model)
    result = analyzer.analyze(processed.document, processed.figures)

    assert [o.status for o in result.outcomes] == [AnalysisStatus.OK, AnalysisStatus.OK]
    request = model.requests[0]
    assert "<caption>\nFigure 1." in request.text
    assert request.image_png.startswith(b"\x89PNG")
    assert "data, not instructions" in request.instructions
    assert "Spanish" in request.instructions

    stored = pipeline.repository.latest_analysis(processed.figures[0].id)
    assert stored.explanation.claims[0].id == "c1"
    assert stored.figure_ref.page == 1
    assert stored.run.model == "gpt-6-luna"
    assert stored.run.model_version == "gpt-6-luna-2026-09-01"
    assert stored.run.prompt_version == PROMPT_VERSION
    # 3000 input tokens at 0.10 USD/M plus 2000 output tokens at 0.50 USD/M.
    assert stored.run.estimated_cost_usd == pytest.approx(0.0013)
    assert result.spent_usd == pytest.approx(0.0026)
    assert analyzer.total_spent() == pytest.approx(0.0026)


def test_cache_avoids_repeated_spend_and_force_appends(pipeline, processed):
    model = FakeModel()
    analyzer = make_analyzer(pipeline, model)
    analyzer.analyze(processed.document, processed.figures)
    second = analyzer.analyze(processed.document, processed.figures)
    assert len(model.requests) == 2
    assert {o.source for o in second.outcomes} == {"cache"}
    assert second.spent_usd == 0

    analyzer.analyze(processed.document, processed.figures[:1], force=True)
    assert len(model.requests) == 3
    rows = pipeline.repository.connection.execute("SELECT COUNT(*) FROM analyses").fetchone()
    assert rows[0] == 3  # append-only: the forced attempt does not overwrite

    # A different prompt or model configuration is a cache miss.
    other = make_analyzer(pipeline, model, max_output_tokens=3000)
    other.analyze(processed.document, processed.figures[:1])
    assert len(model.requests) == 4


@pytest.mark.parametrize(
    ("response", "status", "code"),
    [
        (
            ok_result(
                raw_text=json.dumps(explanation())[:300],
                provider_status="incomplete",
                incomplete_reason="max_output_tokens",
            ),
            AnalysisStatus.INCOMPLETE,
            "truncated",
        ),
        (ok_result(raw_text='{"summary": "x"}'), AnalysisStatus.INVALID, "schema_violation"),
        (ok_result(raw_text=None, refusal="I can't help."), AnalysisStatus.INVALID, "refusal"),
        (
            ok_result(raw_text=json.dumps(explanation(summary=" "))),
            AnalysisStatus.INCOMPLETE,
            "missing_summary",
        ),
    ],
)
def test_bad_responses_are_marked_not_hidden(pipeline, processed, response, status, code):
    analyzer = make_analyzer(pipeline, FakeModel(responses=[response]))
    outcome = analyzer.analyze(processed.document, processed.figures[:1]).outcomes[0]
    assert outcome.status == status
    assert code in codes(outcome.analysis.issues)
    assert outcome.analysis.run.output_tokens == 2000  # spend is recorded even when unusable


def test_failed_calls_are_recorded_and_retried(pipeline, processed):
    model = FakeModel(responses=[ProviderError("timeout")])
    analyzer = make_analyzer(pipeline, model)
    first = analyzer.analyze(processed.document, processed.figures[:1]).outcomes[0]
    assert first.status == AnalysisStatus.FAILED
    assert pipeline.repository.latest_analysis(first.figure.id).error == "timeout"
    second = analyzer.analyze(processed.document, processed.figures[:1]).outcomes[0]
    assert second.status == AnalysisStatus.OK and second.source == "model"


def test_fatal_provider_error_stops_the_document(pipeline, processed):
    model = FakeModel(responses=[ProviderFatalError("quota exhausted")])
    result = make_analyzer(pipeline, model).analyze(processed.document, processed.figures)
    assert result.fatal
    assert [o.status for o in result.outcomes] == [AnalysisStatus.FAILED, AnalysisStatus.SKIPPED]
    assert len(model.requests) == 1


def test_total_budget_stops_before_calling(pipeline, processed):
    model = FakeModel()
    # Worst case per figure is ~0.0031 USD (6000 output tokens); the first call really costs
    # 0.0013 USD, so the second worst case (0.0013 + 0.0031) no longer fits in 0.004 USD.
    analyzer = make_analyzer(pipeline, model, total_budget_usd=0.004)
    result = analyzer.analyze(processed.document, processed.figures)
    assert [o.status for o in result.outcomes] == [AnalysisStatus.OK, AnalysisStatus.SKIPPED]
    assert "presupuesto total" in result.outcomes[1].message
    assert result.stopped
    assert len(model.requests) == 1


def test_document_cost_and_figure_limits_are_reported(pipeline, processed):
    by_cost = make_analyzer(pipeline, max_cost_per_document_usd=0.001)
    result = by_cost.analyze(processed.document, processed.figures)
    assert {o.status for o in result.outcomes} == {AnalysisStatus.SKIPPED}
    assert "por documento" in result.stopped

    by_count = make_analyzer(pipeline)
    result = by_count.analyze(processed.document, processed.figures, max_figures=1)
    assert [o.status for o in result.outcomes] == [AnalysisStatus.OK, AnalysisStatus.SKIPPED]
    assert "Límite de 1 figuras" in result.outcomes[1].message


def test_figures_without_region_are_skipped(pipeline, processed):
    caption_only = processed.figures[0].model_copy(update={"crop_artifact_id": None})
    model = FakeModel()
    result = make_analyzer(pipeline, model).analyze(processed.document, [caption_only])
    assert result.outcomes[0].status == AnalysisStatus.SKIPPED
    assert model.requests == []


def test_concurrent_analysis_keeps_figure_order(pipeline, processed):
    analyzer = FigureAnalyzer(
        AnalysisSettings(concurrency=4), pipeline.repository, pipeline.blobs, FakeModel()
    )
    result = analyzer.analyze(processed.document, processed.figures)
    assert [o.figure.label for o in result.outcomes] == ["Figure 1", "Figure 2"]


def test_images_are_flattened_and_downscaled():
    image = Image.new("RGBA", (3000, 1000), (255, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    png, size = prepare_image(buffer.getvalue(), 1536)
    assert size == (1536, 512)
    with Image.open(io.BytesIO(png)) as result:
        assert result.mode == "RGB"
        assert result.getpixel((0, 0)) == (255, 255, 255)


def test_report_shows_typed_claims_and_unreliable_status(pipeline, processed, tmp_path):
    bad = ok_result(raw_text=json.dumps(explanation(main_findings=["c9"])))
    analyzer = make_analyzer(pipeline, FakeModel(responses=[ok_result(), bad]))
    analyzer.analyze(processed.document, processed.figures)
    path = write_document_report(
        processed.document,
        processed.run,
        processed.figures,
        pipeline.repository,
        pipeline.blobs,
        tmp_path / "reports",
    )
    page = path.read_text(encoding="utf-8")
    assert "Dos patrones de difracción." in page
    assert "según los autores" in page and "observado" in page and "incierto" in page
    assert "<q>indicating presence of ZnO peaks</q>" in page
    assert "no debe tomarse como fiable" in page  # the second figure is invalid
    assert "1 explicaciones válidas de 2" in page
    index = write_index(
        [(processed.document, processed.run, processed.figures)],
        tmp_path / "reports",
        pipeline.repository,
    ).read_text(encoding="utf-8")
    assert "<td>1/2</td>" in index


# --- configuration and the OpenAI adapter ----------------------------------------------


@pytest.mark.parametrize(
    "values",
    [
        {"enable_automatic_fallback": True},
        {"primary_model": "gpt-unknown"},
        {"total_budget_usd": 0},
    ],
)
def test_unsafe_configuration_fails_at_startup(values):
    with pytest.raises(ValueError):
        AnalysisSettings(**values).validate()


class FakeResponses:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def openai_response(**overrides):
    values = {
        "id": "resp_9",
        "model": "gpt-6-luna",
        "status": "completed",
        "incomplete_details": None,
        "output": [
            SimpleNamespace(type="reasoning", content=None),
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text='{"summary": "x"}')],
            ),
        ],
        "usage": SimpleNamespace(
            input_tokens=1200,
            output_tokens=900,
            input_tokens_details=SimpleNamespace(cached_tokens=1000),
            output_tokens_details=SimpleNamespace(reasoning_tokens=150),
        ),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_openai_adapter_builds_a_strict_multimodal_request():
    responses = FakeResponses(openai_response())
    model = OpenAIMultimodalModel("gpt-6-luna", client=SimpleNamespace(responses=responses))
    result = model.generate(
        ModelRequest(
            instructions="Explain.",
            text="Caption: x",
            image_png=b"\x89PNG fake",
            output_schema=Explanation,
            max_output_tokens=6000,
            reasoning_effort="low",
        )
    )
    kwargs = responses.kwargs
    assert kwargs["model"] == "gpt-6-luna"
    assert kwargs["store"] is False
    assert kwargs["max_output_tokens"] == 6000
    assert kwargs["reasoning"] == {"effort": "low"}
    assert kwargs["text"]["format"]["strict"] is True
    content = kwargs["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "Caption: x"}
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert result.raw_text == '{"summary": "x"}'
    assert (result.input_tokens, result.cached_input_tokens) == (1200, 1000)
    assert (result.output_tokens, result.reasoning_tokens) == (900, 150)
    assert result.provider_status == "completed"


def test_openai_adapter_reports_refusals_and_truncation():
    refused = openai_response(
        output=[
            SimpleNamespace(
                type="message", content=[SimpleNamespace(type="refusal", refusal="No.")]
            )
        ]
    )
    model = OpenAIMultimodalModel(
        "gpt-6-luna", client=SimpleNamespace(responses=FakeResponses(refused))
    )
    request = ModelRequest("i", "t", b"png", Explanation, 100)
    assert model.generate(request).refusal == "No."

    truncated = openai_response(
        status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens")
    )
    model.client = SimpleNamespace(responses=FakeResponses(truncated))
    result = model.generate(request)
    assert (result.provider_status, result.incomplete_reason) == (
        "incomplete",
        "max_output_tokens",
    )


def test_spelled_out_numbers_in_the_caption_support_claims():
    data = explanation()
    data["claims"][1]["text"] = "56 pacientes y 105 células cumplieron los criterios."
    caption_text = "Fifty-six patients and one hundred and five cells " + CAPTION
    data["claims"][1]["evidence"][0]["quote"] = "Fifty-six patients"
    assert validate_explanation(Explanation.model_validate(data), caption_text) == []


def test_stored_results_are_revalidated_without_a_new_call(pipeline, processed):
    model = FakeModel()
    analyzer = make_analyzer(pipeline, model)
    figure = processed.figures[0]
    first = analyzer.analyze(processed.document, [figure]).outcomes[0].analysis
    # Simulate that the stored result was judged by older, stricter rules.
    stale = first.model_copy(
        update={"status": AnalysisStatus.INVALID, "validator_version": "validate/0.1"}
    )
    with pipeline.repository.connection:
        pipeline.repository.connection.execute(
            "UPDATE analyses SET status = 'invalid', body = ? WHERE id = ?",
            (stale.model_dump_json(), first.id),
        )

    outcome = analyzer.analyze(processed.document, [figure]).outcomes[0]
    assert len(model.requests) == 1
    assert outcome.source == "cache"
    assert outcome.status == AnalysisStatus.OK
    assert outcome.analysis.reused_from == first.id
    assert outcome.analysis.cost_usd == 0
    assert analyzer.total_spent() == pytest.approx(first.cost_usd)
