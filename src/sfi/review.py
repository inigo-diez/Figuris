"""Human review for Stage 5: reference boxes of SFI-48 and rubric scores of explanations.

Three kinds of annotation, stored as versioned JSON next to the reference
(``data/sfi48/reviews/``), one record per item and annotator:

- ``boxes.json``: a person checks where each doubtful reference figure is on the PDF
  page (or says it is not there, or that it is unclear). The review screen shows the
  page, the JATS caption and the image published by PMC, never the system's
  extraction (research/experiments.md, annotation protocol, step 4).
- ``panels.json``: the box of each panel (a, b, c...) of a multipanel figure, drawn
  on the page without seeing the system's panels; the panel gold of E02.
- ``claims.json``: each claim of an explanation scored 0-2 on the six criteria of
  the human rubric (docs/EVALUATION_PLAN.md), plus critical errors.

Records keep enough provenance (reference version, model, prompt version, claim
text) to be read without the local database. ``apply_box_reviews`` turns the box
reviews into an updated reference for the evaluation scripts; the automatic
reference file itself is never edited.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

BOX_SCHEMA = "sfi48-box-reviews/1"
PANEL_SCHEMA = "sfi48-panel-reviews/1"
PANEL_DECISIONS = ("done", "unclear")
CLAIM_SCHEMA = "sfi-claim-reviews/1"
RUBRIC_VERSION = "rubric/1"
BOX_DECISIONS = ("box", "absent", "unclear")
AGREEMENT_IOU = 0.75  # two reviews of the same figure agree when their boxes overlap this much
ANNOTATOR = re.compile(r"^[\w][\w .-]{0,39}$")


@dataclass(frozen=True)
class Criterion:
    id: str
    name: str
    question: str
    levels: tuple[str, str, str]
    allows_na: bool = False


RUBRIC = (
    Criterion(
        "correctness",
        "Corrección",
        "¿Es verdad según la figura, el pie y el texto del artículo?",
        ("falsa", "en parte", "correcta"),
    ),
    Criterion(
        "support",
        "Respaldo",
        "¿La evidencia que acompaña a la afirmación basta para hacerla?",
        ("sin respaldo", "parcial", "respaldada"),
    ),
    Criterion(
        "citation",
        "Cita",
        "¿La cita (pie o texto) existe, está en el sitio indicado y dice lo que se afirma? "
        "N/A si la afirmación solo se apoya en la imagen.",
        ("errónea", "imprecisa", "exacta"),
        allows_na=True,
    ),
    Criterion(
        "claim_type",
        "Tipo",
        "¿Es correcto marcarla como observado, según los autores, inferencia o incierto?",
        ("equivocado", "discutible", "correcto"),
    ),
    Criterion(
        "calibration",
        "Calibración",
        "¿La seguridad con que se expresa corresponde a la evidencia, sin falsa certeza "
        "ni dudas injustificadas?",
        ("mal calibrada", "algo", "bien calibrada"),
    ),
    Criterion(
        "usefulness",
        "Utilidad",
        "¿Ayuda a entender la figura?",
        ("no aporta", "algo", "útil"),
    ),
)
CRITICAL_ERRORS = {
    "invented_reference": "ID, cita o referencia inventada",
    "fabricated_value": "Valor inventado",
    "contradiction": "Contradice la figura o el artículo",
    "false_certainty": "Falsa certeza (p. ej., clínica)",
}


class ReviewError(ValueError):
    """A review that cannot be stored as sent."""


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def figure_key(figure: dict) -> str:
    """Stable key of a reference figure: its JATS id, or its label when it has none."""
    return figure.get("jats_id") or f"label:{figure['label']}"


def check_annotator(annotator: str) -> str:
    annotator = (annotator or "").strip()
    if not ANNOTATOR.match(annotator):
        raise ReviewError("Indica un nombre de revisor (letras, números, espacios, . o -).")
    return annotator


def check_box(bbox) -> list[float]:
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        raise ReviewError("La caja debe tener cuatro coordenadas.")
    x0, y0, x1, y1 = (round(float(v), 4) for v in bbox)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ReviewError("La caja debe estar dentro de la página y tener tamaño.")
    if (x1 - x0) < 0.01 or (y1 - y0) < 0.01:
        raise ReviewError("La caja es demasiado pequeña.")
    return [x0, y0, x1, y1]


def check_scores(scores: dict) -> dict:
    """Scores of one claim: each criterion 0, 1, 2 (or 'na' where allowed); missing = unscored."""
    out = {}
    for criterion in RUBRIC:
        value = scores.get(criterion.id)
        if value is None:
            continue
        if value == "na" and criterion.allows_na:
            out[criterion.id] = "na"
        elif value in (0, 1, 2) and not isinstance(value, bool):
            out[criterion.id] = value
        else:
            raise ReviewError(f"Valor no válido para «{criterion.name}»: {value!r}.")
    unknown = set(scores) - {c.id for c in RUBRIC}
    if unknown:
        raise ReviewError(f"Criterios desconocidos: {', '.join(sorted(unknown))}.")
    return out


def claim_is_scored(claim: dict) -> bool:
    return all(c.id in claim.get("scores", {}) for c in RUBRIC)


def box_iou(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


class ReviewStore:
    """JSON files with one record per (item, annotator), written atomically."""

    _lock = threading.Lock()  # shared: the web app serves requests from several threads

    def __init__(self, directory: Path):
        self.directory = directory
        self.boxes_path = directory / "boxes.json"
        self.claims_path = directory / "claims.json"
        self.panels_path = directory / "panels.json"

    # --- reference boxes ---------------------------------------------------------------

    def box_reviews(self) -> list[dict]:
        return self._read(self.boxes_path)

    def save_box_review(self, record: dict) -> dict:
        key = ("pmcid", "figure", "annotator")
        with self._lock:
            reviews = [
                r for r in self._read(self.boxes_path) if any(r[k] != record[k] for k in key)
            ]
            reviews.append(record)
            reviews.sort(key=lambda r: (r["pmcid"], r["figure"], r["annotator"]))
            self._write(self.boxes_path, BOX_SCHEMA, reviews)
        return record

    def delete_box_review(self, pmcid: str, figure: str, annotator: str) -> bool:
        with self._lock:
            reviews = self._read(self.boxes_path)
            kept = [
                r
                for r in reviews
                if (r["pmcid"], r["figure"], r["annotator"]) != (pmcid, figure, annotator)
            ]
            if len(kept) == len(reviews):
                return False
            self._write(self.boxes_path, BOX_SCHEMA, kept)
            return True

    # --- panels ------------------------------------------------------------------------

    def panel_reviews(self) -> list[dict]:
        return self._read(self.panels_path)

    def save_panel_review(self, record: dict) -> dict:
        key = ("pmcid", "figure", "annotator")
        with self._lock:
            reviews = [
                r for r in self._read(self.panels_path) if any(r[k] != record[k] for k in key)
            ]
            reviews.append(record)
            reviews.sort(key=lambda r: (r["pmcid"], r["figure"], r["annotator"]))
            self._write(self.panels_path, PANEL_SCHEMA, reviews)
        return record

    # --- explanation claims ------------------------------------------------------------

    def claim_reviews(self) -> list[dict]:
        return self._read(self.claims_path)

    def save_claim_review(self, record: dict) -> dict:
        with self._lock:
            reviews = [
                r
                for r in self._read(self.claims_path)
                if (r["analysis"], r["annotator"]) != (record["analysis"], record["annotator"])
            ]
            reviews.append(record)
            reviews.sort(key=lambda r: (r.get("filename") or "", r["analysis"], r["annotator"]))
            self._write(self.claims_path, CLAIM_SCHEMA, reviews)
        return record

    # --- files -------------------------------------------------------------------------

    @staticmethod
    def _read(path: Path) -> list[dict]:
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))["reviews"]

    def _write(self, path: Path, schema: str, reviews: list[dict]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        body = {"schema": schema, "updated_at": now(), "reviews": reviews}
        if schema == CLAIM_SCHEMA:
            body["rubric"] = {
                "version": RUBRIC_VERSION,
                "criteria": {c.id: c.name for c in RUBRIC},
                "critical_errors": CRITICAL_ERRORS,
            }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", "utf-8")
        os.replace(temporary, path)


def resolve_box_reviews(reviews: list[dict]) -> dict:
    """What the reviews of one figure establish: decision, page and box, or a dispute."""
    reviews = sorted(reviews, key=lambda r: r["reviewed_at"])
    first = reviews[0]
    agree = all(r["decision"] == first["decision"] for r in reviews)
    if agree and first["decision"] == "box":
        agree = all(
            r["page"] == first["page"] and box_iou(r["bbox"], first["bbox"]) >= AGREEMENT_IOU
            for r in reviews[1:]
        )
    if not agree:
        return {"decision": "disputed"}
    return {k: first.get(k) for k in ("decision", "page", "bbox", "label")}


def apply_box_reviews(reference: dict, reviews: list[dict]) -> dict:
    """A copy of the reference with the box reviews applied.

    - ``box``: the figure gets the reviewed page and box (``review_status: reviewed``);
    - ``absent``: the figure is not in the PDF and leaves the reference (listed in
      ``removed_by_review``);
    - ``unclear``: kept, but excluded from box metrics like ``needs_manual``;
    - reviews of the same figure that disagree leave it ``disputed`` until adjudicated;
    - a reviewed figure the reference did not list (``label:...`` key, scanned
      articles) is added with ``source: review``.
    """
    out = copy.deepcopy(reference)
    grouped: dict[tuple[str, str], list[dict]] = {}
    for review in reviews:
        grouped.setdefault((review["pmcid"], review["figure"]), []).append(review)
    for article in out["articles"]:
        kept, removed = [], []
        keys = set()
        for figure in article["figures"]:
            key = figure_key(figure)
            keys.add(key)
            found = grouped.get((article["pmcid"], key))
            if not found:
                kept.append(figure)
                continue
            result = resolve_box_reviews(found)
            figure["reviewed_by"] = sorted({r["annotator"] for r in found})
            if result["decision"] == "absent":
                removed.append(figure["label"] or key)
                continue
            if result["decision"] == "box":
                figure.update(page=result["page"], bbox=result["bbox"], review_status="reviewed")
            else:
                figure["review_status"] = result["decision"]
            kept.append(figure)
        for (pmcid, key), found in sorted(grouped.items()):
            if pmcid != article["pmcid"] or key in keys:
                continue
            result = resolve_box_reviews(found)
            if result["decision"] in ("box", "unclear", "disputed"):
                kept.append(
                    {
                        "jats_id": None,
                        "label": result.get("label") or key.removeprefix("label:"),
                        "source": "review",
                        "page": result.get("page"),
                        "bbox": result.get("bbox"),
                        "review_status": "reviewed"
                        if result["decision"] == "box"
                        else result["decision"],
                        "reviewed_by": sorted({r["annotator"] for r in found}),
                    }
                )
        article["figures"] = kept
        if removed:
            article["removed_by_review"] = removed
    figures = [f for a in out["articles"] for f in a["figures"]]
    statuses = ("auto", "reviewed", "needs_manual", "unclear", "disputed")
    out["summary"] = {
        "articles": len(out["articles"]),
        "figures": len(figures),
        **{s: sum(1 for f in figures if f["review_status"] == s) for s in statuses},
        "removed_by_review": sum(len(a.get("removed_by_review", [])) for a in out["articles"]),
        "multipanel_from_caption": reference["summary"].get("multipanel_from_caption"),
    }
    out["box_reviews"] = {"applied": len(reviews), "agreement_iou": AGREEMENT_IOU}
    return out


def load_reference(corpus_dir: Path, reviewed: bool = True) -> dict:
    """The SFI-48 reference, with the human box reviews applied unless ``reviewed=False``."""
    reference = json.loads((corpus_dir / "expected_figures.json").read_text(encoding="utf-8"))
    if not reviewed:
        return reference
    return apply_box_reviews(reference, ReviewStore(corpus_dir / "reviews").box_reviews())
