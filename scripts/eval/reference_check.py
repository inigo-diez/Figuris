"""Invented references in the stored explanations of one SFI-48 split.

An invented reference is a source an explanation cites that does not exist: a passage
that was not given, a quote that is not in the cited passage or the caption, a panel
that is not in the figure, the caption of a figure without one, or a claim id that is
not defined (validator errors with a code in ``INVENTED``). A quote attributed to the wrong passage
is counted apart: the quote exists, only its address is wrong.

The validator finds them in every model output; an explanation with one is stored as
``invalid`` and shown as "no fiable". The script counts how often the model invents
a reference and checks that none reaches the reader in an explanation shown as
reliable (``ok``).

Reads the latest completed run of each document in the local database (``sfi
process`` must have been run on the split's PDFs). The ``test`` split is only read
with --include-test, and every such run is appended to data/sfi48/test_runs.log.

Usage:
    python scripts/eval/reference_check.py --split validation
    python scripts/eval/reference_check.py --split test --include-test
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

from sfi.config import Settings
from sfi.pipeline import FigurePipeline

sys.path.insert(0, str(Path(__file__).parent))
from runlog import save_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
INVENTED = {
    "unknown_passage",
    "quote_not_in_text",
    "quote_not_in_caption",
    "caption_evidence_without_caption",
    "text_evidence_without_passages",
    "unknown_panel",
    "unknown_claim_ref",
}
MISATTRIBUTED = {"wrong_passage"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus-dir", type=Path, default=ROOT / "data/sfi48")
    parser.add_argument("--split", required=True, choices=("dev", "validation", "test"))
    parser.add_argument("--include-test", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    if args.split == "test":
        if not args.include_test:
            parser.error("the test split is frozen: pass --include-test to read it")
        with (args.corpus_dir / "test_runs.log").open("a", encoding="utf-8") as handle:
            handle.write(
                f"{dt.datetime.now(dt.UTC).isoformat(timespec='seconds')} "
                "reference_check --include-test\n"
            )

    manifest = json.loads((args.corpus_dir / "expected_figures.json").read_text("utf-8"))
    pmcids = {a["pmcid"] for a in manifest["articles"] if a["split"] == args.split}
    pipeline = FigurePipeline.from_settings(Settings.from_env())
    repository = pipeline.repository

    statuses: Counter = Counter()
    codes: Counter = Counter()
    rows = []
    claims = evidence = 0
    shown_with_invented = 0
    seen: set[str] = set()
    for document in repository.find_documents(""):
        pmcid = Path(document.filename).stem
        if pmcid not in pmcids or pmcid in seen:
            continue
        seen.add(pmcid)
        run = repository.latest_completed_run(document.id)
        if run is None:
            continue
        for figure in repository.list_figures(run.id):
            analysis = repository.latest_analysis(figure.id)
            if analysis is None:
                statuses["not analysed"] += 1
                continue
            statuses[analysis.status.value] += 1
            # Only errors: a panel range in the layout notes ("b–d") is a warning.
            invented = [
                i.code for i in analysis.issues if i.code in INVENTED and i.severity == "error"
            ]
            misattributed = [i.code for i in analysis.issues if i.code in MISATTRIBUTED]
            codes.update(invented + misattributed)
            if analysis.explanation is not None:
                claims += len(analysis.explanation.claims)
                evidence += sum(len(c.evidence) for c in analysis.explanation.claims)
            if invented and analysis.status.value == "ok":
                shown_with_invented += 1
            rows.append(
                {
                    "pmcid": pmcid,
                    "figure": figure.label,
                    "status": analysis.status.value,
                    "invented": invented,
                    "misattributed": misattributed,
                }
            )
    with_invented = sum(1 for r in rows if r["invented"])
    metrics = {
        "split": args.split,
        "documents": len(seen),
        "documents_expected": len(pmcids),
        "statuses": dict(statuses),
        "explanations": len(rows),
        "claims": claims,
        "evidence_items": evidence,
        "explanations_with_invented_reference": with_invented,
        "invented_references": sum(codes[c] for c in INVENTED),
        "misattributed_quotes": sum(codes[c] for c in MISATTRIBUTED),
        "by_code": dict(codes),
        "shown_as_reliable_with_invented_reference": shown_with_invented,
    }
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    if not args.no_save:
        target = save_run("references", args.split, {"codes": sorted(INVENTED)}, metrics, rows)
        print(f"run saved to {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
