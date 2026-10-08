"""Evaluate Stage 1 figure extraction on the SFI-12 pilot.

Ground truth:
- figure labels and caption text from each article's JATS XML (PMC);
- ``expected_labels`` overrides in expected_results.json where JATS is
  incomplete (scanned articles);
- pages of the hand-annotated figures in expected_results.json.

Region geometry has no gold boxes yet: crops are checked visually (see the
HTML report) and gold boxes are planned for SFI-48 (experiment E01).

Usage:
    python scripts/eval/stage1_eval.py [--json data/local/eval/stage1.json]
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pypdfium2 as pdfium

from sfi.extract.captions import normalize_label
from sfi.extract.extractor import PdfiumFigureExtractor

ROOT = Path(__file__).resolve().parents[2]
CAPTION_MATCH = 0.9


def text_of(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def comparable(text: str) -> str:
    """Lowercase alphanumerics only: ignores spacing, punctuation and glyph encoding noise."""
    return re.sub(r"[^0-9a-z]+", "", text.lower())


def strip_label(text: str) -> str:
    return re.sub(
        r"^\s*(extended data\s+|supplementary\s+)?(figure|fig\.?|scheme|table)\s*\S+?[\s.:|]+",
        "",
        text,
        flags=re.IGNORECASE,
    )


def jats_figures(xml_path: Path) -> dict[str, str]:
    root = ET.parse(xml_path).getroot()
    figures = {}
    for fig in root.iter("fig"):
        label = normalize_label(text_of(fig.find("label")))
        if label:
            figures[label] = text_of(fig.find("caption"))
    return figures


def evaluate(raw_dir: Path, expected_path: Path) -> dict:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    annotated_pages = {
        (f["pmcid"], normalize_label(f["label"])): f["page"] for f in expected["figures"]
    }
    extractor = PdfiumFigureExtractor()
    articles = []
    for pmcid, info in expected["articles"].items():
        gold = jats_figures(raw_dir / f"{pmcid}.xml")
        gold_labels = info.get("expected_labels") or sorted(gold)
        pdf = pdfium.PdfDocument(raw_dir / f"{pmcid}.pdf")
        started = time.perf_counter()
        result = extractor.extract(pdf)
        seconds = time.perf_counter() - started
        pdf.close()

        found = {f.label: f for f in result.figures if f.label}
        similarities = []
        for label in gold_labels:
            figure, gold_caption = found.get(label), gold.get(label, "")
            if figure and figure.caption and gold_caption:
                similarities.append(
                    difflib.SequenceMatcher(
                        None,
                        comparable(strip_label(figure.caption.text)),
                        comparable(gold_caption),
                        autojunk=False,
                    ).ratio()
                )
        pages = [
            (label, found[label].page_index + 1, page)
            for (pid, label), page in annotated_pages.items()
            if pid == pmcid and label in found
        ]
        articles.append(
            {
                "pmcid": pmcid,
                "expected": len(gold_labels),
                "labels_found": sum(1 for label in gold_labels if label in found),
                "with_region": sum(
                    1 for label in gold_labels if label in found and found[label].status == "ok"
                ),
                "spurious_labels": sorted(set(found) - set(gold_labels)),
                "unlabelled_regions": sum(1 for f in result.figures if f.label is None),
                "caption_similarity": similarities,
                "pages_checked": len(pages),
                "pages_correct": sum(1 for _, got, want in pages if got == want),
                "page_count": len(result.pages),
                "seconds": round(seconds, 2),
            }
        )
    return {"articles": articles}


def summarize(report: dict) -> str:
    rows, totals = (
        [],
        {
            "expected": 0,
            "labels_found": 0,
            "with_region": 0,
            "unlabelled_regions": 0,
            "pages_checked": 0,
            "pages_correct": 0,
            "page_count": 0,
            "seconds": 0.0,
        },
    )
    all_similarities: list[float] = []
    spurious = 0
    for a in report["articles"]:
        for key in totals:
            totals[key] += a[key]
        all_similarities += a["caption_similarity"]
        spurious += len(a["spurious_labels"])
        sims = a["caption_similarity"]
        matched = sum(1 for s in sims if s >= CAPTION_MATCH)
        rows.append(
            f"| {a['pmcid']} | {a['expected']} | {a['labels_found']} | {a['with_region']} | "
            f"{len(a['spurious_labels'])} | {a['unlabelled_regions']} | "
            f"{f'{matched}/{len(sims)}' if sims else 'n/a'} | "
            f"{f'{statistics.mean(sims):.3f}' if sims else 'n/a'} | {a['seconds']} |"
        )
    figures_found = totals["labels_found"] + spurious + totals["unlabelled_regions"]
    precision = (totals["labels_found"]) / figures_found if figures_found else 0
    matched = sum(1 for s in all_similarities if s >= CAPTION_MATCH)
    lines = [
        "| Artículo | Esperadas | Etiqueta encontrada | Con región | Etiquetas espurias | Regiones sin pie "
        f"| Pies ≥ {CAPTION_MATCH} | Similitud media | Segundos |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
        f"- Recall de etiquetas: **{totals['labels_found']}/{totals['expected']}** "
        f"({totals['labels_found'] / totals['expected']:.1%}).",
        f"- Figuras con región asociada: **{totals['with_region']}/{totals['expected']}** "
        f"({totals['with_region'] / totals['expected']:.1%}).",
        f"- Precisión (figuras esperadas / todo lo reportado): **{precision:.1%}** "
        f"({spurious} etiquetas espurias, {totals['unlabelled_regions']} regiones sin pie).",
        f"- Pies con similitud ≥ {CAPTION_MATCH} frente a JATS: **{matched}/{len(all_similarities)}**; "
        f"similitud media {statistics.mean(all_similarities):.3f}, mínima {min(all_similarities):.3f}.",
        f"- Página correcta en figuras anotadas a mano: **{totals['pages_correct']}/{totals['pages_checked']}**.",
        f"- Tiempo: {totals['seconds']:.1f} s para {totals['page_count']} páginas "
        f"({totals['seconds'] / totals['page_count'] * 1000:.0f} ms/página, sin renderizar recortes).",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/stage0")
    parser.add_argument("--expected", type=Path, default=ROOT / "data/stage0/expected_results.json")
    parser.add_argument("--json", type=Path, help="also write the per-article results as JSON")
    args = parser.parse_args()
    report = evaluate(args.raw_dir, args.expected)
    print(summarize(report))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
