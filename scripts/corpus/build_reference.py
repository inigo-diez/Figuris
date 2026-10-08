"""Build the SFI-48 figure reference ("silver" gold) from PMC data, not from our system.

For every figure listed in an article's JATS:

- label, JATS id and caption come from the JATS;
- page and box are found by locating the figure image published by PMC on the
  rendered PDF pages (multi-scale normalized cross-correlation, OpenCV);
- in-text mentions come from the ``<xref ref-type="fig">`` of the JATS body, with a
  fingerprint of each mentioning paragraph so passages can be matched later;
- panel labels are drafted from the caption.

Boxes located with a low score, and every figure of scanned articles (whose JATS
does not list their figures), are marked ``needs_manual``. Nothing here is human
reviewed yet: ``review_status`` is ``auto`` or ``needs_manual`` until someone checks
it (research/experiments.md, annotation protocol).

Usage:
    python scripts/corpus/build_reference.py [--only PMC123,PMC456]
Requires the eval extra: pip install -e ".[eval]"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium

sys.path.insert(0, str(Path(__file__).parent))
from fetch_pmc_oa import BUCKET_URL, CorpusError, http_get, latest_version_prefix, text_of

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from sfi.extract.captions import normalize_label

ROOT = Path(__file__).resolve().parents[2]
XLINK = "{http://www.w3.org/1999/xlink}"
REFERENCE_VERSION = "reference/0.1"
COARSE_DPI = 36
FINE_DPI = 100
ACCEPT_SCORE = 0.6  # below this, the located box must be checked by hand
PANEL = re.compile(r"(?:\(\s*([a-hA-H])\s*\)|(?:^|[.;]\s+|\|\s*)([a-hA-H])[.,:)]\s)")


def fingerprint(text: str) -> str:
    """Stable, content-free key for a paragraph: its first 60 letters and digits."""
    return re.sub(r"[^0-9a-z]+", "", text.lower())[:60]


def render_gray(page: pdfium.PdfPage, dpi: int) -> np.ndarray:
    image = page.render(scale=dpi / 72, grayscale=True).to_numpy()
    return image[..., 0] if image.ndim == 3 else image


def locate(figure: np.ndarray, pages: list[np.ndarray]) -> tuple[int, float, float, tuple]:
    """Best (page index, score, width fraction, (x, y, w, h)) at coarse resolution."""
    best = (-1, -1.0, 0.0, (0, 0, 0, 0))
    aspect = figure.shape[0] / figure.shape[1]
    for index, page in enumerate(pages):
        height, width = page.shape
        for fraction in np.geomspace(0.18, 1.0, 26):
            w = int(width * fraction)
            h = int(w * aspect)
            if w < 24 or h < 24 or h > height or w > width:
                continue
            template = cv2.resize(figure, (w, h), interpolation=cv2.INTER_AREA)
            if template.std() < 1:
                continue
            scores = cv2.matchTemplate(page, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            if score > best[1]:
                best = (index, float(score), float(fraction), (x, y, w, h))
    return best


def refine(figure: np.ndarray, page: np.ndarray, fraction: float) -> tuple[float, tuple]:
    best = (-1.0, (0, 0, 0, 0))
    height, width = page.shape
    aspect = figure.shape[0] / figure.shape[1]
    for f in np.linspace(fraction * 0.9, min(1.0, fraction * 1.1), 11):
        w = int(width * f)
        h = int(w * aspect)
        if h > height or w > width or w < 24:
            continue
        template = cv2.resize(figure, (w, h), interpolation=cv2.INTER_AREA)
        scores = cv2.matchTemplate(page, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if score > best[0]:
            best = (float(score), (x, y, w, h))
    return best


def figure_image(pmcid: str, prefix: str, href: str, cache: Path) -> np.ndarray | None:
    name = href if href.lower().endswith((".jpg", ".png", ".gif", ".tif")) else f"{href}.jpg"
    target = cache / name
    if not target.exists():
        try:
            data = http_get(f"{BUCKET_URL}/{prefix}/{name}")
        except OSError:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    image = cv2.imdecode(np.frombuffer(target.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    return image


def mentions(root: ET.Element) -> dict[str, dict]:
    parents = {child: parent for parent in root.iter() for child in parent}
    body = root.find(".//body")
    found: dict[str, dict] = {}
    for xref in body.iter("xref") if body is not None else []:
        if xref.get("ref-type") != "fig":
            continue
        paragraph = xref
        while paragraph is not None and paragraph.tag != "p":
            paragraph = parents.get(paragraph)
        for rid in (xref.get("rid") or "").split():
            entry = found.setdefault(rid, {"count": 0, "paragraphs": []})
            entry["count"] += 1
            if paragraph is not None:
                key = fingerprint(text_of(paragraph))
                if key and key not in entry["paragraphs"]:
                    entry["paragraphs"].append(key)
    return found


def build_article(article: dict, raw_dir: Path) -> dict:
    pmcid = article["pmcid"]
    root = ET.parse(raw_dir / f"{pmcid}.xml").getroot()
    pdf = pdfium.PdfDocument(raw_dir / f"{pmcid}.pdf")
    coarse = [render_gray(pdf[i], COARSE_DPI) for i in range(len(pdf))]
    xrefs = mentions(root)
    prefix = latest_version_prefix(pmcid)
    figures = []
    for fig in root.iter("fig"):
        label = normalize_label(text_of(fig.find("label")))
        caption = text_of(fig.find("caption"))
        panels = sorted({a or b for a, b in PANEL.findall(caption)})
        record = {
            "jats_id": fig.get("id"),
            "label": label,
            "caption_fingerprint": fingerprint(caption),
            "panels_from_caption": panels,
            "mentions": xrefs.get(fig.get("id"), {"count": 0, "paragraphs": []}),
            "page": None,
            "bbox": None,
            "match_score": None,
            "review_status": "needs_manual",
        }
        graphic = fig.find(".//graphic")
        href = graphic.get(f"{XLINK}href") if graphic is not None else None
        image = figure_image(pmcid, prefix, href, raw_dir / "figures" / pmcid) if href else None
        if image is not None:
            small = cv2.resize(image, (max(1, image.shape[1] // 4), max(1, image.shape[0] // 4)))
            index, score, fraction, _ = locate(small, coarse)
            if index >= 0:
                page = render_gray(pdf[index], FINE_DPI)
                score, (x, y, w, h) = refine(image, page, fraction)
                height, width = page.shape
                record.update(
                    page=index + 1,
                    bbox=[
                        round(x / width, 4),
                        round(y / height, 4),
                        round(min(1, (x + w) / width), 4),
                        round(min(1, (y + h) / height), 4),
                    ],
                    match_score=round(score, 3),
                    review_status="auto" if score >= ACCEPT_SCORE else "needs_manual",
                )
        figures.append(record)
    pdf.close()

    if article.get("expected_labels"):  # scanned: the JATS does not list the figures
        listed = {f["label"] for f in figures}
        for label in article["expected_labels"]:
            if label not in listed:
                figures.append(
                    {
                        "jats_id": None,
                        "label": label,
                        "source": article.get("expected_labels_source", "manual"),
                        "page": None,
                        "bbox": None,
                        "review_status": "needs_manual",
                    }
                )
    return {
        "pmcid": pmcid,
        "split": article["split"],
        "stratum": article.get("stratum"),
        "pdf_kind": article.get("pdf_kind"),
        "pages": len(coarse),
        "figures": figures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--selection", type=Path, default=ROOT / "data/sfi48/selection.json")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/sfi48")
    parser.add_argument("--out", type=Path, default=ROOT / "data/sfi48/expected_figures.json")
    parser.add_argument("--only", help="comma-separated PMCIDs")
    parser.add_argument(
        "--pilot-expected", type=Path, default=ROOT / "data/stage0/expected_results.json"
    )
    args = parser.parse_args()

    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    # Pilot articles keep the hand-reviewed labels of the stage 0 expected results.
    pilot = json.loads(args.pilot_expected.read_text(encoding="utf-8"))["articles"]
    for article in selection["articles"]:
        reviewed = pilot.get(article["pmcid"], {}).get("expected_labels")
        if reviewed and not article.get("expected_labels"):
            article["expected_labels"] = reviewed
            article["expected_labels_source"] = "manual (stage 0)"
    only = set(args.only.split(",")) if args.only else None
    previous = (
        {a["pmcid"]: a for a in json.loads(args.out.read_text(encoding="utf-8"))["articles"]}
        if args.out.exists()
        else {}
    )
    articles = []
    for article in selection["articles"]:
        if only and article["pmcid"] not in only:
            if article["pmcid"] in previous:  # keep what was built before
                articles.append(previous[article["pmcid"]])
            continue
        try:
            built = build_article(article, args.raw_dir)
        except (CorpusError, OSError) as exc:
            print(f"ERROR {article['pmcid']}: {exc}", file=sys.stderr)
            return 1
        scores = [f["match_score"] for f in built["figures"] if f.get("match_score") is not None]
        manual = sum(1 for f in built["figures"] if f["review_status"] == "needs_manual")
        print(
            f"{built['pmcid']:<12} {built['split']:<10} figs={len(built['figures']):<3} "
            f"located={len(scores):<3} min_score={min(scores, default=0):.2f} manual={manual}"
        )
        articles.append(built)

    figures = [f for a in articles for f in a["figures"]]
    reference = {
        "corpus": "SFI-48",
        "version": REFERENCE_VERSION,
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "method": {
            "labels_captions_mentions": "JATS (PMC)",
            "page_bbox": f"PMC figure image located on the PDF page (OpenCV TM_CCOEFF_NORMED, "
            f"{COARSE_DPI} dpi search, {FINE_DPI} dpi refinement); review if score < {ACCEPT_SCORE}",
            "panels": "draft from caption markers",
            "bbox_convention": "normalized [x0, y0, x1, y1], origin top-left, page CropBox",
        },
        "summary": {
            "articles": len(articles),
            "figures": len(figures),
            "auto": sum(1 for f in figures if f["review_status"] == "auto"),
            "needs_manual": sum(1 for f in figures if f["review_status"] == "needs_manual"),
            "multipanel_from_caption": sum(
                1 for f in figures if len(f.get("panels_from_caption") or []) >= 2
            ),
        },
        "articles": articles,
    }
    args.out.write_text(
        json.dumps(reference, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\n{reference['summary']} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
