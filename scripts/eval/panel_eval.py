"""Experiment E02: panel splitting methods against the human panel boxes.

For every figure with human panel boxes (data/sfi48/reviews/panels.json) in dev and
validation, three methods are scored with the metrics of sfi48_eval.py (AP50, label
accuracy, panel-subcaption F1, count accuracy):

- ``xycut``: whitespace cuts guided by the caption (the extractor's baseline);
- ``anchors``: regions around the panel letters printed in the figure, found in the
  evidence layer (PDF text and OCR, plus lone letters read one by one), exactly as the
  pipeline does (``evidence.anchor_panels``); figures where the letters do not
  determine the panels get no boxes;
- ``hybrid``: anchors when the letters determine the panels, else xycut.

Results are given for all figures and per split (dev was used to build both
methods). Each run is recorded in evaluation/runs/. The frozen ``test`` split is only
scored with --include-test, and every such run is appended to
data/sfi48/test_runs.log.

Usage:
    python scripts/eval/panel_eval.py [--include-test] [--no-save]
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pypdfium2 as pdfium

from sfi.extract.evidence import (
    PANEL_ANCHORS_VERSION,
    RapidOcrEngine,
    anchor_panels,
    figure_tokens,
)
from sfi.extract.extractor import PANEL_DPI, PdfiumFigureExtractor
from sfi.review import ReviewStore, figure_key, load_reference

sys.path.insert(0, str(Path(__file__).parent))
from runlog import save_run  # noqa: E402
from sfi48_eval import (  # noqa: E402
    CAPTION_MATCH,
    comparable,
    jats_captions,
    panel_gold_metrics,
    subcaption_map,
)

ROOT = Path(__file__).resolve().parents[2]
SPLITS = ("dev", "validation")


def main() -> int:
    import difflib

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus-dir", type=Path, default=ROOT / "data/sfi48")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/sfi48")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument(
        "--include-test", action="store_true", help="also score the frozen test split"
    )
    args = parser.parse_args()
    splits = SPLITS + ("test",) if args.include_test else SPLITS
    if args.include_test:
        with (args.corpus_dir / "test_runs.log").open("a", encoding="utf-8") as handle:
            handle.write(
                f"{dt.datetime.now(dt.UTC).isoformat(timespec='seconds')} "
                "panel_eval --include-test\n"
            )

    engine = RapidOcrEngine()
    extractor = PdfiumFigureExtractor()
    reference = load_reference(args.corpus_dir)
    split_of = {a["pmcid"]: a["split"] for a in reference["articles"]}
    labels = {
        (a["pmcid"], figure_key(f)): f["label"] for a in reference["articles"] for f in a["figures"]
    }
    reviews: dict[str, list[dict]] = {}
    for review in ReviewStore(args.corpus_dir / "reviews").panel_reviews():
        if review["decision"] == "done" and split_of.get(review["pmcid"]) in splits:
            reviews.setdefault(review["pmcid"], []).append(review)

    rows = []
    for pmcid, items in sorted(reviews.items()):
        pdf = pdfium.PdfDocument(args.raw_dir / f"{pmcid}.pdf")
        result = extractor.extract(pdf)
        captions = jats_captions(args.raw_dir / f"{pmcid}.xml")
        for review in items:
            label = labels.get((pmcid, review["figure"]))
            figure = next((f for f in result.figures if f.label == label and f.box), None)
            gold = {p["label"]: p["bbox"] for p in review["panels"] if p.get("bbox")}
            if figure is None or not gold:
                continue
            page = pdf[figure.page_index]
            layout = result.pages[figure.page_index]
            box = figure.box
            jats_panels = subcaption_map(captions.get(label, ""))

            def entry(label_, page_box, confidence, subcaption, jats_panels=jats_panels):
                ok = (
                    difflib.SequenceMatcher(
                        None,
                        comparable(subcaption),
                        comparable(jats_panels.get(label_, "")),
                        autojunk=False,
                    ).ratio()
                    >= CAPTION_MATCH
                )
                return {
                    "label": label_,
                    "box": page_box,
                    "confidence": confidence,
                    "subcaption_ok": ok,
                }

            xycut = [
                entry(
                    p.label,
                    [
                        p.box.x0 / layout.width,
                        p.box.y0 / layout.height,
                        p.box.x1 / layout.width,
                        p.box.y1 / layout.height,
                    ],
                    p.confidence,
                    p.subcaption,
                )
                for p in figure.panels
                if p.box is not None
            ]
            caption = figure.caption.text if figure.caption else ""
            tokens = figure_tokens(page, box, engine)
            anchored = anchor_panels(page, box, caption, tokens, PANEL_DPI, engine)
            anchors = [
                entry(
                    label_,
                    [
                        b.x0 / layout.width,
                        b.y0 / layout.height,
                        b.x1 / layout.width,
                        b.y1 / layout.height,
                    ],
                    confidence,
                    subcaption,
                )
                for label_, b, subcaption, confidence in anchored or []
            ]
            rows.append(
                {
                    "pmcid": pmcid,
                    "figure": review["figure"],
                    "split": split_of[pmcid],
                    "gold": gold,
                    "xycut": xycut,
                    "anchors": anchors,
                    "hybrid": anchors or xycut,
                    "anchored": bool(anchored),
                }
            )
            print(
                f"{pmcid:<12} {label:<24} gold={len(gold)} xycut={len(xycut)} "
                f"anchors={'yes' if anchored else 'no'}"
            )
        pdf.close()

    def score(selection):
        out = {}
        for method in ("xycut", "anchors", "hybrid"):
            out[method] = panel_gold_metrics(
                [{"gold": r["gold"], "system": r[method]} for r in selection]
            )
        out["anchored_share"] = round(sum(r["anchored"] for r in selection) / len(selection), 3)
        # Where every letter was found: are anchored boxes better than whitespace cuts?
        anchored = [r for r in selection if r["anchored"]]
        if anchored:
            out["where_anchored"] = {
                method: panel_gold_metrics(
                    [{"gold": r["gold"], "system": r[method]} for r in anchored]
                )
                for method in ("xycut", "anchors")
            }
        return out

    def brief(v: dict) -> tuple:
        return (v["ap50"], v["label_accuracy"]["value"], v["panel_subcaption_f1"])

    metrics = {"all": score(rows)}
    for split in splits:
        chosen = [r for r in rows if r["split"] == split]
        if chosen:
            metrics[split] = score(chosen)
    for name, values in metrics.items():
        methods = {m: brief(values[m]) for m in ("xycut", "anchors", "hybrid")}
        subset = {m: brief(v) for m, v in values.get("where_anchored", {}).items()}
        print(name, methods, "anchored", values["anchored_share"], "where anchored", subset)
    if not args.no_save:
        target = save_run(
            "panels",
            f"anchors-{PANEL_ANCHORS_VERSION.split('/')[-1]}",
            {"panel_dpi": PANEL_DPI, "ocr": f"{engine.name}-{engine.version}", "splits": splits},
            metrics,
            rows,
        )
        print(f"run saved to {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
