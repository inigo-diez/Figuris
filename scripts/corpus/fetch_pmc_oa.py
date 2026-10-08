"""Download a license-checked test corpus from the PMC Open Access subset.

Source: the official PMC Article Datasets bucket on AWS Open Data
(``s3://pmc-oa-opendata``), accessed anonymously over HTTPS. For every
requested PMCID the script:

1. reads the article metadata JSON published by PMC;
2. rejects the article unless its ``license_code`` is in the allowlist and it
   is not retracted;
3. downloads the PDF and the JATS XML, verifying the MD5 published by PMC;
4. records SHA-256, license URL and attribution in a manifest;
5. flags figures whose own permissions or credit lines may exclude them from
   the article-level license, for manual review.

The license allowlist is read from the selection file (``allowed_licenses``)
and defaults to ``CC BY``.

PDFs and XML are written to ``--out-dir`` (git-ignored). Only the manifest is
meant to be versioned: article content keeps its own license and is never
committed.

Usage:
    python scripts/corpus/fetch_pmc_oa.py data/stage0/selection.json \
        --out-dir data/raw/stage0 --manifest data/stage0/manifest.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BUCKET_URL = "https://pmc-oa-opendata.s3.amazonaws.com"
DEFAULT_ALLOWED_LICENSES = ["CC BY"]
USER_AGENT = "scientific-figure-intelligence-corpus/0.1"
XLINK = "{http://www.w3.org/1999/xlink}"
ALI = "{http://www.niso.org/schemas/ali/1.0/}"


class CorpusError(Exception):
    """An article cannot be accepted into the corpus."""


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def latest_version_prefix(pmcid: str) -> str:
    listing = http_get(f"{BUCKET_URL}/?list-type=2&prefix={pmcid}.&max-keys=100").decode()
    versions = sorted({int(v) for v in re.findall(rf"<Key>{pmcid}\.(\d+)/", listing)})
    if not versions:
        raise CorpusError(f"{pmcid}: not found in the PMC Open Access bucket")
    return f"{pmcid}.{versions[-1]}"


def s3_to_https(s3_url: str) -> tuple[str, str]:
    """Return (https_url, expected_md5) for an ``s3://bucket/key?md5=...`` URL."""
    match = re.fullmatch(r"s3://pmc-oa-opendata/([^?]+)\?md5=([0-9a-f]{32})", s3_url)
    if not match:
        raise CorpusError(f"unexpected object URL: {s3_url}")
    return f"{BUCKET_URL}/{match.group(1)}", match.group(2)


def download_verified(s3_url: str, target: Path) -> str:
    """Download an object, check PMC's MD5 and return the SHA-256 of the bytes."""
    url, expected_md5 = s3_to_https(s3_url)
    if target.exists() and hashlib.md5(target.read_bytes()).hexdigest() == expected_md5:
        data = target.read_bytes()
    else:
        data = http_get(url)
        if hashlib.md5(data).hexdigest() != expected_md5:
            raise CorpusError(f"MD5 mismatch for {url}")
        target.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def jats_license(root: ET.Element) -> dict[str, str | None]:
    """Extract license URL and copyright statement from the JATS permissions."""
    permissions = root.find(".//article-meta/permissions")
    if permissions is None:
        return {"license_url": None, "copyright": None}
    url = None
    license_el = permissions.find("license")
    if license_el is not None:
        url = license_el.get(f"{XLINK}href")
    if url is None:
        ref = permissions.find(f".//{ALI}license_ref")
        url = ref.text.strip() if ref is not None and ref.text else None
    statement = permissions.findtext("copyright-statement")
    return {
        "license_url": url,
        "copyright": " ".join(statement.split()) if statement else None,
    }


# Caption phrases that usually signal third-party material inside a figure.
CREDIT_PATTERN = re.compile(
    r"\b(credit|courtesy|reproduced|reprinted|adapted from|copyright|with permission)\b|©",
    re.IGNORECASE,
)


def text_of(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def figure_exceptions(root: ET.Element) -> list[dict[str, str]]:
    """List figures with their own permissions, attribution or credit lines.

    These are candidates for manual review, not confirmed exclusions: a credit
    line may name the article's own authors.
    """
    flagged = []
    for fig in root.iter("fig"):
        label = text_of(fig.find("label")) or fig.get("id", "?")
        reasons = []
        if fig.find("permissions") is not None:
            reasons.append(f"figure permissions: {text_of(fig.find('permissions'))}")
        for attrib in fig.iter("attrib"):
            reasons.append(f"attrib: {text_of(attrib)}")
        caption = text_of(fig.find("caption"))
        for match in CREDIT_PATTERN.finditer(caption):
            start = max(0, match.start() - 60)
            reasons.append(f"caption: …{caption[start : match.end() + 100]}…")
        if reasons:
            flagged.append({"label": label, "reasons": reasons, "review_status": "pending"})
    return flagged


def attribution(meta: dict, root: ET.Element, license_url: str | None) -> str:
    authors = [
        text_of(name.find("surname"))
        for name in root.findall(
            ".//article-meta/contrib-group/contrib[@contrib-type='author']/name"
        )
    ]
    author_text = (
        authors[0] + (" et al." if len(authors) > 1 else "") if authors else "Unknown authors"
    )
    citation = (meta.get("citation") or "").rstrip(". ")
    return (
        f'{author_text}, "{meta.get("title")}", {citation}. '
        f"Licensed under {meta.get('license_code')} ({license_url or 'license URL not stated'})."
    )


def fetch_article(entry: dict, out_dir: Path, allowed_licenses: list[str]) -> dict:
    pmcid = entry["pmcid"]
    prefix = latest_version_prefix(pmcid)
    meta = json.loads(http_get(f"{BUCKET_URL}/{prefix}/{prefix}.json"))

    if meta.get("license_code") not in allowed_licenses:
        raise CorpusError(f"{pmcid}: license {meta.get('license_code')!r} not allowed")
    if meta.get("is_retracted"):
        raise CorpusError(f"{pmcid}: article is retracted")
    if not meta.get("pdf_url") or not meta.get("xml_url"):
        raise CorpusError(f"{pmcid}: PDF or XML missing")

    pdf_path = out_dir / f"{pmcid}.pdf"
    xml_path = out_dir / f"{pmcid}.xml"
    pdf_sha256 = download_verified(meta["pdf_url"], pdf_path)
    xml_sha256 = download_verified(meta["xml_url"], xml_path)
    root = ET.fromstring(xml_path.read_bytes())
    license_info = jats_license(root)

    return {
        "pmcid": pmcid,
        **{k: v for k, v in entry.items() if k != "pmcid"},
        "pmc_version": meta.get("version"),
        "doi": meta.get("doi"),
        "title": meta.get("title"),
        "citation": meta.get("citation"),
        "license_code": meta["license_code"],
        **license_info,
        "attribution": attribution(meta, root, license_info["license_url"]),
        "figure_license_exceptions": figure_exceptions(root),
        "is_historical_ocr": meta.get("is_historical_ocr", False),
        "figures_in_jats": len(root.findall(".//fig")),
        "tables_in_jats": len(root.findall(".//table-wrap")),
        "source_url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",
        "pdf_object": meta["pdf_url"],
        "pdf_download_url": s3_to_https(meta["pdf_url"])[0],
        "pdf_sha256": pdf_sha256,
        "pdf_bytes": pdf_path.stat().st_size,
        "xml_sha256": xml_sha256,
        "local_pdf": pdf_path.name,
        "retrieved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("selection", type=Path, help="JSON file with an 'articles' list")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)

    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    allowed_licenses = selection.get("allowed_licenses", DEFAULT_ALLOWED_LICENSES)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    accepted, rejected = [], []
    for entry in selection["articles"]:
        try:
            record = fetch_article(entry, args.out_dir, allowed_licenses)
        except (CorpusError, OSError, ET.ParseError) as exc:
            rejected.append({"pmcid": entry["pmcid"], "reason": str(exc)})
            print(f"REJECTED {entry['pmcid']:<12} {exc}", file=sys.stderr)
            continue
        accepted.append(record)
        flagged = len(record["figure_license_exceptions"])
        print(
            f"ok       {record['pmcid']:<12} {record['license_code']:<6} "
            f"figs={record['figures_in_jats']:<3} tables={record['tables_in_jats']:<3} "
            f"{record['pdf_bytes'] // 1024} KiB"
            + (f"  [{flagged} figure(s) to review]" if flagged else "")
        )

    manifest = {
        "corpus": selection.get("corpus", "stage0"),
        "source": "PMC Open Access subset (s3://pmc-oa-opendata)",
        "allowed_licenses": allowed_licenses,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "articles": accepted,
        "rejected": rejected,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\n{len(accepted)} accepted, {len(rejected)} rejected -> {args.manifest}")
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
