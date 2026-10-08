"""Summarize the human reviews made in the app (Stage 5).

Reference boxes (data/sfi48/reviews/boxes.json):
- progress over the figures the automatic reference left ``needs_manual``, per split;
- decisions, and agreement where two annotators reviewed the same figure (same
  decision; IoU of their boxes, target median >= 0.90 in research/experiments.md).

Explanation claims (data/sfi48/reviews/claims.json), over fully scored claims, for
human reviewers and, separately, for another AI used as judge:
- mean score of each rubric criterion (0-2);
- unsupported-claim rate: support = 0, overall and for high-confidence claims
  (gate <= 0.02 in docs/EVALUATION_PLAN.md);
- citation precision: citation = 2 among claims with a text or caption citation
  (gate >= 0.95);
- critical errors, and explanations invalidated by at least one.

Citation completeness and answerability need annotations the rubric does not collect
(the sources each claim should cite; questions and answers) and are not computed.

Usage:
    python scripts/eval/review_summary.py [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

from sfi.review import RUBRIC, RUBRIC_VERSION, ReviewStore, box_iou, claim_is_scored, figure_key

ROOT = Path(__file__).resolve().parents[2]


def ratio(numerator: int, denominator: int) -> dict:
    return {"value": round(numerator / denominator, 3) if denominator else None, "n": denominator}


def box_summary(reference: dict, reviews: list[dict]) -> dict:
    by_figure: dict[tuple, list[dict]] = {}
    for review in reviews:
        by_figure.setdefault((review["pmcid"], review["figure"]), []).append(review)
    listed = {(a["pmcid"], figure_key(f)) for a in reference["articles"] for f in a["figures"]}
    pending: dict[str, list[int]] = {}
    for article in reference["articles"]:
        for figure in article["figures"]:
            if figure["review_status"] != "needs_manual":
                continue
            done = (article["pmcid"], figure_key(figure)) in by_figure
            counts = pending.setdefault(article["split"], [0, 0])
            counts[0] += done
            counts[1] += 1
    pairs = []
    for found in by_figure.values():
        for a, b in combinations(found, 2):
            same = a["decision"] == b["decision"]
            entry = {"same_decision": same}
            if same and a["decision"] == "box":
                entry["iou"] = box_iou(a["bbox"], b["bbox"]) if a["page"] == b["page"] else 0.0
            pairs.append(entry)
    ious = [p["iou"] for p in pairs if "iou" in p]
    return {
        "needs_manual_reviewed": {s: f"{d}/{t}" for s, (d, t) in sorted(pending.items())},
        "reviews": len(reviews),
        "figures_reviewed": len(by_figure),
        "added_figures": len(set(by_figure) - listed),
        "decisions": dict(Counter(r["decision"] for r in reviews)),
        "annotators": dict(Counter(r["annotator"] for r in reviews)),
        "double_annotated": sum(1 for found in by_figure.values() if len(found) > 1),
        "decision_agreement": ratio(sum(p["same_decision"] for p in pairs), len(pairs)),
        "median_iou": round(statistics.median(ious), 3) if ious else None,
    }


def claim_summary(reviews: list[dict]) -> dict:
    claims = [c for r in reviews for c in r["claims"] if claim_is_scored(c)]
    cited = [c for c in claims if c["scores"]["citation"] != "na"]
    high = [c for c in claims if c.get("confidence") == "high"]
    return {
        "explanations": len(reviews),
        "explanations_complete": sum(
            1 for r in reviews if all(claim_is_scored(c) for c in r["claims"])
        ),
        "claims_scored": len(claims),
        "mean_scores": {
            c.id: round(
                statistics.mean(x["scores"][c.id] for x in claims if x["scores"][c.id] != "na"), 2
            )
            if any(x["scores"][c.id] != "na" for x in claims)
            else None
            for c in RUBRIC
        },
        "unsupported_rate": ratio(sum(c["scores"]["support"] == 0 for c in claims), len(claims)),
        "unsupported_rate_high_confidence": ratio(
            sum(c["scores"]["support"] == 0 for c in high), len(high)
        ),
        "citation_precision": ratio(sum(c["scores"]["citation"] == 2 for c in cited), len(cited)),
        "critical_errors": dict(Counter(c["critical"] for c in claims if c.get("critical"))),
        "explanations_with_critical_error": sum(
            1 for r in reviews if any(c.get("critical") for c in r["claims"])
        ),
        "by_annotator": dict(Counter(r["annotator"] for r in reviews)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus-dir", type=Path, default=ROOT / "data/sfi48")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--save", action="store_true", help="record the run in evaluation/runs/")
    args = parser.parse_args()

    store = ReviewStore(args.corpus_dir / "reviews")
    reference = json.loads((args.corpus_dir / "expected_figures.json").read_text("utf-8"))
    report = {
        "reference_version": reference["version"],
        "boxes": box_summary(reference, store.box_reviews()),
        # Scores from another AI (import_judge_scores.py) are never mixed with human ones.
        "claims": claim_summary(
            [r for r in store.claim_reviews() if r.get("annotator_kind", "human") == "human"]
        ),
        "claims_llm_judge": claim_summary(
            [r for r in store.claim_reviews() if r.get("annotator_kind") == "llm"]
        ),
    }
    print(json.dumps(report, indent=1, ensure_ascii=False))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    if args.save:
        sys.path.insert(0, str(Path(__file__).parent))
        from runlog import save_run

        target = save_run("reviews", RUBRIC_VERSION, {}, report, [])
        print(f"run saved to {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
