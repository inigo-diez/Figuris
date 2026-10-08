"""Extraction rules on synthetic PDFs with known geometry."""

from __future__ import annotations

import numpy as np
import pypdfium2 as pdfium
import pytest

from sfi.domain.models import WarningCode
from sfi.extract.captions import normalize_label, normalize_number, parse_label
from sfi.extract.extractor import PdfiumFigureExtractor
from sfi.extract.grid import dilate, label_components
from sfi.extract.layout import read_page_layout
from tests.pdf_factory import PAGE_H, Page, build_pdf, caption, paragraph, rect, text


def extract(*pages: Page):
    return PdfiumFigureExtractor().extract(pdfium.PdfDocument(build_pdf(list(pages))))


def top_left(
    x0: float, y0_pdf: float, x1: float, y1_pdf: float
) -> tuple[float, float, float, float]:
    """Convert a PDF-space rectangle (bottom-left origin) to extractor coordinates."""
    return x0, PAGE_H - y1_pdf, x1, PAGE_H - y0_pdf


def assert_box(box, expected, tolerance=3.0):
    got = (box.x0, box.y0, box.x1, box.y1)
    assert all(abs(g - e) <= tolerance for g, e in zip(got, expected, strict=True)), (got, expected)


# --- caption labels -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        ("Fig. 3 | Comparison of indicators", "Figure 3"),
        ("Figure 2. LULC maps", "Figure 2"),
        ("FIGURE 4 Results", "Figure 4"),
        ("Extended Data Fig. 1 |. Features", "Extended Data Figure 1"),
        ("Supplementary Figure S2: details", "Supplementary Figure S2"),
        ("Table IV Classification", "Table 4"),
        ("Scheme 1. Synthesis", "Scheme 1"),
        ("Figure I Age-standardised rates", "Figure 1"),  # OCR reads "1" as "I"
    ],
)
def test_parse_label(raw, label):
    assert normalize_label(raw) == label


def test_parse_label_rejects_plain_text():
    assert parse_label("Figures show the results") is None
    assert parse_label("Configuration of the device") is None


def test_normalize_number():
    assert normalize_number("IX") == "9"
    assert normalize_number("l") == "1"
    assert normalize_number("12") == "12"


# --- grid -----------------------------------------------------------------


def test_label_components_counts_separate_blobs():
    mask = np.zeros((10, 10), dtype=bool)
    mask[1:3, 1:3] = True
    mask[6:9, 5:9] = True
    labels, count = label_components(mask)
    assert count == 2
    assert labels[1, 1] != labels[7, 7]


def test_dilate_merges_close_blobs():
    mask = np.zeros((10, 10), dtype=bool)
    mask[5, 2] = mask[5, 5] = True
    assert label_components(dilate(mask, 1))[1] == 1


# --- figure extraction ----------------------------------------------------


def test_figure_with_caption_below():
    page = Page(
        paragraph(60, 740, 8)
        + rect(100, 350, 400, 250)
        + caption(60, 335, "Figure 1.", "A synthetic chart used for testing.")
        + paragraph(60, 300, 10)
    )
    result = extract(page)
    [figure] = result.figures
    assert (figure.label, figure.status, figure.relation) == ("Figure 1", "ok", "caption_below")
    assert_box(figure.box, top_left(100, 350, 500, 600))
    assert figure.caption.text == "Figure 1. A synthetic chart used for testing."


def test_two_figures_on_one_page_get_their_own_captions():
    page = Page(
        rect(100, 560, 400, 170)
        + caption(60, 545, "Figure 1.", "Upper figure.")
        + rect(100, 300, 400, 200)
        + caption(60, 285, "Figure 2.", "Lower figure.")
        + paragraph(60, 250, 8)
    )
    result = extract(page)
    boxes = {f.label: f.box for f in result.figures}
    assert set(boxes) == {"Figure 1", "Figure 2"}
    assert_box(boxes["Figure 1"], top_left(100, 560, 500, 730))
    assert_box(boxes["Figure 2"], top_left(100, 300, 500, 500))


def test_side_caption():
    side = "".join(
        caption(60, 600 - i * 11, "Fig. 3" if i == 0 else "", f"side caption line {i}")
        for i in range(5)
    )
    page = Page(rect(230, 420, 320, 200) + side + paragraph(60, 380, 12))
    [figure] = extract(page).figures
    assert (figure.label, figure.relation) == ("Figure 3", "caption_beside")
    assert_box(figure.box, top_left(230, 420, 550, 620))


def test_table_regions_are_not_reported_as_figures():
    page = Page(
        paragraph(60, 740, 6)
        + caption(60, 640, "Table 1.", "Measured values.")
        + rect(60, 450, 480, 175)
        + paragraph(60, 420, 10)
    )
    result = extract(page)
    assert result.figures == []
    assert result.tables_detected == 1


def test_in_text_reference_is_not_a_caption():
    page = Page(
        paragraph(60, 740, 5)
        + text(
            60,
            680,
            "Fig. 2 shows the results of the second experiment "
            "in more detail than the summary table.",
        )
        + paragraph(60, 668, 5)
    )
    assert extract(page).figures == []


def test_caption_without_graphics_is_reported_with_warning():
    page = Page(
        paragraph(60, 740, 6)
        + caption(60, 600, "Figure 1.", "Missing artwork.")
        + paragraph(60, 560, 6)
    )
    [figure] = extract(page).figures
    assert figure.status == "caption_only"
    assert figure.box is None
    assert WarningCode.CAPTION_WITHOUT_REGION in {w.code for w in figure.warnings}


def test_gap_in_numbering_is_warned():
    page = Page(
        rect(100, 560, 400, 170)
        + caption(60, 545, "Figure 1.", "First.")
        + rect(100, 300, 400, 200)
        + caption(60, 285, "Figure 3.", "Third.")
    )
    result = extract(page)
    missing = [w for w in result.warnings if w.code == WarningCode.MISSING_IN_SEQUENCE]
    assert [w.figure_label for w in missing] == ["Figure 2"]


def test_axis_labels_join_the_figure():
    labels = text(68, 470, "Intensity", 8) + text(280, 340, "Wavelength (nm)", 8)
    page = Page(
        rect(100, 350, 400, 250)
        + labels
        + caption(60, 320, "Figure 1.", "Spectrum.")
        + paragraph(60, 280, 8)
    )
    [figure] = extract(page).figures
    assert figure.box.x0 <= 69  # y-axis label left of the plot is part of the figure
    assert figure.box.y1 >= PAGE_H - 341  # x-axis label below the plot is included


# --- PDF structure ----------------------------------------------------------


def test_form_xobject_children_are_placed_in_page_space():
    # Form draws a 100x50 rectangle, scaled x2 by its matrix and placed at (100, 300).
    page = Page(
        "q 1 0 0 1 100 300 cm /Fm1 Do Q\n" + caption(60, 285, "Figure 1.", "Scaled form."),
        forms={"Fm1": ("2 0 0 2 0 0", rect(0, 0, 100, 50))},
    )
    [figure] = extract(page).figures
    assert_box(figure.box, top_left(100, 300, 300, 400))


def test_content_hidden_by_a_clip_path_is_ignored():
    # A large drawing and some text are clipped to a 200x100 window.
    hidden = rect(0, 0, 400, 400) + text(10, 380, "invisible words outside the clip window")
    page = Page(
        "q 100 300 200 100 re W n 1 0 0 1 0 0 cm /Fm1 Do Q\n"
        + caption(60, 285, "Figure 1.", "Clipped artwork."),
        forms={"Fm1": ("1 0 0 1 0 0", hidden)},
    )
    pdf = pdfium.PdfDocument(build_pdf([page]))
    layout = read_page_layout(pdf[0], 0)
    assert not any("invisible" in line.text for line in layout.lines)
    [figure] = PdfiumFigureExtractor().extract(pdf).figures
    assert_box(figure.box, top_left(100, 300, 300, 400))


FULL_LINE = (
    "the fluorescent signal measured in every replicate of the second group of animals and the"
)


def test_finished_caption_at_page_bottom_does_not_absorb_the_next_page():
    page1 = Page(
        paragraph(60, 740, 6)
        + rect(100, 300, 400, 300)
        + caption(
            60,
            90,
            "Figure 1.",
            "A synthetic chart of the fluorescent signal in all groups.",
            size=10,
        )
        + text(60, 78, "Bars are means.")
    )
    page2 = Page(paragraph(60, 740, 10))
    [figure] = extract(page1, page2).figures
    assert figure.caption.text.endswith("Bars are means.")
    assert figure.caption.continuation_lines == []
    assert WarningCode.CAPTION_MAY_CONTINUE not in {w.code for w in figure.warnings}


def test_caption_cut_at_page_bottom_takes_its_continuation():
    page1 = Page(
        paragraph(60, 740, 6)
        + rect(100, 300, 400, 300)
        + caption(
            60,
            90,
            "Figure 1.",
            "A synthetic chart of the fluorescent signal in all groups:",
            size=10,
        )
        + text(60, 78, FULL_LINE)
    )
    page2 = Page(
        text(60, 740, "control animals measured after the treatment.") + paragraph(60, 700, 8)
    )
    [figure] = extract(page1, page2).figures
    assert figure.caption.text.endswith("control animals measured after the treatment.")
    codes = {w.code for w in figure.warnings}
    assert WarningCode.CAPTION_CONTINUED in codes  # joined: not reported as truncated
    assert WarningCode.CAPTION_MAY_CONTINUE not in codes


def test_single_line_caption_at_page_bottom_is_complete():
    page1 = Page(
        paragraph(60, 740, 6)
        + rect(100, 300, 400, 300)
        + caption(60, 80, "Figure 1.", "A chart.", size=10)
    )
    page2 = Page(paragraph(60, 740, 10))
    [figure] = extract(page1, page2).figures
    assert figure.caption.text == "Figure 1. A chart."


def test_panel_descriptions_on_the_next_page_continue_a_finished_title():
    page1 = Page(
        paragraph(60, 740, 6)
        + rect(100, 300, 400, 300)
        + caption(60, 80, "Figure 1.", "Images after several imaging cycles.", size=10)
    )
    page2 = Page(
        text(60, 740, "a, Left panel: overview of the tissue section. b, Detail.")
        + paragraph(60, 700, 8)
    )
    [figure] = extract(page1, page2).figures
    assert figure.caption.text.endswith("b, Detail.")
