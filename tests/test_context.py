"""Stage 3: article text, figure mentions, context selection and traceable quotes.

No test touches the network: the model is the scripted fake from test_analysis.
"""

from __future__ import annotations

import json

import pytest

from sfi.analysis.schema import AnalysisStatus, ContextPassage, Explanation
from sfi.analysis.validate import locate_quote, validate_explanation
from sfi.config import Settings
from sfi.context.mentions import find_mentions
from sfi.context.select import ContextConfig, select_context
from sfi.domain.models import BBox, FigureMention, Passage, PassageSegment
from sfi.pipeline import FigurePipeline
from sfi.report import write_document_report
from tests.pdf_factory import Page, build_pdf, caption, paragraph, rect, text
from tests.test_analysis import CAPTION, FakeModel, explanation, make_analyzer, ok_result

MENTION_LINE = "here, and the effect was largest in the second group of animals measured (Fig. 1b)."

# --- mentions --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("respectively (Fig. 2C,D). Absence", [("Figure 2", ["C", "D"])]),
        ("(Figs. 2–4)", [("Figure 2", []), ("Figure 3", []), ("Figure 4", [])]),
        (
            "(Extended Data Figs. 1 and 2)",
            [("Extended Data Figure 1", []), ("Extended Data Figure 2", [])],
        ),
        ("see Fig. 2a–c and Fig. 3(b)", [("Figure 2", ["a", "b", "c"]), ("Figure 3", ["b"])]),
        ("Figs 2, 3 and 5", [("Figure 2", []), ("Figure 3", []), ("Figure 5", [])]),
        ("Fig. 2a, b, d", [("Figure 2", ["a", "b", "d"])]),
        ("(Fig. 2 and a decrease)", [("Figure 2", [])]),
        ("Figure I shows the rates", [("Figure 1", [])]),
        ("Supplementary Fig. 4", [("Supplementary Figure 4", [])]),
        ("Scheme 1 and Table 2", [("Scheme 1", [])]),
        ("Figure 10.5 mm", []),
        ("the figures and Table 1", []),
    ],
)
def test_mentions(source, expected):
    assert [(m.label, m.panels) for m in find_mentions(source)] == expected


def test_mention_offsets_point_at_the_reference():
    source = "Signal rose (Fig. 2C,D). Then"
    [mention] = find_mentions(source)
    assert source[mention.start : mention.end] == mention.text == "Fig. 2C,D"


# --- passages from a PDF ---------------------------------------------------------------


@pytest.fixture
def pipeline(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", render_dpi=72, max_pdf_mb=1, max_pages=5)
    return FigurePipeline.from_settings(settings)


def build_article() -> bytes:
    """A two-page article: Results heading, paragraphs that mention Figure 1, references."""

    page1 = Page(
        text(60, 720, "Results", size=12, bold=True)
        + text(
            60,
            700,
            "Treated cells showed a strong increase of the fluorescent signal in every replicate",
        )
        + text(60, 688, MENTION_LINE)
        + text(
            72,
            676,
            "A second paragraph discusses unrelated controls that were measured in the same",
        )
        + text(
            60,
            664,
            "conditions as before, and it ends here without mentioning any figure of the paper.",
        )
        + rect(100, 350, 400, 250)
        + caption(60, 335, "Figure 1.", CAPTION)
        + paragraph(60, 300, 10)
    )
    page2 = Page(
        text(
            72,
            720,
            "The effect described in Fig. 1a persisted after correction for multiple comparisons.",
        )
        + paragraph(60, 706, 6)
        + text(60, 600, "References", size=12, bold=True)
        + text(
            60,
            580,
            "1. Smith, J. A study of Fig. 1 in mice and the effects of light exposure. J. Biol. 12, 3.",
        )
        + paragraph(60, 560, 4)
    )
    return build_pdf([page1, page2])


@pytest.fixture
def article(tmp_path):
    path = tmp_path / "article.pdf"
    path.write_bytes(build_article())
    return path


def passage_with(passages: list[Passage], fragment: str) -> Passage:
    return next(p for p in passages if fragment in p.text)


def test_body_text_is_stored_as_passages_with_sections_and_mentions(pipeline, article):
    result = pipeline.process(article)
    passages = result.passages
    assert passages == pipeline.repository.list_passages(result.run.id)

    first = passage_with(passages, "(Fig. 1b)")
    assert first.section == "Results"
    assert first.page_index == 0 and not first.back_matter
    assert first.text.startswith("Treated cells showed")  # two lines joined in one paragraph
    assert [(m.label, m.panels) for m in first.mentions] == [("Figure 1", ["b"])]
    mention = first.mentions[0]
    assert first.text[mention.start : mention.end] == "Fig. 1b"

    # A first-line indent after a finished sentence starts a new paragraph.
    second = passage_with(passages, "A second paragraph")
    assert second.ordinal == first.ordinal + 1 and not second.mentions

    later = passage_with(passages, "Fig. 1a persisted")
    assert later.page_at(later.text.index("Fig. 1a")) == 1
    assert [m.panels for m in later.mentions] == [["a"]]

    reference = passage_with(passages, "Smith, J.")
    assert reference.back_matter and reference.section == "References"

    # Neither the caption nor the heading are body text.
    assert not any("XRD pattern" in p.text for p in passages)
    assert not any(p.text.strip() == "Results" for p in passages)
    for passage in passages:
        for segment in passage.segments:
            x0, y0, x1, y1 = segment.bbox_normalized
            assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


# --- context selection -----------------------------------------------------------------


def make_passage(ordinal: int, text_: str, section: str | None = "Results", **values) -> Passage:
    mentions = [
        FigureMention(label=m.label, panels=m.panels, start=m.start, end=m.end, text=m.text)
        for m in find_mentions(text_)
    ]
    box = BBox(left=0, bottom=0, right=10, top=10)
    return Passage(
        id=f"psg_{ordinal}",
        document_id="sha256:x",
        run_id="run",
        ordinal=ordinal,
        page_index=values.get("page_index", 0),
        section=section,
        back_matter=values.get("back_matter", False),
        text=text_,
        segments=values.get(
            "segments",
            [
                PassageSegment(
                    page_index=0, char_start=0, bbox=box, bbox_normalized=(0, 0, 0.1, 0.1)
                )
            ],
        ),
        mentions=mentions,
        producer="test",
        producer_version="0",
    )


def figure_1(pipeline_figure=None):
    from sfi.domain.models import Figure

    return Figure(
        id="fig",
        document_id="sha256:x",
        run_id="run",
        label="Figure 1",
        page_index=0,
        bbox=None,
        status="ok",
        confidence=1.0,
        producer="test",
        producer_version="0",
    )


def test_context_uses_mentioning_passages_and_skips_back_matter():
    passages = [
        make_passage(0, "Unrelated introduction text."),
        make_passage(1, "Cells grew faster (Fig. 1a)."),
        make_passage(2, "Figure 2 shows something else."),
        make_passage(3, "Smith. Fig. 1 in mice.", section="References", back_matter=True),
    ]
    context = select_context(figure_1(), passages)
    assert [p.ref for p in context.passages] == ["p1"]
    assert context.passages[0].mentions == ["Fig. 1a"]
    assert context.note is None

    none = select_context(figure_1(), passages[:1])
    assert none.passages == [] and "no menciona" in none.note


def test_long_passages_are_cut_around_the_mention_and_budget_is_reported():
    filler = " ".join(f"Sentence number {i} adds background." for i in range(80))
    long_text = filler + " The key result is shown in Fig. 1c. " + filler
    passages = [
        make_passage(1, long_text),
        make_passage(2, "Methods for Fig. 1. " + "Details. " * 40, section="Methods"),
    ]
    config = ContextConfig(max_chars=300, max_passage_chars=400, window_sentences=1)
    context = select_context(figure_1(), passages, config)
    [sent] = context.passages
    assert sent.truncated and "Fig. 1c" in sent.text and len(sent.text) < 400
    assert long_text[sent.offset : sent.offset + len(sent.text)] == sent.text
    assert "1 de 2" in context.note  # the Methods passage did not fit


# --- validation of text quotes ---------------------------------------------------------


CONTEXT = [
    ContextPassage(
        ref="p4",
        passage_id="psg_4",
        page=3,
        section="Results",
        text="Dice coefficients were 0.92 for TTV and 0.95 for T1CE TV (Fig. 1).",
        offset=10,
        mentions=["Fig. 1"],
        segments=[(3, 0), (4, 40)],
    ),
    ContextPassage(
        ref="p7",
        passage_id="psg_7",
        page=5,
        section="Discussion",
        text="Segmentation was robust.",
        offset=0,
        mentions=["Fig. 1"],
    ),
]


def with_text_claim(
    quote: str, passage_id: str = "p4", claim_text: str | None = None
) -> Explanation:
    data = explanation()
    data["claims"].append(
        {
            "id": "c4",
            "type": "author_stated",
            "text": claim_text or "Los coeficientes Dice fueron 0.92 y 0.95.",
            "panels": [],
            "evidence": [
                {"kind": "text_span", "panel": None, "quote": quote, "passage_id": passage_id}
            ],
            "approximate": False,
            "confidence": "high",
        }
    )
    data["main_findings"].append("c4")
    return Explanation.model_validate(data)


def errors(issues):
    return {i.code for i in issues if i.severity == "error"}


def test_text_quotes_must_be_literal_in_the_cited_passage():
    caption_text = "XRD pattern indicating presence of ZnO peaks in two samples."
    ok = with_text_claim("0.92 for TTV and 0.95 for T1CE TV")
    assert validate_explanation(ok, caption_text, CONTEXT) == []

    invented = with_text_claim("Dice coefficients exceeded 0.9 in every case")
    assert "quote_not_in_text" in errors(validate_explanation(invented, caption_text, CONTEXT))

    unknown = with_text_claim("was robustly measured", passage_id="p99")
    assert "unknown_passage" in errors(validate_explanation(unknown, caption_text, CONTEXT))

    misattributed = with_text_claim("Segmentation was robust", claim_text="Fue robusta.")
    issues = validate_explanation(misattributed, caption_text, CONTEXT)
    assert [(i.code, i.severity) for i in issues] == [("wrong_passage", "warning")]

    no_context = validate_explanation(ok, caption_text, [])
    assert "text_evidence_without_passages" in errors(no_context)


def test_numbers_must_come_from_the_cited_passage():
    caption_text = "XRD pattern indicating presence of ZnO peaks in two samples."
    wrong = with_text_claim("0.92 for TTV", claim_text="El Dice fue 0.97 para TTV.")
    assert "number_not_in_evidence" in errors(validate_explanation(wrong, caption_text, CONTEXT))


def test_main_findings_must_be_traceable():
    data = explanation()
    data["claims"][0]["evidence"] = []
    issues = validate_explanation(
        Explanation.model_validate(data), "x indicating presence of ZnO peaks"
    )
    assert "untraceable_finding" in errors(issues)


def test_quotes_are_located_in_the_original_text():
    source = "Cells were imaged with con-\nfocal microscopy “in vivo” (n = 3)."
    start, end = locate_quote('confocal microscopy "in vivo"', source)
    assert (
        source[start:end] == "con-\nfocal microscopy “in vivo"
    )  # punctuation-insensitive match ends at the last letter
    start, end = locate_quote("Cells were imaged … (n = 3)", source)
    assert source[start:end] == source[:-1]


# --- analysis with context, end to end -------------------------------------------------


def test_analysis_sends_context_and_traces_quotes_to_pages(pipeline, article, tmp_path):
    result = pipeline.process(article)
    [figure] = [f for f in result.figures if f.label == "Figure 1"]
    probe = make_analyzer(pipeline)
    context = probe.context_for(figure, result.passages)
    refs = [p.ref for p in context.passages]
    assert len(refs) == 2  # the paragraph on page 1 and the one on page 2; not the reference

    later = context.passages[1]
    data = explanation()
    data["claims"].append(
        {
            "id": "c4",
            "type": "author_stated",
            "text": "El efecto persistió tras la corrección.",
            "panels": [],
            "evidence": [
                {
                    "kind": "text_span",
                    "panel": None,
                    "quote": "persisted after correction for multiple comparisons",
                    "passage_id": later.ref,
                }
            ],
            "approximate": False,
            "confidence": "high",
        }
    )
    data["role_in_article"] = {"text": "Muestra el efecto principal.", "claim_ids": ["c4"]}
    model = FakeModel(responses=[ok_result(raw_text=json.dumps(data))])
    analyzer = make_analyzer(pipeline, model)
    outcome = analyzer.analyze(result.document, [figure]).outcomes[0]

    assert outcome.status == AnalysisStatus.OK, outcome.analysis.issues
    request = model.requests[0].text
    assert f'<passage id="{refs[0]}" page="1" section="Results">' in request
    assert "(Fig. 1b)" in request and "Smith" not in request
    [span] = outcome.analysis.spans
    assert (span.claim_id, span.ref, span.page) == ("c4", later.ref, 2)
    passage = next(p for p in result.passages if p.id == span.passage_id)
    assert (
        passage.text[span.start : span.end] == "persisted after correction for multiple comparisons"
    )

    # The gallery links the quote to the passage, highlighted on page 2.
    report = write_document_report(
        result.document,
        result.run,
        result.figures,
        pipeline.repository,
        pipeline.blobs,
        tmp_path / "reports",
    ).read_text(encoding="utf-8")
    assert f"href='#psg-{span.passage_id}'" in report
    assert f'id="psg-{span.passage_id}"' in report
    assert 'id="page-2"' in report
    assert "Papel en el artículo" in report and "Fragmentos del artículo enviados (2)" in report


def test_context_is_part_of_the_cache_key(pipeline, article):
    result = pipeline.process(article)
    [figure] = [f for f in result.figures if f.label == "Figure 1"]
    model = FakeModel()
    analyzer = make_analyzer(pipeline, model)
    analyzer.analyze(result.document, [figure])
    analyzer.analyze(result.document, [figure])
    assert len(model.requests) == 1
    analyzer.analyze(result.document, [figure], passages=result.passages[:1])
    assert len(model.requests) == 2  # different text sent: a new analysis


def test_literal_sentences_with_gaps_are_accepted_with_a_warning():
    caption_text = "(A,B) XRD pattern of ZnO. (A) Cassia NPs. (B) Melia NPs. (C,D) FTIR pattern."
    data = explanation()
    data["claims"][1]["evidence"][0]["quote"] = "(A,B) XRD pattern of ZnO. (C,D) FTIR pattern."
    data["claims"][1]["text"] = "Los paneles muestran XRD y FTIR."
    issues = validate_explanation(Explanation.model_validate(data), caption_text)
    assert [(i.code, i.severity) for i in issues] == [("quote_with_gaps", "warning")]
    # Changing a word is still an error, gaps or not.
    data["claims"][1]["evidence"][0]["quote"] = "(A,B) XRD pattern of ZnO. (C,D) Raman pattern."
    issues = validate_explanation(Explanation.model_validate(data), caption_text)
    assert "quote_not_in_caption" in errors(issues)


def test_quotes_stay_linked_when_an_explanation_is_reused_in_a_new_run(pipeline, article):
    from sfi.pipeline import FigurePipeline
    from tests.test_evidence import FakeOcr

    result = pipeline.process(article)
    [figure] = [f for f in result.figures if f.label == "Figure 1"]
    later = make_analyzer(pipeline).context_for(figure, result.passages).passages[1]
    data = explanation()
    data["claims"].append(
        {
            "id": "c4",
            "type": "author_stated",
            "text": "El efecto persistió tras la corrección.",
            "panels": [],
            "evidence": [
                {
                    "kind": "text_span",
                    "panel": None,
                    "quote": "persisted after correction for multiple comparisons",
                    "passage_id": later.ref,
                }
            ],
            "approximate": False,
            "confidence": "high",
        }
    )
    model = FakeModel(responses=[ok_result(raw_text=json.dumps(data))])
    make_analyzer(pipeline, model).analyze(result.document, [figure])

    # Another configuration (here, OCR) gives a new run: new figure and passage ids.
    rerun = FigurePipeline(
        pipeline.settings, pipeline.repository, pipeline.blobs, ocr_engine=FakeOcr([])
    ).process(article)
    assert rerun.run.id != result.run.id
    [new_figure] = [f for f in rerun.figures if f.label == "Figure 1"]
    reused = make_analyzer(pipeline, model).analyze(rerun.document, [new_figure]).outcomes[0]
    assert len(model.requests) == 1 and reused.analysis.reused_from
    new_ids = {p.id for p in rerun.passages}
    [span] = reused.analysis.spans
    assert span.passage_id in new_ids
    assert all(c.passage_id in new_ids for c in reused.analysis.context)
