"""Experiment E03: how well OCR reads the text inside figures, before relying on it.

Two references that need no new annotation:

1. Vector figures (dev + validation): the PDF text layer inside the figure is exact.
   The figure is rendered as an image at several resolutions and read by OCR; each
   PDF word is matched to the OCR line over it. Metrics: entity accuracy for numbers
   (the gate of E03: >= 0.95 born-digital), word accuracy, and how often an OCR line
   over a number reads a different number (substitutions).
2. Panel letters: the human panel boxes (data/sfi48/reviews/panels.json). A letter
   counts as found when a token of the figure (PDF text or OCR) reads exactly that
   letter, ignoring parentheses and case, inside its panel box (enlarged by 10 %).

The test split is never used. Each run is recorded in evaluation/runs/.

Usage:
    python scripts/eval/ocr_eval.py [--dpi 150,200,300] [--min-words 15] [--no-save]
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
from pathlib import Path

import pypdfium2 as pdfium

from sfi.extract.evidence import (
    RapidOcrEngine,
    TextToken,
    figure_tokens,
    numbers_in,
    ocr_tokens,
    pdf_tokens,
)
from sfi.extract.extractor import PdfiumFigureExtractor
from sfi.extract.layout import Box
from sfi.review import ReviewStore, figure_key, load_reference

sys.path.insert(0, str(Path(__file__).parent))
from runlog import save_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SPLITS = ("dev", "validation")


def overlap(a: Box, b: Box) -> float:
    return a.x_overlap(b) * a.y_overlap(b)


def normalize_word(text: str) -> str:
    return re.sub(r"[^0-9a-zα-ωµμ%°]+", "", text.lower().replace("−", "-"))


def score_vector_figure(native: list[TextToken], read: list[TextToken]) -> dict:
    """Match each PDF word to the OCR lines that cover it."""
    numbers = words = number_hits = word_hits = substitutions = 0
    for word in native:
        covering = [t for t in read if overlap(t.box, word.box) > 0.5 * word.box.area]
        # Unsigned, like the validator: a minus sign is often a separate glyph.
        expected = [n.lstrip("-") for n in numbers_in(word.text)]
        if expected:
            numbers += len(expected)
            found = [n.lstrip("-") for t in covering for n in numbers_in(t.text)]
            hits = sum(1 for n in expected if n in found)
            number_hits += hits
            substitutions += sum(1 for n in expected if n not in found and found)
        elif len(normalize_word(word.text)) >= 2:
            words += 1
            seen = {normalize_word(w) for t in covering for w in t.text.split()}
            word_hits += normalize_word(word.text) in seen
    return {
        "numbers": numbers,
        "number_hits": number_hits,
        "number_substitutions": substitutions,
        "words": words,
        "word_hits": word_hits,
    }


def ratio(hits: int, total: int) -> dict:
    return {"value": round(hits / total, 3) if total else None, "n": total}


def letter_key(text: str) -> str:
    return re.sub(r"[()\[\].,:;\s]", "", text).lower()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus-dir", type=Path, default=ROOT / "data/sfi48")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/sfi48")
    parser.add_argument("--dpi", default="150,200,300")
    parser.add_argument("--panel-dpi", type=int, default=200)
    parser.add_argument("--min-words", type=int, default=15, help="PDF words for a vector figure")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    dpis = [int(x) for x in args.dpi.split(",")]

    engine = RapidOcrEngine()
    extractor = PdfiumFigureExtractor()
    reference = load_reference(args.corpus_dir)
    articles = [a for a in reference["articles"] if a["split"] in SPLITS]

    # 1. Vector figures: PDF text as the exact reference.
    rows, timings = [], {d: [] for d in dpis}
    for article in articles:
        pdf = pdfium.PdfDocument(args.raw_dir / f"{article['pmcid']}.pdf")
        result = extractor.extract(pdf)
        for figure in result.figures:
            if figure.box is None or result.pages[figure.page_index].is_scanned:
                continue
            native = pdf_tokens(pdf[figure.page_index], figure.box)
            if len(native) < args.min_words:
                continue
            row = {"pmcid": article["pmcid"], "label": figure.label, "pdf_words": len(native)}
            for dpi in dpis:
                started = time.perf_counter()
                read = ocr_tokens(pdf[figure.page_index], figure.box, engine, dpi)
                timings[dpi].append(time.perf_counter() - started)
                row[str(dpi)] = score_vector_figure(native, read)
            rows.append(row)
            print(f"vector {article['pmcid']:<12} {figure.label!s:<24} words={len(native)}")
        pdf.close()

    vector = {}
    for dpi in dpis:
        sums = {k: sum(r[str(dpi)][k] for r in rows) for k in rows[0][str(dpi)]} if rows else {}
        vector[str(dpi)] = {
            "figures": len(rows),
            "number_accuracy": ratio(sums.get("number_hits", 0), sums.get("numbers", 0)),
            "number_substitutions": sums.get("number_substitutions", 0),
            "word_accuracy": ratio(sums.get("word_hits", 0), sums.get("words", 0)),
            "seconds_per_figure": round(statistics.mean(timings[dpi]), 2) if timings[dpi] else None,
        }

    # 2. Panel letters against the human panel boxes.
    figures = {
        (a["pmcid"], figure_key(f)): (a, f) for a in reference["articles"] for f in a["figures"]
    }
    letter_rows = []
    by_pmcid: dict[str, list[dict]] = {}
    for review in ReviewStore(args.corpus_dir / "reviews").panel_reviews():
        if review["decision"] == "done" and (review["pmcid"], review["figure"]) in figures:
            article, _ = figures[(review["pmcid"], review["figure"])]
            if article["split"] in SPLITS:
                by_pmcid.setdefault(review["pmcid"], []).append(review)
    for pmcid, reviews in sorted(by_pmcid.items()):
        pdf = pdfium.PdfDocument(args.raw_dir / f"{pmcid}.pdf")
        for review in reviews:
            _, figure = figures[(pmcid, review["figure"])]
            page = pdf[figure["page"] - 1]
            left, bottom, right, top = page.get_cropbox()
            width, height = right - left, top - bottom

            def to_box(b, w=width, h=height):
                return Box(b[0] * w, b[1] * h, b[2] * w, b[3] * h)

            tokens = figure_tokens(page, to_box(figure["bbox"]), engine, args.panel_dpi)
            single = [t for t in tokens if len(letter_key(t.text)) == 1]
            for panel in review["panels"]:
                if not panel.get("bbox"):
                    continue
                box = to_box(panel["bbox"])
                grow_x, grow_y = 0.1 * box.width, 0.1 * box.height
                area = Box(box.x0 - grow_x, box.y0 - grow_y, box.x1 + grow_x, box.y1 + grow_y)
                found = [
                    t
                    for t in single
                    if letter_key(t.text) == panel["label"].lower()
                    and area.x0 <= t.box.cx <= area.x1
                    and area.y0 <= t.box.cy <= area.y1
                ]
                letter_rows.append(
                    {
                        "pmcid": pmcid,
                        "figure": review["figure"],
                        "label": panel["label"],
                        "found": bool(found),
                        "exact_case": any(t.text.strip("()[]. ") == panel["label"] for t in found),
                        "source": found[0].source if found else None,
                    }
                )
        pdf.close()
    letters = {
        "panels": len(letter_rows),
        "figures": len({(r["pmcid"], r["figure"]) for r in letter_rows}),
        "letter_recall": ratio(sum(r["found"] for r in letter_rows), len(letter_rows)),
        "letter_recall_exact_case": ratio(
            sum(r["exact_case"] for r in letter_rows), len(letter_rows)
        ),
        "dpi": args.panel_dpi,
    }

    metrics = {
        "engine": f"{engine.name}-{engine.version}",
        "vector": vector,
        "panel_letters": letters,
    }
    print("vector figures:", vector)
    print("panel letters:", letters)
    if not args.no_save:
        target = save_run(
            "ocr",
            f"{engine.name}-{engine.version}",
            {
                "dpi": dpis,
                "panel_dpi": args.panel_dpi,
                "min_words": args.min_words,
                "splits": SPLITS,
                "engine_params": engine.params,
            },
            metrics,
            [{"kind": "vector", **r} for r in rows]
            + [{"kind": "letter", **r} for r in letter_rows],
            {"reference_version": reference["version"]},
        )
        print(f"run saved to {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
