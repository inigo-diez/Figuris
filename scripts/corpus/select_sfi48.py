"""Select the SFI-48 benchmark (research/experiments.md) reproducibly.

SFI-48 = the SFI-12 pilot as the ``dev`` split (it was used to develop the
pipeline, so it cannot be validation or test) plus 36 new PMC Open Access
articles: 6 per discipline, split 2 ``validation`` / 4 ``test`` per stratum.

For each stratum the script runs a fixed PMC search (NCBI E-utilities, license
filter), shuffles the results with a fixed seed and accepts candidates in that
order when the PMC Open Access metadata confirms:

- license in the allowlist (CC BY, CC0) and not retracted, PDF and JATS present;
- between ``min_figures`` and ``max_figures`` figures in the JATS;
- at least one multipanel figure (caption with panel markers), so that the
  benchmark reaches the target share of multipanel figures;
- scanned strata: PMC flags the article as historical OCR, and the OCR text refers to
  at least ``min_figures`` distinct figures (the JATS of scanned articles often lists
  none: their figures exist only in the page images, so ``expected_labels`` are
  taken from the OCR text and must be reviewed).

Splits are assigned here, before any system output exists for these articles,
and must not change afterwards: ``test`` is frozen.

Usage:
    python scripts/corpus/select_sfi48.py --out data/sfi48/selection.json
    python scripts/corpus/fetch_pmc_oa.py data/sfi48/selection.json \\
        --out-dir data/raw/sfi48 --manifest data/sfi48/manifest.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_pmc_oa import BUCKET_URL, CorpusError, http_get, latest_version_prefix, text_of

ROOT = Path(__file__).resolve().parents[2]
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
SEED = 20261006
ALLOWED = ["CC BY", "CC0"]
JOURNALS = (
    '("Sci Rep"[journal] OR "PLoS One"[journal] OR "Nat Commun"[journal] OR '
    '"R Soc Open Sci"[journal] OR "Heliyon"[journal] OR "PeerJ"[journal])'
)
BORN_DIGITAL = '2016:2024[pdat] AND "cc by license"[filter] AND ' + JOURNALS

STRATA = [
    {
        "id": "biomedicine",
        "pdf_kind": "born_digital",
        "count": 2,
        "split": {"validation": 1, "test": 1},
        "term": "(microscopy[Title/Abstract] OR immunohistochemistry[Title/Abstract] "
        'OR "western blot"[Title/Abstract]) AND ' + BORN_DIGITAL,
    },
    {
        "id": "biomedicine",
        "pdf_kind": "scanned",
        "count": 4,
        "split": {"validation": 1, "test": 3},
        "term": '"Br J Cancer"[journal] AND 1975:1995[pdat] AND "cc by license"[filter]',
        "require_ocr": True,
    },
    {
        "id": "chemistry_materials",
        "pdf_kind": "born_digital",
        "count": 6,
        "split": {"validation": 2, "test": 4},
        "term": "(nanoparticles[Title] OR catalyst[Title] OR catalytic[Title] OR "
        'polymer[Title] OR "crystal structure"[Title] OR electrochemical[Title]) AND '
        + BORN_DIGITAL,
    },
    {
        "id": "physics_astronomy",
        "pdf_kind": "born_digital",
        "count": 6,
        "split": {"validation": 2, "test": 4},
        "term": "(astrophysics[Title/Abstract] OR galaxy[Title] OR quantum[Title] OR "
        "laser[Title] OR plasma[Title] OR optical[Title]) AND " + BORN_DIGITAL,
    },
    {
        "id": "environment_geo",
        "pdf_kind": "born_digital",
        "count": 6,
        "split": {"validation": 2, "test": 4},
        "term": '("land use"[Title] OR "remote sensing"[Title] OR climate[Title] OR '
        'hydrolog*[Title] OR "air pollution"[Title] OR groundwater[Title]) AND ' + BORN_DIGITAL,
    },
    {
        "id": "computer_science_engineering",
        "pdf_kind": "born_digital",
        "count": 6,
        "split": {"validation": 2, "test": 4},
        "term": '("deep learning"[Title] OR "neural network"[Title] OR robot*[Title] OR '
        "algorithm[Title] OR sensor[Title]) NOT (patients[Title] OR clinical[Title]) AND "
        + BORN_DIGITAL,
    },
    {
        "id": "social_sciences",
        "pdf_kind": "born_digital",
        "count": 6,
        "split": {"validation": 2, "test": 4},
        "term": '(survey[Title] OR "public opinion"[Title] OR economic[Title] OR '
        "education[Title] OR policy[Title] OR voting[Title]) NOT (patients[Title] OR "
        "clinical[Title]) AND " + BORN_DIGITAL,
    },
]

OCR_FIGURE = re.compile(r"\bFig(?:ure|\.)?\s*(\d{1,2})\b")
PANEL_MARKER = re.compile(
    r"(\(\s*[a-hA-H]\s*\)|(?:^|[.;]\s+)[a-hA-H][.,:)]\s|\b[A-H]\s*[–-]\s*[A-H]\b)"
)


def search(term: str, retmax: int) -> list[str]:
    query = urllib.parse.urlencode({"db": "pmc", "term": term, "retmode": "json", "retmax": retmax})
    data = json.loads(http_get(f"{ESEARCH}?{query}"))
    time.sleep(0.4)  # NCBI asks for at most 3 requests per second without an API key
    return [f"PMC{i}" for i in data["esearchresult"]["idlist"]]


def multipanel(caption: str) -> bool:
    return len(PANEL_MARKER.findall(caption)) >= 2


def inspect(pmcid: str, stratum: dict, limits: dict) -> dict:
    prefix = latest_version_prefix(pmcid)
    meta = json.loads(http_get(f"{BUCKET_URL}/{prefix}/{prefix}.json"))
    if meta.get("license_code") not in ALLOWED:
        raise CorpusError(f"license {meta.get('license_code')!r}")
    if meta.get("is_retracted"):
        raise CorpusError("retracted")
    if not meta.get("pdf_url") or not meta.get("xml_url"):
        raise CorpusError("PDF or XML missing")
    if stratum.get("require_ocr") and not meta.get("is_historical_ocr"):
        raise CorpusError("not a scanned (historical OCR) article")
    root = ET.fromstring(http_get(f"{BUCKET_URL}/{prefix}/{prefix}.xml"))
    figures = root.findall(".//fig")
    captions = [text_of(f.find("caption")) for f in figures]
    expected_labels = None
    if stratum.get("require_ocr"):
        text = http_get(f"{BUCKET_URL}/{prefix}/{prefix}.txt").decode("utf-8", "replace")
        numbers = sorted({int(n) for n in OCR_FIGURE.findall(text) if 0 < int(n) < 30})
        if len(numbers) < limits["min_figures"]:
            raise CorpusError(f"OCR text refers to {len(numbers)} figures")
        # Figures are numbered consecutively; gaps are usually OCR misses.
        expected_labels = [f"Figure {n}" for n in range(1, max(numbers) + 1)]
    else:
        if not limits["min_figures"] <= len(figures) <= limits["max_figures"]:
            raise CorpusError(f"{len(figures)} figures")
        if not any(multipanel(c) for c in captions):
            raise CorpusError("no multipanel figure")
    language = root.get("{http://www.w3.org/XML/1998/namespace}lang", "en")
    return {
        "pmcid": pmcid,
        "discipline": stratum["id"],
        "pdf_kind": stratum["pdf_kind"],
        "title": meta.get("title"),
        "journal_citation": meta.get("citation"),
        "license_code": meta["license_code"],
        "language": language,
        "figures_in_jats": len(figures),
        "multipanel_figures_estimate": sum(multipanel(c) for c in captions),
        **(
            {"expected_labels": expected_labels, "expected_labels_source": "ocr_text_draft"}
            if expected_labels
            else {}
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "data/sfi48/selection.json")
    parser.add_argument("--pilot", type=Path, default=ROOT / "data/stage0/selection.json")
    parser.add_argument("--min-figures", type=int, default=3)
    parser.add_argument("--max-figures", type=int, default=10)
    # Results come newest first: draw from a wide pool so all publication years are covered.
    parser.add_argument("--retmax", type=int, default=2000)
    args = parser.parse_args()
    limits = {"min_figures": args.min_figures, "max_figures": args.max_figures}

    pilot = json.loads(args.pilot.read_text(encoding="utf-8"))
    excluded = {a["pmcid"] for a in pilot["articles"]}
    rng = random.Random(SEED)
    articles = [
        {
            "pmcid": a["pmcid"],
            "discipline": a["discipline"],
            "pdf_kind": a["pdf_kind"],
            "split": "dev",
            "stratum": "pilot",
        }
        for a in pilot["articles"]
        if not a.get("reason")  # reserves were not part of the pilot
    ]
    log = []
    for stratum in STRATA:
        ids = search(stratum["term"], args.retmax)
        rng.shuffle(ids)
        chosen, rejected = [], 0
        for pmcid in ids:
            if len(chosen) == stratum["count"]:
                break
            if pmcid in excluded:
                continue
            try:
                record = inspect(pmcid, stratum, limits)
            except (CorpusError, OSError, ET.ParseError, json.JSONDecodeError) as exc:
                rejected += 1
                print(f"  skip {pmcid:<12} {exc}", file=sys.stderr)
                continue
            excluded.add(pmcid)
            chosen.append(record)
            print(f"  ok   {pmcid:<12} {stratum['id']:<28} figs={record['figures_in_jats']}")
        if len(chosen) < stratum["count"]:
            print(f"WARNING {stratum['id']}/{stratum['pdf_kind']}: only {len(chosen)} found")
        # Fixed split assignment inside the stratum.
        order = list(range(len(chosen)))
        rng.shuffle(order)
        splits = [s for s, n in stratum["split"].items() for _ in range(n)]
        for position, index in enumerate(order):
            chosen[index]["split"] = splits[position] if position < len(splits) else "test"
            chosen[index]["stratum"] = f"{stratum['id']}/{stratum['pdf_kind']}"
        articles += chosen
        log.append(
            {
                "stratum": f"{stratum['id']}/{stratum['pdf_kind']}",
                "term": stratum["term"],
                "results": len(ids),
                "inspected": len(chosen) + rejected,
                "accepted": len(chosen),
            }
        )

    selection = {
        "corpus": "SFI-48",
        "allowed_licenses": ALLOWED,
        "seed": SEED,
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "selection_rules": {
            **limits,
            "multipanel": "at least one figure caption with two or more panel markers",
            "scanned": "PMC is_historical_ocr flag",
        },
        "splits": {
            s: sum(1 for a in articles if a["split"] == s) for s in ("dev", "validation", "test")
        },
        "search_log": log,
        "articles": articles,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(selection, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\n{len(articles)} articles {selection['splits']} -> {args.out}")
    return 0 if len(articles) == 48 else 1


if __name__ == "__main__":
    sys.exit(main())
