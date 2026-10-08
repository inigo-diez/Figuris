"""Evaluate Stage 3 (article context and evidence) on the SFI-12 pilot.

Reads the stored passages and analyses (run ``sfi process``/``sfi analyze`` first;
this script never calls the model).

- Mentions: compares the figure mentions found in the extracted text with the
  ``<xref ref-type="fig">`` references of the JATS body (PMC), which mark every
  in-text reference to a figure. JATS counts panel references separately
  ("Fig. 2a, c" is two xrefs), so mention counts are a lower bound.
- Context: figures that received at least one passage.
- Traceability: main findings whose evidence resolves to the figure, a literal
  caption quote or a literal passage quote located on a page.
- Review sheet: for the hand-annotated figures, expected items next to the
  model's claims with the source and page of every quote.

Usage:
    python scripts/eval/stage3_eval.py [--review data/local/eval/stage3_review.md]
                                       [--json data/local/eval/stage3.json]
"""

from __future__ import annotations

import argparse
import collections
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from sfi.analysis.schema import AnalysisStatus, FigureAnalysis
from sfi.config import Settings
from sfi.extract.captions import normalize_label
from sfi.storage.repository import SQLiteRepository

ROOT = Path(__file__).resolve().parents[2]
TYPE_NAMES = {
    "observed": "observado",
    "author_stated": "según los autores",
    "model_inference": "inferencia",
    "uncertain": "incierto",
}


def jats_mentions(xml_path: Path) -> collections.Counter:
    root = ET.parse(xml_path).getroot()
    labels = {}
    for fig in root.iter("fig"):
        label = fig.find("label")
        if label is not None and fig.get("id"):
            labels[fig.get("id")] = normalize_label(" ".join("".join(label.itertext()).split()))
    counts: collections.Counter = collections.Counter()
    body = root.find(".//body")
    for xref in body.iter("xref") if body is not None else []:
        if xref.get("ref-type") == "fig":
            for rid in (xref.get("rid") or "").split():
                if labels.get(rid):
                    counts[labels[rid]] += 1
    return counts


def traceable(analysis: FigureAnalysis, claim_id: str) -> bool:
    """A finding is traceable if some evidence item resolves without a validation error."""
    claim = next((c for c in analysis.explanation.claims if c.id == claim_id), None)
    if claim is None:
        return False
    bad = {
        i.claim_id
        for i in analysis.issues
        if i.severity == "error" and i.code.startswith(("quote_", "unknown_passage"))
    }
    spans = {(s.claim_id, s.evidence_index) for s in analysis.spans}
    for index, evidence in enumerate(claim.evidence):
        if evidence.kind == "figure_region":
            return True
        if evidence.kind == "caption" and evidence.quote and claim.id not in bad:
            return True
        if evidence.kind == "text_span" and (claim.id, index) in spans:
            return True
    return False


def evaluate(repository: SQLiteRepository, raw_dir: Path) -> tuple[dict, list]:
    mentions = collections.Counter()
    per_article = []
    rows = []
    for document in repository.find_documents():
        run = repository.latest_completed_run(document.id)
        if not run:
            continue
        pmcid = Path(document.filename).stem
        passages = repository.list_passages(run.id)
        found = collections.Counter(
            m.label for p in passages if not p.back_matter for m in p.mentions
        )
        xml = raw_dir / f"{pmcid}.xml"
        expected = jats_mentions(xml) if xml.exists() else collections.Counter()
        covered = [label for label in expected if found[label]]
        mentions["figures_in_jats"] += len(expected)
        mentions["figures_found"] += len(covered)
        mentions["jats_xrefs"] += sum(expected.values())
        mentions["found_for_those"] += sum(min(found[label], expected[label]) for label in expected)
        per_article.append(
            {
                "article": pmcid,
                "passages": len(passages),
                "jats_figures": len(expected),
                "figures_found": len(covered),
                "missing": sorted(set(expected) - set(covered)),
            }
        )
        for figure in repository.list_figures(run.id):
            analysis = repository.latest_analysis(figure.id)
            if analysis:
                rows.append((pmcid, figure, analysis))

    explained = [a for _, _, a in rows if a.explanation]
    findings = [(a, cid) for a in explained for cid in a.explanation.main_findings]
    evidence_kinds = collections.Counter(
        e.kind for a in explained for c in a.explanation.claims for e in c.evidence
    )
    text_quotes = evidence_kinds["text_span"]
    runs = [a.run for _, _, a in rows if a.run]
    report = {
        "mentions": {
            **mentions,
            "figure_recall": round(mentions["figures_found"] / mentions["figures_in_jats"], 3),
            "xref_recall_lower_bound": round(
                mentions["found_for_those"] / mentions["jats_xrefs"], 3
            ),
        },
        "figures": len(rows),
        "status": dict(collections.Counter(a.status.value for _, _, a in rows)),
        "issues": dict(
            collections.Counter(f"{i.code} ({i.severity})" for _, _, a in rows for i in a.issues)
        ),
        "context": {
            "figures_with_context": sum(1 for _, _, a in rows if a.context),
            "passages_mean": round(sum(len(a.context) for _, _, a in rows) / len(rows), 2),
            "chars_mean": round(
                sum(len(p.text) for _, _, a in rows for p in a.context) / len(rows)
            ),
        },
        "evidence": {
            "by_kind": dict(evidence_kinds),
            "text_quotes_located": sum(len(a.spans) for a in explained),
            "text_quotes": text_quotes,
            "figures_citing_text": sum(
                1
                for a in explained
                if any(e.kind == "text_span" for c in a.explanation.claims for e in c.evidence)
            ),
            "claims_by_type": dict(
                collections.Counter(c.type for a in explained for c in a.explanation.claims)
            ),
        },
        "traceability": {
            "main_findings": len(findings),
            "traceable": sum(1 for a, cid in findings if traceable(a, cid)),
            "role_in_article_filled": sum(
                1 for a in explained if a.explanation.role_in_article.text.strip()
            ),
        },
        "cost_usd": round(sum(r.estimated_cost_usd for r in runs), 4),
        "tokens_input_mean": round(sum(r.input_tokens for r in runs) / len(runs)),
        "tokens_output_mean": round(sum(r.output_tokens for r in runs) / len(runs)),
        "per_article": per_article,
    }
    report["traceability"]["share"] = round(
        report["traceability"]["traceable"] / max(1, len(findings)), 3
    )
    return report, rows


def _quote_source(analysis: FigureAnalysis, claim_id: str, index: int, kind: str) -> str:
    if kind == "caption":
        return "pie"
    span = next(
        (s for s in analysis.spans if s.claim_id == claim_id and s.evidence_index == index), None
    )
    if span is None:
        return "texto, cita no encontrada"
    return f"texto {span.ref}, p. {span.page}" + (f", {span.section}" if span.section else "")


def review_sheet(rows, expected_path: Path) -> str:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    index = {(pmcid, normalize_label(f.label or "")): a for pmcid, f, a in rows}
    out = [
        "# Etapa 3 — hoja de revisión de explicaciones con contexto",
        "",
        "Generada por scripts/eval/stage3_eval.py. Cada cita indica su fuente (pie o pasaje",
        "del texto con página). Marcar cada elemento esperado como cubierto, parcial o ausente.",
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
        context = ", ".join(f"{p.ref} (p. {p.page})" for p in analysis.context) or "ninguno"
        out += [
            f"**Modelo** — estado `{analysis.status.value}`, {len(explanation.claims)} "
            f"afirmaciones; pasajes enviados: {context}",
            "",
            f"> {explanation.summary}",
            "",
        ]
        for claim in explanation.claims:
            quotes = [
                f"«{e.quote}» ({_quote_source(analysis, claim.id, i, e.kind)})"
                for i, e in enumerate(claim.evidence)
                if e.quote
            ]
            panels = f" [{', '.join(claim.panels)}]" if claim.panels else ""
            approx = " (aprox.)" if claim.approximate else ""
            out.append(
                f"- `{claim.id}` *{TYPE_NAMES[claim.type]}*{panels}{approx}: {claim.text}"
                + (f" — {' · '.join(quotes)}" if quotes else "")
            )
        out += [
            "",
            f"Interpretación: {explanation.interpretation.text}",
            "",
            f"Papel en el artículo: {explanation.role_in_article.text}",
            "",
        ]
        for issue in analysis.issues:
            out.append(f"- ⚠ `{issue.code}` ({issue.severity}): {issue.message}")
        out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/stage0")
    parser.add_argument("--expected", type=Path, default=ROOT / "data/stage0/expected_results.json")
    parser.add_argument("--review", type=Path, default=ROOT / "data/local/eval/stage3_review.md")
    parser.add_argument("--json", type=Path, help="also write the metrics as JSON")
    args = parser.parse_args()

    settings = Settings.from_env()
    repository = SQLiteRepository(settings.database_path)
    report, rows = evaluate(repository, args.raw_dir)
    if not rows:
        print("No analyses found: run `sfi process` or `sfi analyze` first.")
        return 1
    for key in ("mentions", "status", "issues", "context", "evidence", "traceability"):
        print(f"{key}: {report[key]}")
    print(
        f"cost: {report['cost_usd']} USD  tokens in/out: "
        f"{report['tokens_input_mean']}/{report['tokens_output_mean']}"
    )
    for article in report["per_article"]:
        if article["missing"]:
            print(f"  {article['article']}: figures without detected mentions {article['missing']}")
    ok = sum(1 for _, _, a in rows if a.status == AnalysisStatus.OK)
    print(f"valid explanations: {ok}/{len(rows)}")
    args.review.parent.mkdir(parents=True, exist_ok=True)
    args.review.write_text(review_sheet(rows, args.expected), encoding="utf-8")
    print(f"review sheet: {args.review}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
