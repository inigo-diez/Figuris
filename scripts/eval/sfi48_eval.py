"""Evaluate figure extraction and context retrieval on SFI-48 (experiment E01 / E04).

Compares the pipeline (no model calls) with the reference built from PMC data by
scripts/corpus/build_reference.py:

- figures: label recall/precision against the JATS figure list (or the reviewed
  ``expected_labels`` of scanned articles), page accuracy, box IoU and P/R/F1 at
  IoU >= 0.5 and >= 0.75 where the reference box exists;
- captions: association = extracted caption similar (>= 0.9) to the JATS caption;
- silent losses: reference figures neither found nor reported by a warning;
- panels (figures whose JATS caption names >= 2 panel letters): letters found in
  the PDF caption, share split into boxes (and how many needed merging pieces, the
  lower-confidence case), and sub-caption agreement (similarity >= 0.9 with the same
  panel's JATS text);
- panels against the human panel boxes (data/sfi48/reviews/panels.json), where they
  exist: AP at IoU >= 0.5 over panel boxes ranked by confidence, label accuracy of
  the system boxes that match a human box, panel-subcaption F1 (right box, right
  letter and right sub-caption) and panel count accuracy;
- context: Recall@5 = share of the in-text references to a figure (JATS ``<xref>``)
  whose sentence is among the passages selected for that figure. Each reference is
  located by the text just before (or after) it, so trimmed passages count when
  they keep the mention.

Boxes and pages are only scored against reliable reference boxes: located with a
good match (``auto``) or checked by a person in the review screen (``reviewed``,
data/sfi48/reviews/boxes.json). Figures a reviewer found absent from the PDF leave
the reference; ``needs_manual``, ``unclear`` and ``disputed`` boxes are not scored.

Metrics are given per split and stratum with 95% bootstrap intervals over articles.
The ``test`` split is frozen: it is only evaluated with --include-test, and every
such run is appended to data/sfi48/test_runs.log.

Usage:
    python scripts/eval/sfi48_eval.py [--splits dev,validation] [--json out.json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import random
import re
import statistics
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import pypdfium2 as pdfium

from sfi.context.mentions import find_mentions
from sfi.context.select import ContextConfig, select_context
from sfi.domain.models import BBox, Figure, FigureMention, Passage, PassageSegment
from sfi.extract.captions import normalize_label
from sfi.extract.extractor import PdfiumFigureExtractor
from sfi.extract.panels import CONFIDENCE_MERGED, parse_subcaptions
from sfi.extract.text import passages_from_extraction
from sfi.review import ReviewStore, figure_key, load_reference

sys.path.insert(0, str(Path(__file__).parent))
from runlog import save_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CAPTION_MATCH = 0.9
RELIABLE = ("auto", "reviewed")


def text_of(element) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def comparable(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", unicodedata.normalize("NFKC", text).lower())


def xref_snippets(xml_path: Path) -> dict[str, list[str]]:
    """For each figure id, a short text key around each in-text reference to it."""
    root = ET.parse(xml_path).getroot()
    body = root.find(".//body")
    snippets: dict[str, list[str]] = {}

    def walk(element, parts, refs):
        if element.tag == "xref" and element.get("ref-type") == "fig":
            start = sum(len(p) for p in parts)
            parts.append("".join(element.itertext()))
            for rid in (element.get("rid") or "").split():
                refs.append((rid, start, start + len(parts[-1])))
        else:
            parts.append(element.text or "")
            for child in element:
                walk(child, parts, refs)
                parts.append(child.tail or "")

    for paragraph in body.iter("p") if body is not None else []:
        parts, refs = [], []
        walk(paragraph, parts, refs)
        text = "".join(parts)
        for rid, start, end in refs:
            before = comparable(text[max(0, start - 120) : start])[-30:]
            key = before if len(before) >= 15 else comparable(text[end : end + 120])[:30]
            if len(key) >= 15:
                snippets.setdefault(rid, []).append(key)
    return snippets


def strip_label(text: str) -> str:
    return re.sub(
        r"^\s*(extended data\s+|supplementary\s+)?(figure|fig\.?|scheme)\s*\S+?[\s.:|]+",
        "",
        text,
        flags=re.IGNORECASE,
    )


def iou(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def subcaption_map(caption: str) -> dict[str, str]:
    return {label: sub.text for sub in parse_subcaptions(caption)[1] for label in sub.labels}


def jats_captions(xml_path: Path) -> dict[str, str]:
    root = ET.parse(xml_path).getroot()
    # Equations appear twice (LaTeX source and rendered text): keep only the rendered text.
    parents = {child: parent for parent in root.iter() for child in parent}
    for tex in list(root.iter("tex-math")):
        parent = parents.get(tex)
        if parent is not None:
            parent.remove(tex)
    return {
        normalize_label(text_of(f.find("label"))): text_of(f.find("caption"))
        for f in root.iter("fig")
        if f.find("label") is not None
    }


def as_passages(text_passages, layouts) -> list[Passage]:
    """Minimal Passage objects so the production context selection can be reused."""
    out = []
    for p in text_passages:
        page = layouts[p.page_index]
        box = BBox(left=0, bottom=0, right=page.width, top=page.height)
        out.append(
            Passage(
                id=f"psg_{p.ordinal}",
                document_id="eval",
                run_id="eval",
                ordinal=p.ordinal,
                page_index=p.page_index,
                section=p.section,
                back_matter=p.back_matter,
                text=p.text,
                segments=[
                    PassageSegment(
                        page_index=s.page_index,
                        char_start=s.char_start,
                        bbox=box,
                        bbox_normalized=(0, 0, 1, 1),
                    )
                    for s in p.segments
                ],
                mentions=[
                    FigureMention(
                        label=m.label, panels=m.panels, start=m.start, end=m.end, text=m.text
                    )
                    for m in find_mentions(p.text)
                ],
                producer="eval",
                producer_version="0",
            )
        )
    return out


def panel_gold_row(gold: dict, got, page_size, jats_panels: dict[str, str]) -> dict:
    width, height = page_size
    system = [
        {
            "label": p.label,
            "box": [p.box.x0 / width, p.box.y0 / height, p.box.x1 / width, p.box.y1 / height],
            "confidence": p.confidence,
            "subcaption_ok": difflib.SequenceMatcher(
                None,
                comparable(p.subcaption),
                comparable(jats_panels.get(p.label, "")),
                autojunk=False,
            ).ratio()
            >= CAPTION_MATCH,
        }
        for p in got.panels
        if p.box is not None
    ]
    return {
        "gold": {p["label"]: p["bbox"] for p in gold["panels"] if p["bbox"]},
        "system": system,
    }


def evaluate_article(
    reference: dict, raw_dir: Path, extractor, panel_gold: dict | None = None
) -> dict:
    pmcid = reference["pmcid"]
    pdf = pdfium.PdfDocument(raw_dir / f"{pmcid}.pdf")
    started = time.perf_counter()
    result = extractor.extract(pdf)
    seconds = time.perf_counter() - started
    passages = as_passages(passages_from_extraction(result), result.pages)
    page_sizes = [(layout.width, layout.height) for layout in result.pages]
    pdf.close()
    captions = jats_captions(raw_dir / f"{pmcid}.xml")
    snippets = xref_snippets(raw_dir / f"{pmcid}.xml")
    all_text = [comparable(p.text) for p in passages if not p.back_matter]
    unlabelled = [f for f in result.figures if f.label is None and f.box is not None]

    found = {}
    for figure in result.figures:
        if figure.label and figure.kind != "table":
            found.setdefault(figure.label, figure)
    warned = {w.figure_label for w in result.warnings if w.figure_label}
    warned |= {
        label
        for w in result.warnings
        if w.code.value == "missing_in_sequence"
        for label in re.findall(r"(?:Figure|Scheme) \S+", w.message)
    }
    ref_labels = [f["label"] for f in reference["figures"] if f["label"]]
    rows = []
    for ref in reference["figures"]:
        label = ref["label"]
        got = found.get(label)
        if label is None and ref["bbox"]:  # unlabelled in the JATS: match by position
            for candidate in unlabelled:
                width, height = page_sizes[candidate.page_index]
                box = (
                    candidate.box.x0 / width,
                    candidate.box.y0 / height,
                    candidate.box.x1 / width,
                    candidate.box.y1 / height,
                )
                if candidate.page_index + 1 == ref["page"] and iou(box, ref["bbox"]) >= 0.5:
                    got = candidate
                    unlabelled.remove(candidate)
                    break
        row = {"label": label, "found": got is not None, "status": ref["review_status"]}
        reliable = ref["review_status"] in RELIABLE
        if got is not None:
            if reliable:
                row["page_ok"] = got.page_index + 1 == ref["page"]
            if (
                reliable
                and ref["bbox"]
                and got.box is not None
                and got.page_index + 1 == ref["page"]
            ):
                width, height = page_sizes[got.page_index]
                box = (
                    got.box.x0 / width,
                    got.box.y0 / height,
                    got.box.x1 / width,
                    got.box.y1 / height,
                )
                row["iou"] = round(iou(box, ref["bbox"]), 3)
            elif reliable and ref["bbox"]:
                row["iou"] = 0.0
            gold = captions.get(label, "")
            gold_panels = subcaption_map(gold)
            if len(gold_panels) >= 2:
                panels = {p.label: p for p in got.panels}
                row["panels"] = {
                    "expected": len(gold_panels),
                    "letters_found": sum(1 for x in gold_panels if x in panels),
                    "layout": got.panel_layout,
                    "merged": any(p.confidence == CONFIDENCE_MERGED for p in got.panels),
                    "subcaption_match": sum(
                        1
                        for x, text in gold_panels.items()
                        if x in panels
                        and difflib.SequenceMatcher(
                            None, comparable(panels[x].subcaption), comparable(text), autojunk=False
                        ).ratio()
                        >= CAPTION_MATCH
                    ),
                }
            human = (panel_gold or {}).get(figure_key(ref)) if ref.get("label") else None
            if human and human["decision"] == "done":
                row["panel_gold"] = panel_gold_row(
                    human, got, page_sizes[got.page_index], gold_panels
                )
            if got.caption and gold:
                row["caption_similarity"] = round(
                    difflib.SequenceMatcher(
                        None,
                        comparable(strip_label(got.caption.text)),
                        comparable(gold),
                        autojunk=False,
                    ).ratio(),
                    3,
                )
            # Context recall: in-text references kept in the passages selected for the figure.
            keys = snippets.get(ref.get("jats_id") or "", [])
            if keys and label:
                stub = Figure(
                    id="f",
                    document_id="eval",
                    run_id="eval",
                    label=label,
                    page_index=got.page_index,
                    bbox=None,
                    status="ok",
                    confidence=1,
                    producer="eval",
                    producer_version="0",
                )
                context = select_context(stub, passages, ContextConfig())
                selected = [comparable(p.text) for p in context.passages[:5]]
                hits = sum(1 for key in keys if any(key in text for text in selected))
                in_text = sum(1 for key in keys if any(key in text for text in all_text))
                row["context_recall"] = round(hits / len(keys), 3)
                # Diagnosis: references whose sentence is in the extracted text at all.
                row["mentions_in_text"] = round(in_text / len(keys), 3)
        else:
            row["warned"] = label in warned
        rows.append(row)
    spurious = sorted(
        label
        for label in found
        if label not in ref_labels and not label.startswith("Supplementary")
    )
    unlabelled_left = len(unlabelled)
    return {
        "pmcid": pmcid,
        "split": reference["split"],
        "stratum": reference.get("stratum"),
        "pages": len(page_sizes),
        "seconds": round(seconds, 2),
        "figures": rows,
        "spurious_labels": spurious,
        "unlabelled_regions": unlabelled_left,
    }


def bootstrap(per_article: list[tuple[float, float]], rounds: int = 1000) -> tuple[float, float]:
    """95% interval of a ratio (sum of numerators / sum of denominators) over articles."""
    if not per_article:
        return (0.0, 0.0)
    rng = random.Random(7)
    values = []
    for _ in range(rounds):
        sample = [rng.choice(per_article) for _ in per_article]
        denominator = sum(d for _, d in sample)
        values.append(sum(n for n, _ in sample) / denominator if denominator else 0.0)
    values.sort()
    return values[int(0.025 * rounds)], values[int(0.975 * rounds) - 1]


def metric(articles: list[dict], numerator, denominator) -> dict:
    pairs = [(numerator(a), denominator(a)) for a in articles]
    total_n, total_d = sum(n for n, _ in pairs), sum(d for _, d in pairs)
    low, high = bootstrap([p for p in pairs if p[1]])
    return {
        "value": round(total_n / total_d, 3) if total_d else None,
        "n": total_d,
        "ci95": [round(low, 3), round(high, 3)],
    }


def average_precision(scored: list[tuple[float, bool]], positives: int) -> float | None:
    """All-point interpolated AP of detections (confidence, is true positive)."""
    if not positives:
        return None
    scored = sorted(scored, key=lambda x: -x[0])
    points, hits = [], 0
    for rank, (_, hit) in enumerate(scored, start=1):
        hits += hit
        points.append((hits / positives, hits / rank))
    ap, previous_recall = 0.0, 0.0
    for i, (recall, _) in enumerate(points):
        precision = max(p for _, p in points[i:])
        ap += (recall - previous_recall) * precision
        previous_recall = recall
    return round(ap, 3)


def panel_gold_metrics(rows: list[dict]) -> dict:
    scored, positives, label_hits, matched, linked, system_total, counts = [], 0, 0, 0, 0, 0, 0
    for row in rows:
        gold, system = row["gold"], row["system"]
        positives += len(gold)
        system_total += len(system)
        counts += len(system) == len(gold)
        free = dict(gold)
        for panel in sorted(system, key=lambda p: -p["confidence"]):
            best = max(free.items(), key=lambda kv: iou(panel["box"], kv[1]), default=None)
            hit = best is not None and iou(panel["box"], best[1]) >= 0.5
            scored.append((panel["confidence"], hit))
            if hit:
                matched += 1
                label_hits += best[0] == panel["label"]
                free.pop(best[0])
            same = gold.get(panel["label"])
            linked += bool(same and iou(panel["box"], same) >= 0.5 and panel["subcaption_ok"])
    precision = linked / system_total if system_total else 0.0
    recall = linked / positives if positives else 0.0
    return {
        "figures": len(rows),
        "gold_panels": positives,
        "ap50": average_precision(scored, positives),
        "label_accuracy": ratio_of(label_hits, matched),
        "panel_subcaption_f1": round(2 * precision * recall / (precision + recall), 3)
        if precision + recall
        else 0.0,
        "count_accuracy": ratio_of(counts, len(rows)),
    }


def ratio_of(numerator: int, denominator: int) -> dict:
    return {"value": round(numerator / denominator, 3) if denominator else None, "n": denominator}


def summarize(articles: list[dict]) -> dict:
    def figs(a, cond=lambda r: True):
        return [r for r in a["figures"] if cond(r)]

    def boxed(r):
        return "iou" in r or (not r["found"] and r["status"] in RELIABLE and r["label"] is not None)

    def iou_hits(threshold):
        return lambda a: sum(1 for r in figs(a) if r.get("iou", 0) >= threshold)

    def predicted(a):
        found = sum(1 for r in figs(a) if r["found"])
        return found + len(a["spurious_labels"]) + a["unlabelled_regions"]

    recall = metric(
        articles, lambda a: sum(1 for r in figs(a) if r["found"]), lambda a: len(figs(a))
    )
    precision = metric(articles, lambda a: sum(1 for r in figs(a) if r["found"]), predicted)
    out = {
        "articles": len(articles),
        "figures": sum(len(a["figures"]) for a in articles),
        "label_recall": recall,
        "label_precision": precision,
        "page_accuracy": metric(
            articles,
            lambda a: sum(1 for r in figs(a, lambda r: "page_ok" in r) if r["page_ok"]),
            lambda a: len(figs(a, lambda r: "page_ok" in r)),
        ),
        "box_recall_iou50": metric(articles, iou_hits(0.5), lambda a: len(figs(a, boxed))),
        "box_recall_iou75": metric(articles, iou_hits(0.75), lambda a: len(figs(a, boxed))),
        "box_precision_iou50": metric(
            # Predictions scored against reliable reference boxes, plus unmatched ones.
            articles,
            iou_hits(0.5),
            lambda a: (
                len(figs(a, lambda r: "iou" in r))
                + len(a["spurious_labels"])
                + a["unlabelled_regions"]
            ),
        ),
        "caption_association": metric(
            articles,
            lambda a: sum(1 for r in figs(a) if r.get("caption_similarity", 0) >= CAPTION_MATCH),
            lambda a: len(figs(a, lambda r: "caption_similarity" in r or not r["found"])),
        ),
        "silent_losses": sum(
            1 for a in articles for r in figs(a) if not r["found"] and not r.get("warned")
        ),
        "context_recall_at5": metric(
            articles,
            lambda a: sum(r["context_recall"] for r in figs(a, lambda r: "context_recall" in r)),
            lambda a: len(figs(a, lambda r: "context_recall" in r)),
        ),
        "median_iou": round(
            statistics.median(
                [r["iou"] for a in articles for r in figs(a, lambda r: "iou" in r)] or [0]
            ),
            3,
        ),
        "seconds_per_page": round(
            sum(a["seconds"] for a in articles) / max(1, sum(a["pages"] for a in articles)), 3
        ),
    }
    multipanel = [r["panels"] for a in articles for r in figs(a) if "panels" in r]
    split = [x for x in multipanel if x["layout"] == "split"]
    out["panels"] = {
        "multipanel_figures": len(multipanel),
        "letters_found": ratio_of(
            sum(x["letters_found"] for x in multipanel), sum(x["expected"] for x in multipanel)
        ),
        "split_share": ratio_of(len(split), len(multipanel)),
        "split_after_merging": ratio_of(sum(x["merged"] for x in split), len(split)),
        "subcaption_match": ratio_of(
            sum(x["subcaption_match"] for x in multipanel), sum(x["expected"] for x in multipanel)
        ),
        "against_human_boxes": panel_gold_metrics(
            [r["panel_gold"] for a in articles for r in figs(a) if "panel_gold" in r]
        ),
    }
    p, r = precision["value"] or 0, recall["value"] or 0
    out["label_f1"] = round(2 * p * r / (p + r), 3) if p + r else 0.0
    bp, br = out["box_precision_iou50"]["value"] or 0, out["box_recall_iou50"]["value"] or 0
    out["box_f1_iou50"] = round(2 * bp * br / (bp + br), 3) if bp + br else 0.0
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus-dir", type=Path, default=ROOT / "data/sfi48")
    parser.add_argument(
        "--no-reviews",
        action="store_true",
        help="ignore the human box reviews (automatic reference)",
    )
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/sfi48")
    parser.add_argument("--splits", default="dev,validation")
    parser.add_argument(
        "--include-test", action="store_true", help="also evaluate the frozen test split"
    )
    parser.add_argument("--json", type=Path)
    parser.add_argument(
        "--no-save", action="store_true", help="do not record the run in evaluation/runs/"
    )
    args = parser.parse_args()

    splits = set(args.splits.split(","))
    if args.include_test:
        splits.add("test")
        log = ROOT / "data/sfi48/test_runs.log"
        with log.open("a", encoding="utf-8") as handle:
            handle.write(
                f"{dt.datetime.now(dt.UTC).isoformat(timespec='seconds')} sfi48_eval --include-test\n"
            )
    elif "test" in splits:
        print("The test split is frozen: use --include-test explicitly.", file=sys.stderr)
        return 2

    reference = load_reference(args.corpus_dir, reviewed=not args.no_reviews)
    panel_gold: dict[str, dict[str, dict]] = {}
    for review in sorted(
        ReviewStore(args.corpus_dir / "reviews").panel_reviews(), key=lambda r: r["reviewed_at"]
    ):  # one annotator per figure for now: the first review is used
        panel_gold.setdefault(review["pmcid"], {}).setdefault(review["figure"], review)
    extractor = PdfiumFigureExtractor()
    articles = []
    for ref in reference["articles"]:
        if ref["split"] not in splits:
            continue
        article = evaluate_article(ref, args.raw_dir, extractor, panel_gold.get(ref["pmcid"]))
        found = sum(r["found"] for r in article["figures"])
        ious = [r["iou"] for r in article["figures"] if "iou" in r]
        print(
            f"{article['pmcid']:<12} {article['split']:<10} {article['stratum'] or '':<38} "
            f"found {found}/{len(article['figures'])} spurious={len(article['spurious_labels'])} "
            f"unlabelled={article['unlabelled_regions']} "
            f"iou_med={statistics.median(ious) if ious else float('nan'):.2f}"
        )
        articles.append(article)

    report = {
        "reference_version": reference["version"],
        "reference_summary": reference["summary"],
        "box_reviews_applied": (reference.get("box_reviews") or {}).get("applied", 0),
        "extractor": {"name": extractor.name, "version": extractor.version},
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "overall": summarize(articles),
        "by_split": {
            s: summarize([a for a in articles if a["split"] == s]) for s in sorted(splits)
        },
        "by_stratum": {
            s: summarize([a for a in articles if (a["stratum"] or "pilot").split("/")[0] == s])
            for s in sorted({(a["stratum"] or "pilot").split("/")[0] for a in articles})
        },
        "articles": articles,
    }
    overall = report["overall"]
    print("\noverall:", json.dumps({k: v for k, v in overall.items()}, ensure_ascii=False))
    for stratum, values in report["by_stratum"].items():
        print(
            f"  {stratum:<30} label_f1={values['label_f1']} box_f1@50={values['box_f1_iou50']} "
            f"caption={values['caption_association']['value']} ctx@5={values['context_recall_at5']['value']} "
            f"panels_split={values['panels']['split_share']['value']}"
        )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    if not args.no_save:
        target = save_run(
            "sfi48",
            extractor.version,
            {"extractor": extractor.name, **extractor.config(), "splits": sorted(splits)},
            {k: v for k, v in report.items() if k != "articles"},
            articles,
            {
                "reference_version": reference["version"],
                "box_reviews_applied": report["box_reviews_applied"],
                "panel_reviews": sum(len(v) for v in panel_gold.values()),
            },
        )
        print(f"run saved to {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
