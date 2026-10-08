"""Evaluate Stage 2 figure explanations on the SFI-12 pilot.

Reads the latest analysis of every extracted figure from the local database
(run ``sfi process``/``sfi analyze`` first; this script never calls the model).

Automatic metrics: status, validation issues, claim types, tokens, cost and
latency. Semantic quality cannot be scored automatically yet: for the
hand-annotated figures in expected_results.json the script writes a review
sheet that puts the expected items (must observe, author stated, must mark
uncertain, must not claim) next to the model's claims for manual judgement.

Usage:
    python scripts/eval/stage2_eval.py [--review data/local/eval/stage2_review.md]
                                       [--json data/local/eval/stage2.json]
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
from pathlib import Path

from sfi.analysis.schema import FigureAnalysis
from sfi.config import Settings
from sfi.extract.captions import normalize_label
from sfi.storage.repository import SQLiteRepository

ROOT = Path(__file__).resolve().parents[2]
TYPE_NAMES = {
    "observed": "observado",
    "author_stated": "según el pie",
    "model_inference": "inferencia",
    "uncertain": "incierto",
}


def latest_analyses(repository: SQLiteRepository) -> list[tuple[str, object, FigureAnalysis]]:
    rows = []
    for document in repository.find_documents():
        run = repository.latest_completed_run(document.id)
        if not run:
            continue
        pmcid = Path(document.filename).stem
        for figure in repository.list_figures(run.id):
            analysis = repository.latest_analysis(figure.id)
            if analysis:
                rows.append((pmcid, figure, analysis))
    return rows


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def evaluate(rows) -> dict:
    statuses = collections.Counter(a.status.value for _, _, a in rows)
    issues = collections.Counter(f"{i.code} ({i.severity})" for _, _, a in rows for i in a.issues)
    explained = [a for _, _, a in rows if a.explanation]
    claim_types = collections.Counter(c.type for a in explained for c in a.explanation.claims)
    claims_per_figure = [len(a.explanation.claims) for a in explained]
    # Spend and latency of the calls behind the results shown (not reused copies).
    runs = [a.run for _, _, a in rows if a.run]
    return {
        "figures": len(rows),
        "status": dict(statuses),
        "issues": dict(issues),
        "claims": {
            "total": sum(claims_per_figure),
            "per_figure_mean": round(statistics.mean(claims_per_figure), 1),
            "per_figure_range": [min(claims_per_figure), max(claims_per_figure)],
            "by_type": dict(claim_types),
            "figures_with_limitations": sum(1 for a in explained if a.explanation.limitations),
            "figures_with_author_stated": sum(
                1 for a in explained if any(c.type == "author_stated" for c in a.explanation.claims)
            ),
        },
        "tokens": {
            "input_mean": round(statistics.mean(r.input_tokens for r in runs)),
            "output_mean": round(statistics.mean(r.output_tokens for r in runs)),
            "output_max": max(r.output_tokens for r in runs),
            "reasoning_mean": round(statistics.mean(r.reasoning_tokens for r in runs)),
            "cached_input_share": round(
                sum(r.cached_input_tokens for r in runs) / sum(r.input_tokens for r in runs), 2
            ),
        },
        "cost_usd": {
            "results_shown": round(sum(r.estimated_cost_usd for r in runs), 4),
            "per_figure_mean": round(statistics.mean(r.estimated_cost_usd for r in runs), 5),
        },
        "latency_s": {
            "p50": round(percentile([r.latency_ms / 1000 for r in runs], 0.5), 1),
            "p90": round(percentile([r.latency_ms / 1000 for r in runs], 0.9), 1),
            "max": round(max(r.latency_ms for r in runs) / 1000, 1),
        },
        "models": dict(collections.Counter(r.model_version or r.model for r in runs)),
    }


def review_sheet(rows, expected_path: Path) -> str:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    index = {(pmcid, normalize_label(f.label or "")): a for pmcid, f, a in rows}
    out = [
        "# Etapa 2 — hoja de revisión de explicaciones",
        "",
        "Generada por scripts/eval/stage2_eval.py. Compara cada figura anotada a mano con",
        "las afirmaciones del modelo. Marcar cada elemento esperado como cubierto, parcial o ausente.",
        "",
    ]
    for item in expected["figures"]:
        analysis = index.get((item["pmcid"], normalize_label(item["label"])))
        out += [f"## {item['id']} — {item['label']} (p. {item['page']})", ""]
        if analysis is None or analysis.explanation is None:
            out += ["**Sin explicación.**", ""]
            continue
        spec = item["analysis"]
        for title, key in (
            ("Debe observar", "must_observe"),
            ("Según los autores", "author_stated"),
            ("Debe marcar como incierto", "must_mark_uncertain"),
            ("No debe afirmar", "must_not_claim"),
        ):
            out.append(f"**{title}**")
            out += [f"- [ ] {text}" for text in spec.get(key, [])] or ["- (ninguno)"]
            out.append("")
        explanation = analysis.explanation
        out += [
            f"**Modelo** — estado `{analysis.status.value}`, "
            f"{len(explanation.claims)} afirmaciones",
            "",
            f"> {explanation.summary}",
            "",
        ]
        for claim in explanation.claims:
            quotes = [e.quote for e in claim.evidence if e.quote]
            panels = f" [{', '.join(claim.panels)}]" if claim.panels else ""
            approx = " (aprox.)" if claim.approximate else ""
            out.append(
                f"- `{claim.id}` *{TYPE_NAMES[claim.type]}*{panels}{approx}: {claim.text}"
                + (f" — cita: «{' … '.join(quotes)}»" if quotes else "")
            )
        out += ["", f"Interpretación: {explanation.interpretation.text}", ""]
        for issue in analysis.issues:
            out.append(f"- ⚠ `{issue.code}` ({issue.severity}): {issue.message}")
        out.append("")
    return "\n".join(out)


def summarize(report: dict) -> str:
    lines = [
        f"figures analysed: {report['figures']}  status: {report['status']}",
        f"issues: {report['issues'] or 'none'}",
        "claims: {total} ({per_figure_mean}/figure, range {per_figure_range}) "
        "by type {by_type}".format(**report["claims"]),
        f"figures with limitations: {report['claims']['figures_with_limitations']}, "
        f"with author_stated claims: {report['claims']['figures_with_author_stated']}",
        f"tokens: {report['tokens']}",
        f"cost: {report['cost_usd']}  latency: {report['latency_s']}  models: {report['models']}",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--expected", type=Path, default=ROOT / "data/stage0/expected_results.json")
    parser.add_argument("--review", type=Path, default=ROOT / "data/local/eval/stage2_review.md")
    parser.add_argument("--json", type=Path, help="also write the metrics as JSON")
    args = parser.parse_args()

    settings = Settings.from_env()
    repository = SQLiteRepository(settings.database_path)
    rows = latest_analyses(repository)
    if not rows:
        print("No analyses found: run `sfi process` or `sfi analyze` first.")
        return 1
    report = evaluate(rows)
    print(summarize(report))
    args.review.parent.mkdir(parents=True, exist_ok=True)
    args.review.write_text(review_sheet(rows, args.expected), encoding="utf-8")
    print(f"review sheet: {args.review}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
