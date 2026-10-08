"""Stage 5: human review of reference boxes and rubric scores of explanations."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sfi.analysis.analyzer import FigureAnalyzer
from sfi.config import AnalysisSettings, Settings
from sfi.review import ReviewError, apply_box_reviews, check_scores, load_reference
from sfi.web.app import create_app
from tests.test_analysis import FakeModel
from tests.test_context import build_article

JATS = """<article xmlns:xlink="http://www.w3.org/1999/xlink"><body><p>See Fig. 1.</p>
<fig id="F1"><label>Figure 1</label><caption><title>Signal.</title><p>Treated cells.</p></caption>
<graphic xlink:href="img1"/></fig></body></article>"""


def review(figure, decision="box", annotator="ann-1", page=1, bbox=(0.1, 0.1, 0.5, 0.5), **extra):
    return {
        "pmcid": "PMC1",
        "figure": figure,
        "annotator": annotator,
        "decision": decision,
        "page": page if decision == "box" else None,
        "bbox": list(bbox) if decision == "box" else None,
        "reviewed_at": extra.pop("reviewed_at", "2026-10-07T10:00:00+00:00"),
        **extra,
    }


def reference(*figures) -> dict:
    return {
        "version": "reference/test",
        "summary": {"multipanel_from_caption": 0},
        "articles": [
            {"pmcid": "PMC1", "split": "validation", "pages": 2, "figures": list(figures)}
        ],
    }


def ref_figure(jats_id, label, status="needs_manual", page=1, bbox=(0.1, 0.1, 0.6, 0.6)):
    return {
        "jats_id": jats_id,
        "label": label,
        "page": page,
        "bbox": list(bbox),
        "match_score": 0.5,
        "review_status": status,
    }


def test_box_reviews_update_the_reference_without_editing_it():
    original = reference(
        ref_figure("F1", "Figure 1"),
        ref_figure("F2", "Figure 2"),
        ref_figure("F3", "Figure 3"),
        ref_figure("F4", "Figure 4"),
        ref_figure("F5", "Figure 5", status="auto"),
    )
    reviews = [
        review("F1", page=2, bbox=(0.2, 0.2, 0.8, 0.7)),
        review("F2", decision="absent"),
        review("F3", decision="unclear", note="split over two pages"),
        review("F4", bbox=(0.1, 0.1, 0.5, 0.5)),
        review("F4", annotator="ann-2", bbox=(0.5, 0.5, 0.9, 0.9)),  # disagrees
        review("label:Figure 6", label="Figure 6", bbox=(0.1, 0.5, 0.9, 0.9)),
    ]
    updated = apply_box_reviews(original, reviews)
    figures = {f["label"]: f for f in updated["articles"][0]["figures"]}
    assert figures["Figure 1"]["review_status"] == "reviewed"
    assert (figures["Figure 1"]["page"], figures["Figure 1"]["bbox"]) == (2, [0.2, 0.2, 0.8, 0.7])
    assert "Figure 2" not in figures
    assert updated["articles"][0]["removed_by_review"] == ["Figure 2"]
    assert figures["Figure 3"]["review_status"] == "unclear"
    assert figures["Figure 4"]["review_status"] == "disputed"
    assert figures["Figure 4"]["reviewed_by"] == ["ann-1", "ann-2"]
    assert figures["Figure 5"]["review_status"] == "auto"
    assert figures["Figure 6"]["source"] == "review" and figures["Figure 6"]["page"] == 1
    assert updated["summary"]["reviewed"] == 2 and updated["summary"]["disputed"] == 1
    assert original["articles"][0]["figures"][0]["review_status"] == "needs_manual"


def test_agreeing_reviews_are_applied():
    reviews = [
        review("F1", bbox=(0.1, 0.1, 0.5, 0.5)),
        review("F1", annotator="ann-2", bbox=(0.11, 0.1, 0.5, 0.51)),
    ]
    [figure] = apply_box_reviews(reference(ref_figure("F1", "Figure 1")), reviews)["articles"][0][
        "figures"
    ]
    assert figure["review_status"] == "reviewed" and figure["bbox"] == [0.1, 0.1, 0.5, 0.5]


def test_rubric_scores_are_validated():
    assert check_scores({"correctness": 2, "citation": "na"}) == {
        "correctness": 2,
        "citation": "na",
    }
    for bad in ({"correctness": 3}, {"support": "na"}, {"correctness": True}, {"style": 1}):
        with pytest.raises(ReviewError):
            check_scores(bad)


# --- web ---------------------------------------------------------------------------------


@pytest.fixture
def corpus(tmp_path):
    raw = tmp_path / "raw"
    (raw / "figures" / "PMC1").mkdir(parents=True)
    (raw / "PMC1.pdf").write_bytes(build_article())
    (raw / "PMC1.xml").write_text(JATS, encoding="utf-8")
    (raw / "figures" / "PMC1" / "img1.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")
    corpus_dir = tmp_path / "sfi48"
    corpus_dir.mkdir()
    figure = ref_figure("F1", "Figure 1", page=2) | {"match_score": 0.41}
    (corpus_dir / "expected_figures.json").write_text(
        json.dumps(reference(figure)), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def client(corpus):
    settings = Settings(
        data_dir=corpus / "data",
        render_dpi=72,
        max_pdf_mb=1,
        max_pages=5,
        corpus_dir=corpus / "sfi48",
        corpus_raw_dir=corpus / "raw",
    )

    def factory(settings, repository, blobs):
        return FigureAnalyzer(AnalysisSettings(concurrency=1), repository, blobs, FakeModel())

    app = create_app(settings, analyzer_factory=factory, start_worker=False)
    with TestClient(app) as client:
        client.app_state = app.state
        yield client


def test_box_review_round_trip(client, corpus):
    listing = client.get("/api/review/boxes", params={"annotator": "ann-1"}).json()
    assert listing["available"]
    [item] = listing["items"]
    assert (item["key"], item["reason"], item["needs_review"], item["mine"]) == (
        "F1",
        "low_score",
        True,
        None,
    )

    detail = client.get("/api/review/box", params={"pmcid": "PMC1", "figure": "F1"}).json()
    assert detail["caption"].startswith("Signal.") and detail["has_image"]
    assert detail["proposal"] == {"page": 2, "bbox": [0.1, 0.1, 0.6, 0.6], "score": 0.41}
    assert any(p["page"] == 1 and p["caption_like"] for p in detail["label_pages"])
    page = client.get("/api/review/articles/PMC1/pages/1")
    assert page.content[:4] == b"\x89PNG"
    image = client.get("/api/review/articles/PMC1/figure-image", params={"figure": "F1"})
    assert image.headers["content-type"] == "image/jpeg"

    body = {"pmcid": "PMC1", "figure": "F1", "annotator": "ann-1", "decision": "box", "page": 1}
    assert (
        client.put("/api/review/box", json=body | {"bbox": [0.5, 0.1, 0.2, 0.4]}).status_code == 400
    )
    assert (
        client.put(
            "/api/review/box", json=body | {"page": 9, "bbox": [0.1, 0.1, 0.5, 0.5]}
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/review/box", json=body | {"annotator": "", "bbox": [0.1, 0.1, 0.5, 0.5]}
        ).status_code
        == 400
    )
    saved = client.put("/api/review/box", json=body | {"bbox": [0.12, 0.3, 0.88, 0.62]})
    assert saved.status_code == 200 and saved.json()["reference_version"] == "reference/test"

    listing = client.get("/api/review/boxes", params={"annotator": "ann-1"}).json()
    assert listing["items"][0]["mine"] == "box"
    [figure] = load_reference(corpus / "sfi48")["articles"][0]["figures"]
    assert (figure["review_status"], figure["page"], figure["bbox"]) == (
        "reviewed",
        1,
        [0.12, 0.3, 0.88, 0.62],
    )
    params = {"pmcid": "PMC1", "figure": "F1", "annotator": "ann-1"}
    assert client.delete("/api/review/box", params=params).status_code == 200
    assert client.delete("/api/review/box", params=params).status_code == 404


def test_box_review_rejects_unknown_figures_and_accepts_added_ones(client, corpus):
    body = {"pmcid": "PMC1", "annotator": "ann-1", "decision": "unclear", "note": "faint"}
    assert client.put("/api/review/box", json=body | {"figure": "F9"}).status_code == 400
    assert (
        client.put("/api/review/box", json=body | {"pmcid": "PMC9", "figure": "F1"}).status_code
        == 404
    )
    unclear = body | {"figure": "F1", "note": ""}
    assert client.put("/api/review/box", json=unclear).status_code == 400  # needs a note
    added = {
        "pmcid": "PMC1",
        "figure": "label:Figure 2",
        "label": "Figure 2",
        "annotator": "ann-1",
        "decision": "box",
        "page": 2,
        "bbox": [0.1, 0.1, 0.9, 0.5],
    }
    assert client.put("/api/review/box", json=added).status_code == 200
    detail = client.get(
        "/api/review/box",
        params={"pmcid": "PMC1", "figure": "label:Figure 2", "annotator": "ann-1"},
    ).json()
    assert detail["reason"] == "added" and detail["review"]["page"] == 2
    labels = [f["label"] for f in load_reference(corpus / "sfi48")["articles"][0]["figures"]]
    assert labels == ["Figure 1", "Figure 2"]


def test_explanations_are_scored_with_the_rubric(client, corpus):
    pdf = (corpus / "raw" / "PMC1.pdf").read_bytes()
    client.post("/api/documents", files={"file": ("article.pdf", pdf, "application/pdf")})
    client.app_state.runner.run_pending()

    [item] = client.get("/api/review/explanations", params={"annotator": "ann-1"}).json()["items"]
    assert (item["pmcid"], item["split"], item["claims"], item["scored"]) == (
        "PMC1",
        "validation",
        3,
        0,
    )
    path = f"/api/review/explanations/{item['document_id']}/{item['figure_id']}"
    current = client.get(path, params={"annotator": "ann-1"}).json()
    assert current["review"] is None
    assert [c["id"] for c in current["rubric"]["criteria"]][:2] == ["correctness", "support"]

    good = {k: 2 for k in ("correctness", "support", "claim_type", "calibration", "usefulness")}
    body = {
        "annotator": "ann-1",
        "analysis": current["analysis"],
        "claims": {
            "c1": {"scores": good | {"citation": "na"}},
            "c2": {"scores": good | {"citation": 1}, "critical": "fabricated_value", "note": "x"},
        },
    }
    assert client.put(path, json=body | {"analysis": "an_stale"}).status_code == 409
    bad = body | {"claims": {"c1": {"scores": {"correctness": 5}}}}
    assert client.put(path, json=bad).status_code == 400
    assert client.put(path, json=body | {"claims": {"c9": {}}}).status_code == 400
    saved = client.put(path, json=body).json()
    assert saved["pmcid"] == "PMC1" and saved["figure_label"] == "Figure 1"
    assert [c["id"] for c in saved["claims"]] == ["c1", "c2", "c3"]
    assert saved["claims"][1]["critical"] == "fabricated_value"
    assert saved["claims"][2]["scores"] == {}

    [item] = client.get("/api/review/explanations", params={"annotator": "ann-1"}).json()["items"]
    assert (item["scored"], item["critical"]) == (2, 1)
    stored = json.loads((corpus / "sfi48" / "reviews" / "claims.json").read_text("utf-8"))
    assert stored["rubric"]["version"] == "rubric/1" and len(stored["reviews"]) == 1


def test_review_reports_a_missing_corpus(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        render_dpi=72,
        max_pdf_mb=1,
        max_pages=5,
        corpus_dir=tmp_path / "missing",
        corpus_raw_dir=tmp_path / "missing-raw",
    )
    with TestClient(create_app(settings, start_worker=False)) as client:
        listing = client.get("/api/review/boxes").json()
        assert listing["available"] is False
        assert (
            client.get("/api/review/box", params={"pmcid": "PMC1", "figure": "F1"}).status_code
            == 404
        )
        assert client.get("/api/review/explanations").json()["items"] == []


def test_review_summary_computes_the_rubric_metrics():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[1] / "scripts" / "eval" / "review_summary.py"
    spec = importlib.util.spec_from_file_location("review_summary", path)
    summary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(summary)

    good = {"correctness": 2, "support": 2, "citation": 2, "claim_type": 2}
    good |= {"calibration": 2, "usefulness": 2}
    claims = [
        {"id": "c1", "confidence": "high", "scores": good, "critical": None},
        {"id": "c2", "confidence": "high", "scores": good | {"support": 0, "citation": 1}},
        {
            "id": "c3",
            "confidence": "low",
            "scores": good | {"citation": "na"},
            "critical": "contradiction",
        },
        {"id": "c4", "confidence": "high", "scores": {"correctness": 2}},  # not fully scored
    ]
    result = summary.claim_summary([{"annotator": "a", "claims": claims}])
    assert result["claims_scored"] == 3 and result["explanations_complete"] == 0
    assert result["unsupported_rate"] == {"value": 0.333, "n": 3}
    assert result["unsupported_rate_high_confidence"] == {"value": 0.5, "n": 2}
    assert result["citation_precision"] == {"value": 0.5, "n": 2}
    assert result["critical_errors"] == {"contradiction": 1}
    assert result["explanations_with_critical_error"] == 1

    scanned = ref_figure(None, "Figure 3")  # keyed by label, like figures of scanned articles
    ref = reference(ref_figure("F1", "Figure 1"), ref_figure("F2", "Figure 2"), scanned)
    reviews = [review("F1"), review("F1", annotator="ann-2", bbox=(0.1, 0.1, 0.5, 0.45))]
    reviews += [review("label:Figure 3"), review("label:Figure 9")]
    boxes = summary.box_summary(ref, reviews)
    assert boxes["needs_manual_reviewed"] == {"validation": "2/3"}
    assert boxes["added_figures"] == 1
    assert boxes["double_annotated"] == 1 and boxes["median_iou"] == 0.875


def test_panel_boxes_are_reviewed_per_letter(client, corpus):
    jats = JATS.replace(
        "<caption><title>Signal.</title><p>Treated cells.</p></caption>",
        "<caption><p>Growth. (a) Control cells. (b) Treated cells.</p></caption>",
    )
    (corpus / "raw" / "PMC1.xml").write_text(jats, encoding="utf-8")
    review_box = {"pmcid": "PMC1", "figure": "F1", "annotator": "ann-1", "decision": "box"}
    client.put("/api/review/box", json=review_box | {"page": 1, "bbox": [0.1, 0.1, 0.9, 0.5]})

    [item] = client.get("/api/review/panels", params={"annotator": "ann-1"}).json()["items"]
    assert (item["key"], item["letters"], item["mine"]) == ("F1", "ab", None)
    detail = client.get("/api/review/panel", params={"pmcid": "PMC1", "figure": "F1"}).json()
    assert (detail["page"], detail["figure_box"]) == (1, [0.1, 0.1, 0.9, 0.5])
    assert detail["panels"] == [
        {"label": "a", "subcaption": "Control cells.", "added": False},
        {"label": "b", "subcaption": "Treated cells.", "added": False},
    ]

    body = {"pmcid": "PMC1", "figure": "F1", "annotator": "ann-1", "decision": "done"}
    a = {"label": "a", "bbox": [0.1, 0.1, 0.5, 0.5]}
    assert client.put("/api/review/panel", json=body | {"panels": []}).status_code == 400
    assert client.put("/api/review/panel", json=body | {"panels": [a, a]}).status_code == 400
    outside = {"label": "b", "bbox": [0.1, 0.7, 0.5, 0.9]}
    assert client.put("/api/review/panel", json=body | {"panels": [a, outside]}).status_code == 400
    assert (
        client.put("/api/review/panel", json=body | {"panels": [{"label": "z"}]}).status_code == 400
    )
    saved = client.put("/api/review/panel", json=body | {"panels": [a]}).json()
    assert saved["panels"] == [a | {"absent": False}, {"label": "b", "bbox": None, "absent": False}]
    stored = json.loads((corpus / "sfi48" / "reviews" / "panels.json").read_text("utf-8"))
    assert stored["schema"] == "sfi48-panel-reviews/1" and len(stored["reviews"]) == 1
    [item] = client.get("/api/review/panels", params={"annotator": "ann-1"}).json()["items"]
    assert item["mine"] == "done"


def test_judge_answers_are_checked_before_import(tmp_path):
    import importlib.util
    import sys
    from pathlib import Path

    scripts = Path(__file__).parents[1] / "scripts" / "eval"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "import_judge", scripts / "import_judge_scores.py"
    )
    judge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(judge)

    claims = [
        {"id": "c1", "type": "observed", "confidence": "high", "text": "A peak at 68 nm."},
        {"id": "c2", "type": "author_stated", "confidence": "high", "text": "Smaller with M."},
    ]
    keys = {
        "E01": {
            "lote": 1,
            "analysis": "an_1",
            "document_sha256": "abc",
            "filename": "PMC1.pdf",
            "pmcid": "PMC1",
            "split": "dev",
            "figure_label": "Figure 3",
            "page": 4,
            "explanation_status": "ok",
            "model": "m",
            "prompt_version": "p",
            "schema_version": "s",
            "claims": claims,
        }
    }
    good = {
        "correccion": 2,
        "respaldo": 2,
        "cita": "NA",
        "tipo": 2,
        "calibracion": 2,
        "utilidad": 2,
    }
    answer = {
        "revisor": "modelo-x",
        "lote": 1,
        "explicaciones": [
            {
                "id": "E01",
                "afirmaciones": [
                    {"id": "c1", **good, "error_critico": None, "nota": None},
                    {
                        "id": "c2",
                        **good,
                        "cita": 1,
                        "error_critico": "valor_inventado",
                        "nota": "No.",
                    },
                ],
            }
        ],
    }
    text = "Aquí está:\n```json\n" + json.dumps(answer) + "\n```"
    [record] = judge.convert(judge.parse_answer(text), keys, "ia-modelo-x")
    assert record["annotator_kind"] == "llm" and record["judge"] == "modelo-x"
    assert record["claims"][0]["scores"]["citation"] == "na"
    assert record["claims"][1]["critical"] == "fabricated_value"

    answer["explicaciones"][0]["afirmaciones"][1]["nota"] = None  # low score without a note
    del answer["explicaciones"][0]["afirmaciones"][0]  # and a claim left out
    with pytest.raises(ReviewError) as problems:
        judge.convert(answer, keys, "ia-modelo-x")
    assert "faltan afirmaciones c1" in str(problems.value) and "nota" in str(problems.value)


def test_panel_review_is_not_limited_to_the_caption_letters(client, corpus):
    jats = JATS.replace(
        "<caption><title>Signal.</title><p>Treated cells.</p></caption>",
        "<caption><p>Growth. (a) Control cells. (b) Treated cells.</p></caption>",
    )
    (corpus / "raw" / "PMC1.xml").write_text(jats, encoding="utf-8")
    review_box = {"pmcid": "PMC1", "figure": "F1", "annotator": "ann-1", "decision": "box"}
    client.put("/api/review/box", json=review_box | {"page": 1, "bbox": [0.1, 0.1, 0.9, 0.5]})

    body = {"pmcid": "PMC1", "figure": "F1", "annotator": "ann-1", "decision": "done"}
    a = {"label": "a", "bbox": [0.1, 0.1, 0.5, 0.5]}
    c = {"label": "c", "bbox": [0.5, 0.1, 0.9, 0.5]}  # printed in the figure, not in the caption
    gone = {"label": "b", "absent": True}  # named by the caption, not printed
    for bad in (
        [a, {"label": "b", "absent": True, "bbox": [0.5, 0.1, 0.9, 0.5]}],  # absent with a box
        [a, {"label": "c", "absent": True}],  # only caption letters can be absent
        [a, {"label": "c?", "bbox": [0.5, 0.1, 0.9, 0.5]}],  # not a panel letter
    ):
        assert client.put("/api/review/panel", json=body | {"panels": bad}).status_code == 400
    saved = client.put("/api/review/panel", json=body | {"panels": [a, gone, c]}).json()
    assert saved["letters_added"] == ["c"] and saved["letters_absent"] == ["b"]
    assert [(p["label"], p["bbox"] is not None) for p in saved["panels"]] == [
        ("a", True),
        ("b", False),
        ("c", True),
    ]
    detail = client.get(
        "/api/review/panel", params={"pmcid": "PMC1", "figure": "F1", "annotator": "ann-1"}
    ).json()
    assert [(p["label"], p["added"]) for p in detail["panels"]] == [
        ("a", False),
        ("b", False),
        ("c", True),
    ]
