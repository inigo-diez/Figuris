"""Stage 5: multipanel figures split into panels and linked to sub-captions."""

from __future__ import annotations

import numpy as np
import pypdfium2 as pdfium
import pytest

from sfi.extract.extractor import PdfiumFigureExtractor
from sfi.extract.panels import (
    CONFIDENCE_EXACT,
    CONFIDENCE_MERGED,
    caption_letters,
    detect_panels,
    parse_subcaptions,
    reading_order,
    split_figure,
)
from tests.pdf_factory import Page, build_pdf, caption, paragraph, rect


@pytest.mark.parametrize(
    ("text", "letters"),
    [
        ("Disease risks.a Comparison of groups. b Association. c AUCs.", "abc"),
        ("Overview. (A) Map. (B) Time series; (C–E) Quantification as in (A).", "ABCDE"),
        ("Fluorophores. a, Signal. b, Antibodies. c-e, Cell types.", "abcde"),
        ("A total of 5 cells were imaged. A. Control. B. Treated.", "AB"),
        ("No panels here. A typical example shows a trend.", ""),
        ("Only (b) is mentioned here.", ""),
    ],
)
def test_caption_markers_form_a_sequence(text, letters):
    assert "".join(caption_letters(text)) == letters


def test_subcaptions_keep_their_text_and_the_common_part():
    common, subs = parse_subcaptions("Cell growth. a, Control cells. b, Treated cells; scale 5 µm.")
    assert common == "Cell growth."
    assert [(s.labels, s.text) for s in subs] == [
        (["a"], "Control cells."),
        (["b"], "Treated cells; scale 5 µm."),
    ]


def canvas(height=200, width=300, background=255):
    return np.full((height, width), background, dtype=np.uint8)


def test_grid_is_split_in_reading_order():
    image = canvas()
    for x0, y0 in [(10, 10), (160, 10), (10, 110), (160, 110)]:
        image[y0 : y0 + 80, x0 : x0 + 130] = 40
    boxes, merged = split_figure(image, expected=4)
    assert not merged
    assert [b[:2] for b in boxes] == [(10, 10), (160, 10), (10, 110), (160, 110)]


def test_thin_rows_join_their_panel_and_dark_backgrounds_work():
    image = canvas(background=0)
    image[20:30, 10:20] = 255  # a panel letter on its own row
    image[36:190, 10:140] = 200
    image[20:190, 160:290] = 200
    boxes, _ = split_figure(image, expected=2)
    assert boxes == [(10, 20, 140, 190), (160, 20, 290, 190)]


def test_pieces_of_one_panel_are_merged_to_the_announced_count():
    image = canvas(height=200, width=400)
    image[10:190, 10:120] = 40  # panel a: one tall image
    image[40:190, 130:255] = 40  # panel b: two shorter images side by side,
    image[40:190, 265:390] = 40  # all gaps equally narrow
    boxes, merged = split_figure(image, expected=2)
    assert merged and boxes == [(10, 10, 120, 190), (130, 40, 390, 190)]
    assert reading_order([(140, 10, 390, 190), (10, 10, 120, 190)])[0][0] == 10


def test_detect_panels_publishes_boxes_only_when_the_count_matches():
    image = canvas()
    image[10:190, 10:140] = 40
    image[10:190, 160:290] = 40
    result = detect_panels(image, "Growth. (a) Control. (b) Treated.")
    assert result.layout == "split" and [p.label for p in result.panels] == ["a", "b"]
    assert all(p.confidence == CONFIDENCE_EXACT for p in result.panels)
    assert result.panels[1].subcaption == "Treated."

    unmatched = detect_panels(image, "Growth. (a) Control. (b) Treated. (c) Both.")
    assert unmatched.layout == "unmatched"
    assert [(p.label, p.box) for p in unmatched.panels] == [("a", None), ("b", None), ("c", None)]
    assert detect_panels(image, "A single chart of growth.").layout == "single"
    assert CONFIDENCE_MERGED < CONFIDENCE_EXACT


def test_extractor_splits_a_multipanel_figure():
    page = Page(
        rect(100, 450, 180, 200)
        + rect(300, 450, 180, 200)
        + caption(100, 430, "Figure 1.", "Growth curves. (a) Control cells. (b) Treated cells.")
        + paragraph(72, 380, 12)
    )
    result = PdfiumFigureExtractor().extract(pdfium.PdfDocument(build_pdf([page])))
    [figure] = result.figures
    assert figure.panel_layout == "split"
    a, b = figure.panels
    assert (a.label, b.label) == ("a", "b") and b.subcaption == "Treated cells."
    # Boxes are page points, top-left origin: panel a is the left rectangle.
    assert a.box.x1 < b.box.x0
    assert a.box.x0 == pytest.approx(100, abs=2) and b.box.x1 == pytest.approx(480, abs=2)
    assert a.box.y0 == pytest.approx(792 - 650, abs=2)


def test_group_markers_give_each_panel_its_own_text():
    _, subs = parse_subcaptions(
        "ZnO. (A–C): Micrographs of Cassia. (A) 500x. (B) 2000x. (C) 5000x. (D, E) Melia."
    )
    assert [(s.labels, s.text) for s in subs] == [
        (["A"], "Micrographs of Cassia. 500x."),
        (["B"], "Micrographs of Cassia. 2000x."),
        (["C"], "Micrographs of Cassia. 5000x."),
        (["D", "E"], "Melia."),
    ]


def test_panel_metrics_against_human_boxes():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[1] / "scripts" / "eval" / "sfi48_eval.py"
    spec = importlib.util.spec_from_file_location("sfi48_eval", path)
    evaluation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluation)

    assert evaluation.average_precision([(0.8, True), (0.8, False)], 1) == 1.0
    assert evaluation.average_precision([(0.8, False), (0.6, True)], 2) == 0.25
    gold = {"a": [0.0, 0.0, 0.5, 1.0], "b": [0.5, 0.0, 1.0, 1.0]}
    swapped = [  # right boxes, letters in the wrong order, one sub-caption wrong
        {"label": "b", "box": [0.0, 0.0, 0.5, 1.0], "confidence": 0.8, "subcaption_ok": True},
        {"label": "a", "box": [0.5, 0.0, 1.0, 1.0], "confidence": 0.8, "subcaption_ok": True},
    ]
    result = evaluation.panel_gold_metrics([{"gold": gold, "system": swapped}])
    assert result["ap50"] == 1.0 and result["label_accuracy"]["value"] == 0.0
    assert result["panel_subcaption_f1"] == 0.0 and result["count_accuracy"]["value"] == 1.0
    right = [dict(p, label=x) for p, x in zip(swapped, "ab", strict=True)]
    right[1]["subcaption_ok"] = False
    result = evaluation.panel_gold_metrics([{"gold": gold, "system": right}])
    assert result["label_accuracy"]["value"] == 1.0 and result["panel_subcaption_f1"] == 0.5


def test_panel_boxes_below_the_calibrated_confidence_are_not_shown():
    from sfi.domain.models import BBox, Figure, Panel
    from sfi.extract.panels import PUBLISH_MIN_CONFIDENCE
    from sfi.web.app import panels_json

    box = BBox(left=100, bottom=400, right=300, top=600)
    panel = {"label": "a", "bbox": box, "subcaption": "Control.", "method": "xy-cut"}
    figure = Figure(
        id="f",
        document_id="d",
        run_id="r",
        label="Figure 1",
        page_index=0,
        bbox=box,
        bbox_normalized=box.normalized(612, 792),
        status="ok",
        confidence=0.9,
        producer="t",
        producer_version="0",
        panels=[
            Panel(**panel, bbox_normalized=box.normalized(612, 792), confidence=CONFIDENCE_EXACT),
            Panel(
                **panel | {"label": "b"},
                bbox_normalized=box.normalized(612, 792),
                confidence=PUBLISH_MIN_CONFIDENCE,
            ),
        ],
    )
    hidden, shown = panels_json(figure, 612, 792)
    assert (hidden["box"], hidden["image_box"], hidden["subcaption"]) == (None, None, "Control.")
    assert shown["box"] is not None and shown["image_box"] is not None


# --- panels anchored on printed letters --------------------------------------------------

from sfi.extract.evidence import PANEL_ANCHORS_VERSION, read_lone_letters  # noqa: E402
from sfi.extract.panels import (  # noqa: E402
    CONFIDENCE_ANCHORED,
    CONFIDENCE_INFERRED,
    anchored_split,
    detect_anchored_panels,
    find_anchors,
    grid_split,
)


def lettered_grid(labels_below: bool = False):
    """Four plots in a 2 x 2 grid with a small letter per panel, as OCR tokens."""
    image = canvas(height=420, width=420)
    tokens = []
    for i, (x0, y0) in enumerate([(30, 30), (230, 30), (30, 230), (230, 230)]):
        image[y0 : y0 + 150, x0 : x0 + 150] = 60  # the plot
        if labels_below:
            box = (x0 + 68, y0 + 160, x0 + 82, y0 + 176)  # "(a)" centred under it
        else:
            box = (x0 - 20, y0 - 22, x0 - 6, y0 - 6)  # "a" at its top-left
        image[box[1] : box[3], box[0] : box[2]] = 20  # the letter's ink
        tokens.append((f"({'abcd'[i]})" if labels_below else "abcd"[i], box, 0.95))
    return image, tokens


def test_top_left_letters_bound_their_panels():
    image, tokens = lettered_grid()
    anchors = find_anchors(tokens, list("abcd"))
    regions = dict(anchored_split(image < 235, anchors, list("abcd")))
    # Each panel holds its letter and its plot, and nothing of the neighbours.
    assert regions["a"] == (10, 8, 180, 180)
    assert regions["d"][0] >= 200 and regions["d"][1] >= 200


def test_letters_under_the_plots_are_recognised():
    image, tokens = lettered_grid(labels_below=True)
    anchors = find_anchors(tokens, list("abcd"))
    regions = dict(anchored_split(image < 235, anchors, list("abcd")))
    assert regions["a"] == (30, 30, 180, 206) and regions["c"][1] >= 200


def test_letters_inside_a_line_of_text_are_not_panel_letters():
    # "Subclade C and D" in a legend, read before the real panel letters below.
    tokens = [
        ("Subclade", (300, 40, 360, 52), 1.0),
        ("C", (364, 40, 372, 52), 1.0),
        ("and", (376, 40, 396, 52), 1.0),
        ("D", (400, 40, 408, 52), 1.0),
        ("C", (10, 250, 22, 264), 0.95),
        ("D", (210, 250, 222, 264), 0.95),
    ]
    anchors = find_anchors(tokens, list("CD"))
    assert anchors == {"C": (10, 250, 22, 264), "D": (210, 250, 222, 264)}


def test_letters_on_a_clear_margin_beat_letters_inside_a_photo():
    image = canvas(height=300, width=300)
    image[100:250, 100:250] = 90  # a photo with a letter "A" printed inside it
    tokens = [("A", (150, 150, 162, 164), 0.99), ("A", (2, 2, 14, 16), 0.9)]
    anchors = find_anchors(tokens, ["A"], image < 235)
    assert anchors["A"] == (2, 2, 14, 16)


def test_a_tall_panel_spanning_two_rows_stays_whole():
    # a above b on the left; c on the right, as tall as a and b together.
    image = canvas(height=420, width=420)
    image[30:180, 30:180] = 60
    image[230:380, 30:180] = 60
    image[30:380, 230:380] = 60
    tokens = []
    for letter, (x0, y0) in zip("abc", [(30, 30), (30, 230), (230, 30)], strict=True):
        box = (x0 - 20, y0 - 22, x0 - 6, y0 - 6)
        image[box[1] : box[3], box[0] : box[2]] = 20
        tokens.append((letter, box, 0.95))
    regions = dict(anchored_split(image < 235, find_anchors(tokens, list("abc")), list("abc")))
    assert regions["c"] == (210, 8, 380, 380)
    assert regions["b"][2] <= 200  # b does not reach into c's column


def test_letters_under_rows_that_touch_are_read_as_labels_below():
    # Four photo strips with no white gap between them, each with its letter at the
    # bottom-left: only the ink left outside the panels tells where letters belong.
    image = canvas(height=410, width=300)
    image[0:400, 20:300] = 90
    anchors = {}
    for i, letter in enumerate("abcd"):
        box = (2, 100 * i + 84, 14, 100 * i + 98)
        image[box[1] : box[3], box[0] : box[2]] = 20
        anchors[letter] = box
    regions = dict(grid_split(image < 235, anchors, list("abcd")))
    assert regions["a"][1] == 0 and regions["a"][3] == 99  # down to its letter
    assert regions["b"][1] == 99


class LetterReader:
    """Fake OCR engine whose recogniser reads every blob it is shown as "b"."""

    name, version = "fake", "1"

    def __init__(self):
        self.shown = 0

    def read(self, image):
        return []

    def read_line(self, image):
        self.shown += 1
        return "b", 0.9


def test_lone_letters_are_read_one_at_a_time():
    image = canvas(height=200, width=300)
    image[20:32, 10:18] = 20  # a lone letter
    image[100:112, 100:108] = 20  # a letter inside a word: neighbours on both sides
    image[100:112, 110:118] = 20
    image[100:112, 120:128] = 20
    reader = LetterReader()
    found = read_lone_letters(image, ["b"], reader, size=12)
    assert found == [("b", (10, 20, 18, 32), 0.9)] and reader.shown == 1


def test_one_unread_letter_is_placed_on_the_grid():
    image, tokens = lettered_grid()
    caption = "Results. (a) One. (b) Two. (c) Three. (d) Four."
    without_c = [t for t in tokens if t[0] != "c"]
    result = detect_anchored_panels(image, caption, without_c)
    assert result is not None and all(p.confidence == CONFIDENCE_INFERRED for p in result.panels)
    boxes = {p.label: p.box for p in result.panels}
    assert boxes["c"][1] >= 200 and boxes["c"][2] <= 200  # bottom-left, where c belongs
    assert (
        detect_anchored_panels(image, caption, tokens).panels[0].confidence == CONFIDENCE_ANCHORED
    )
    assert detect_anchored_panels(image, caption, without_c[:2]) is None  # two missing


def test_pipeline_uses_the_letters_read_in_the_figure(tmp_path):
    from sfi.config import Settings
    from sfi.pipeline import FigurePipeline
    from sfi.storage.blobs import LocalBlobStore
    from sfi.storage.repository import SQLiteRepository
    from tests.test_evidence import FakeOcr

    page = Page(
        rect(100, 450, 180, 200)
        + rect(300, 450, 180, 200)
        + caption(100, 430, "Figure 1.", "Growth curves. (a) Control cells. (b) Treated cells.")
        + paragraph(72, 380, 12)
    )
    path = tmp_path / "panels.pdf"
    path.write_bytes(build_pdf([page]))
    # Letters just above each rectangle, in pixels of the 200 dpi OCR rendering.
    s = 200 / 72

    def quad(x, y):
        return [
            [x * s, y * s],
            [(x + 8) * s, y * s],
            [(x + 8) * s, (y + 10) * s],
            [x * s, (y + 10) * s],
        ]

    engine = FakeOcr([("a", quad(2, 2), 0.9), ("b", quad(202, 2), 0.9)])
    settings = Settings(data_dir=tmp_path / "data", render_dpi=72, max_pdf_mb=1, max_pages=5)
    pipeline = FigurePipeline(
        settings,
        SQLiteRepository(settings.database_path),
        LocalBlobStore(settings.blob_dir),
        ocr_engine=engine,
    )
    [figure] = pipeline.process(path).figures
    assert [p.method for p in figure.panels] == [PANEL_ANCHORS_VERSION] * 2
    a, b = (p.bbox_normalized for p in figure.panels)
    assert a[2] <= b[0]  # a is the left rectangle, b the right one
