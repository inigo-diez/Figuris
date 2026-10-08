"""Import the rubric scores returned by an external reviewer (another AI).

Reads the JSON answer to a batch made by scripts/eval/export_judge_packet.py and
the batch's keys file, checks it strictly (every explanation of the batch, every
claim, valid scores, a note when something is wrong) and stores one record per
explanation in data/sfi48/reviews/claims.json with ``annotator_kind: llm``. These
are an LLM's judgements, reported apart from human scores, and are checked before
they are used (scripts/eval/review_summary.py).

The answer may be the bare JSON or text containing one ```json block.

Usage:
    python scripts/eval/import_judge_scores.py respuesta.json --keys claves.json
                                               [--annotator ia:modelo] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from export_judge_packet import CRITERIA_KEYS, CRITICAL_KEYS

from sfi.review import (
    RUBRIC_VERSION,
    ReviewError,
    ReviewStore,
    check_annotator,
    check_scores,
    now,
)

ROOT = Path(__file__).resolve().parents[2]


def parse_answer(text: str) -> dict:
    block = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    return json.loads(block.group(1) if block else text)


def convert(answer: dict, keys: dict, annotator: str) -> list[dict]:
    """Records for the review store; raises ReviewError listing every problem found."""
    problems: list[str] = []
    batch = answer.get("lote")
    expected = {i for i, k in keys.items() if batch is None or k["lote"] == batch}
    given = {e.get("id"): e for e in answer.get("explicaciones", [])}
    if missing := sorted(expected - set(given)):
        problems.append(f"faltan explicaciones: {', '.join(missing)}")
    if unknown := sorted(set(given) - set(keys)):
        problems.append(f"explicaciones desconocidas: {', '.join(map(str, unknown))}")
    records = []
    for item_id in sorted(set(given) & set(keys)):
        key, entry = keys[item_id], given[item_id]
        claims = {c["id"]: c for c in key["claims"]}
        scored_by_id = {a.get("id"): a for a in entry.get("afirmaciones", [])}
        if missing := sorted(set(claims) - set(scored_by_id)):
            problems.append(f"{item_id}: faltan afirmaciones {', '.join(missing)}")
        if unknown := sorted(set(scored_by_id) - set(claims)):
            problems.append(f"{item_id}: afirmaciones desconocidas {', '.join(map(str, unknown))}")
        scored = []
        for claim_id, claim in claims.items():
            given_claim = scored_by_id.get(claim_id, {})
            raw = {
                rubric_id: (
                    "na"
                    if given_claim.get(key_es) in ("NA", "na", "N/A")
                    else given_claim.get(key_es)
                )
                for key_es, rubric_id in CRITERIA_KEYS.items()
            }
            critical = given_claim.get("error_critico")
            note = (given_claim.get("nota") or "").strip() or None
            try:
                scores = check_scores({k: v for k, v in raw.items() if v is not None})
                if len(scores) < len(CRITERIA_KEYS) and claim_id in scored_by_id:
                    raise ReviewError("faltan criterios")
                if critical is not None and critical not in CRITICAL_KEYS:
                    raise ReviewError(f"error crítico desconocido {critical!r}")
                low = any(v != "na" and v < 2 for v in scores.values())
                if (low or critical) and not note:
                    raise ReviewError("falta la nota que explique la puntuación")
            except ReviewError as exc:
                problems.append(f"{item_id}/{claim_id}: {exc}")
                continue
            scored.append(
                {
                    **claim,
                    "scores": scores,
                    "critical": CRITICAL_KEYS.get(critical) if critical else None,
                    "note": note,
                }
            )
        records.append(
            {
                "analysis": key["analysis"],
                "annotator": annotator,
                "annotator_kind": "llm",
                "judge": answer.get("revisor"),
                **{
                    k: key[k]
                    for k in (
                        "document_sha256",
                        "filename",
                        "pmcid",
                        "split",
                        "figure_label",
                        "page",
                        "explanation_status",
                        "model",
                        "prompt_version",
                        "schema_version",
                    )
                },
                "rubric_version": RUBRIC_VERSION,
                "comment": (entry.get("comentario") or "").strip() or None,
                "claims": scored,
                "scored_at": now(),
                "packet_item": item_id,
            }
        )
    if problems:
        raise ReviewError("\n".join(problems))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("answer", type=Path)
    parser.add_argument("--keys", type=Path, required=True)
    parser.add_argument("--annotator", help="default: ia:<revisor declared in the answer>")
    parser.add_argument("--corpus-dir", type=Path, default=ROOT / "data/sfi48")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    answer = parse_answer(args.answer.read_text(encoding="utf-8"))
    keys = json.loads(args.keys.read_text(encoding="utf-8"))["items"]
    try:
        reviewer = re.sub(r"[^\w .-]+", "-", str(answer.get("revisor") or "desconocido"))[:36]
        annotator = check_annotator(args.annotator or f"ia-{reviewer}".strip("-"))
        records = convert(answer, keys, annotator)
    except (ReviewError, KeyError, TypeError, AttributeError) as exc:
        print(f"Respuesta rechazada:\n{exc}", file=sys.stderr)
        return 1
    claims = sum(len(r["claims"]) for r in records)
    print(f"{len(records)} explicaciones, {claims} afirmaciones de {annotator}")
    if not args.dry_run:
        store = ReviewStore(args.corpus_dir / "reviews")
        for record in records:
            store.save_claim_review(record)
        print(f"guardado en {store.claims_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
