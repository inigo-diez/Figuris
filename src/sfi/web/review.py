"""Review API (Stage 5): check SFI-48 reference boxes and score explanations.

Box and panel review are blind to the system: these endpoints read the reference,
the local PDF and JATS of the corpus and the images published by PMC, never the
figures or panels our extractor found. Explanation scoring reads the analyses of the local database.
Annotations are written to ``<corpus_dir>/reviews/`` (sfi.review).
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable

import pypdfium2 as pdfium
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from sfi.analysis.schema import FigureAnalysis
from sfi.config import Settings
from sfi.domain.models import Document, Figure
from sfi.extract.panels import parse_subcaptions
from sfi.extract.render import render_page_png
from sfi.review import (
    BOX_DECISIONS,
    CRITICAL_ERRORS,
    PANEL_DECISIONS,
    RUBRIC,
    RUBRIC_VERSION,
    ReviewError,
    ReviewStore,
    apply_box_reviews,
    check_annotator,
    check_box,
    check_scores,
    claim_is_scored,
    figure_key,
    now,
)
from sfi.storage.repository import SQLiteRepository
from sfi.web.deps import PAGE_DPI, Repo, render_lock, short_id

XLINK = "{http://www.w3.org/1999/xlink}"
IMAGE_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".gif": "image/gif"}

FiguresOf = Callable[[SQLiteRepository, Document], list[Figure]]


class BoxReviewIn(BaseModel):
    pmcid: str
    figure: str = Field(description="Reference key: JATS id, or 'label:<label>'")
    annotator: str
    decision: str
    page: int | None = None
    bbox: list[float] | None = None
    note: str | None = Field(default=None, max_length=2000)
    label: str | None = Field(default=None, max_length=80)
    proposal_shown: bool = False


class PanelBoxIn(BaseModel):
    label: str = Field(max_length=4)
    bbox: list[float] | None = None
    absent: bool = False  # named by the caption but not printed in the figure


# A letter the reviewer adds: a, B, aa, or a roman numeral (i, iv...).
PANEL_LETTER = re.compile(r"^(?:[A-Za-z]{1,2}|[ivx]{1,4})$")


class PanelReviewIn(BaseModel):
    pmcid: str
    figure: str
    annotator: str
    decision: str
    panels: list[PanelBoxIn] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=2000)


class ClaimScoresIn(BaseModel):
    scores: dict[str, int | str] = Field(default_factory=dict)
    critical: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class ExplanationReviewIn(BaseModel):
    annotator: str
    analysis: str = Field(description="Key returned by GET: the explanation being scored")
    claims: dict[str, ClaimScoresIn]
    comment: str | None = Field(default=None, max_length=4000)


def text_of(element) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def label_pattern(label: str) -> re.Pattern:
    """'Figure 3' -> matches 'Figure 3', 'Fig. 3', 'FIG 3' but not 'Figure 30'."""
    number = label.split()[-1]
    return re.compile(rf"\bfig(?:ure|s?\.)?\s*{re.escape(number)}(?![0-9])", re.IGNORECASE)


def analysis_key(analysis: FigureAnalysis) -> str:
    """Scores belong to the explanation content, which a reused analysis shares."""
    return analysis.reused_from or analysis.id


def create_review_router(settings: Settings, document_figures: FiguresOf) -> APIRouter:
    router = APIRouter(prefix="/api/review")
    store = ReviewStore(settings.corpus_dir / "reviews")
    raw = settings.corpus_raw_dir
    cache: dict = {}

    # --- corpus files ------------------------------------------------------------------

    def reference() -> dict | None:
        path = settings.corpus_dir / "expected_figures.json"
        if not path.exists():
            return None
        stamp = path.stat().st_mtime
        if cache.get("reference_stamp") != stamp:
            cache["reference"] = json.loads(path.read_text(encoding="utf-8"))
            cache["reference_stamp"] = stamp
        return cache["reference"]

    def require_reference() -> dict:
        ref = reference()
        if ref is None:
            raise HTTPException(404, "No se encuentra la referencia de SFI-48.")
        return ref

    def article(pmcid: str) -> dict:
        for item in require_reference()["articles"]:
            if item["pmcid"] == pmcid:
                if not (raw / f"{pmcid}.pdf").exists():
                    raise HTTPException(
                        404, f"Falta el PDF de {pmcid} en {raw}. Descarga el corpus primero."
                    )
                return item
        raise HTTPException(404, "Artículo no encontrado en SFI-48.")

    def jats(pmcid: str) -> dict[str, dict]:
        """Caption and image file of each JATS figure, by figure id."""
        key = ("jats", pmcid)
        if key not in cache:
            figures = {}
            path = raw / f"{pmcid}.xml"
            if path.exists():
                root = ET.parse(path).getroot()
                for fig in root.iter("fig"):
                    graphic = fig.find(".//graphic")
                    href = graphic.get(f"{XLINK}href") if graphic is not None else None
                    if href and not href.lower().endswith((".jpg", ".png", ".gif", ".tif")):
                        href = f"{href}.jpg"
                    figures[fig.get("id")] = {"caption": text_of(fig.find("caption")), "href": href}
            cache[key] = figures
        return cache[key]

    def page_texts(pmcid: str) -> list[str]:
        key = ("text", pmcid)
        if key not in cache:
            with render_lock:
                pdf = pdfium.PdfDocument(raw / f"{pmcid}.pdf")
                try:
                    texts = []
                    for page in pdf:
                        textpage = page.get_textpage()
                        texts.append(textpage.get_text_range())
                        textpage.close()
                finally:
                    pdf.close()
            cache[key] = texts
        return cache[key]

    def label_pages(pmcid: str, label: str | None) -> list[dict]:
        """Pages whose text contains the label; caption-like when it starts a line."""
        if not label:
            return []
        pattern = label_pattern(label)
        out = []
        for index, text in enumerate(page_texts(pmcid)):
            matches = list(pattern.finditer(text))
            if matches:
                starts = any(m.start() == 0 or text[m.start() - 1] in "\r\n" for m in matches)
                out.append({"page": index + 1, "caption_like": starts})
        return out

    def figure_entry(item: dict, key: str) -> dict | None:
        return next((f for f in item["figures"] if figure_key(f) == key), None)

    def reason(figure: dict, pdf_kind: str | None) -> str:
        if figure.get("review_status") == "auto":
            return "auto"
        if figure.get("jats_id") is None:
            return "scanned" if pdf_kind == "scanned" else "no_jats"
        return "low_score" if figure.get("bbox") else "not_located"

    def pmcid_by_sha() -> dict[str, str]:
        if "sha" not in cache:
            mapping = {}
            for path in raw.glob("PMC*.pdf") if raw.exists() else []:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                mapping[f"sha256:{digest}"] = path.stem
            cache["sha"] = mapping
        return cache["sha"]

    def splits() -> dict[str, str]:
        ref = reference()
        return {a["pmcid"]: a["split"] for a in ref["articles"]} if ref else {}

    # --- reference boxes ---------------------------------------------------------------

    @router.get("/boxes")
    def list_boxes(annotator: str | None = None) -> dict:
        ref = reference()
        if ref is None:
            return {"available": False, "message": "No se encuentra la referencia de SFI-48."}
        if not raw.exists():
            return {
                "available": False,
                "message": f"Faltan los PDF del corpus en {raw}. Descárgalos con "
                "scripts/corpus/fetch_pmc_oa.py (ver data/sfi48/README.md).",
            }
        reviews = store.box_reviews()
        by_item: dict[tuple, list[dict]] = {}
        for review in reviews:
            by_item.setdefault((review["pmcid"], review["figure"]), []).append(review)

        def box_item(item, figure, key, found, added=False) -> dict:
            mine = next((r for r in found if r["annotator"] == annotator), None)
            return {
                "pmcid": item["pmcid"],
                "key": key,
                "label": figure.get("label"),
                "split": item["split"],
                "stratum": item.get("stratum"),
                "pdf_kind": item.get("pdf_kind"),
                "reason": "added" if added else reason(figure, item.get("pdf_kind")),
                "match_score": figure.get("match_score"),
                "needs_review": added or figure.get("review_status") != "auto",
                "mine": mine["decision"] if mine else None,
                "reviewers": len(found),
            }

        items = []
        for item in ref["articles"]:
            keys = set()
            for figure in item["figures"]:
                key = figure_key(figure)
                keys.add(key)
                items.append(box_item(item, figure, key, by_item.get((item["pmcid"], key), [])))
            for (pmcid, key), found in by_item.items():
                if pmcid == item["pmcid"] and key not in keys:  # added by a reviewer
                    figure = {"jats_id": None, "label": found[0].get("label")}
                    items.append(box_item(item, figure, key, found, added=True))

        return {
            "available": True,
            "reference_version": ref["version"],
            "decisions": list(BOX_DECISIONS),
            "items": items,
        }

    @router.get("/box")
    def box_detail(pmcid: str, figure: str, annotator: str | None = None) -> dict:
        item = article(pmcid)
        entry = figure_entry(item, figure)
        mine = next(
            (
                r
                for r in store.box_reviews()
                if (r["pmcid"], r["figure"], r["annotator"]) == (pmcid, figure, annotator)
            ),
            None,
        )
        if entry is None:  # a figure the reference does not list, added by a reviewer
            label = figure.removeprefix("label:").strip()
            if not figure.startswith("label:") or not label:
                raise HTTPException(404, "Figura no encontrada en la referencia.")
            entry = {"jats_id": None, "label": label}
        source = jats(pmcid).get(entry.get("jats_id") or "", {})
        image = source.get("href")
        located = entry.get("bbox") is not None
        return {
            "pmcid": pmcid,
            "key": figure,
            "label": entry.get("label"),
            "split": item["split"],
            "stratum": item.get("stratum"),
            "pdf_kind": item.get("pdf_kind"),
            "pages": item["pages"],
            "reason": reason(entry, item.get("pdf_kind")) if "review_status" in entry else "added",
            "caption": source.get("caption") or None,
            "has_image": bool(image and (raw / "figures" / pmcid / image).exists()),
            "proposal": {
                "page": entry["page"],
                "bbox": entry["bbox"],
                "score": entry.get("match_score"),
            }
            if located
            else None,
            "label_pages": label_pages(pmcid, entry.get("label")),
            "review": mine,
        }

    @router.put("/box")
    def save_box(body: BoxReviewIn) -> dict:
        try:
            annotator = check_annotator(body.annotator)
            item = article(body.pmcid)
            entry = figure_entry(item, body.figure)
            label = entry.get("label") if entry else None
            if entry is None:
                if not body.figure.startswith("label:") or not (body.label or "").strip():
                    raise ReviewError("Figura no encontrada en la referencia.")
                label = body.label.strip()
                if body.figure != f"label:{label}":
                    raise ReviewError("La clave de una figura añadida debe ser 'label:<etiqueta>'.")
            if body.decision not in BOX_DECISIONS:
                raise ReviewError(f"Decisión desconocida: {body.decision!r}.")
            page = bbox = None
            if body.decision == "box":
                if body.page is None or not 1 <= body.page <= item["pages"]:
                    raise ReviewError("Página fuera de rango.")
                page, bbox = body.page, check_box(body.bbox)
            if body.decision == "unclear" and not (body.note or "").strip():
                raise ReviewError("Explica en una nota por qué es dudosa.")
        except ReviewError as exc:
            raise HTTPException(400, str(exc)) from exc
        record = {
            "pmcid": body.pmcid,
            "figure": body.figure,
            "label": label,
            "annotator": annotator,
            "decision": body.decision,
            "page": page,
            "bbox": bbox,
            "note": (body.note or "").strip() or None,
            "proposal_shown": body.proposal_shown,
            "reference_version": require_reference()["version"],
            "reviewed_at": now(),
        }
        return store.save_box_review(record)

    @router.delete("/box")
    def delete_box(pmcid: str, figure: str, annotator: str) -> dict:
        if not store.delete_box_review(pmcid, figure, annotator):
            raise HTTPException(404, "No hay revisión que borrar.")
        return {"deleted": True}

    @router.get("/articles/{pmcid}/pages/{number}")
    def corpus_page(pmcid: str, number: int):
        item = article(pmcid)
        if not 1 <= number <= item["pages"]:
            raise HTTPException(404, "Página fuera de rango.")
        target = settings.data_dir / "pages" / "sfi48" / pmcid / f"p{number}-{PAGE_DPI}.png"
        if not target.exists():
            with render_lock:
                if not target.exists():
                    pdf = pdfium.PdfDocument(raw / f"{pmcid}.pdf")
                    try:
                        png = render_page_png(pdf[number - 1], PAGE_DPI)
                    finally:
                        pdf.close()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(png)
        return FileResponse(
            target, media_type="image/png", headers={"Cache-Control": "max-age=86400"}
        )

    @router.get("/articles/{pmcid}/figure-image")
    def published_image(pmcid: str, figure: str):
        """The figure image PMC publishes for the article (what the reviewer looks for)."""
        item = article(pmcid)
        entry = figure_entry(item, figure)
        href = jats(pmcid).get((entry or {}).get("jats_id") or "", {}).get("href")
        path = raw / "figures" / pmcid / href if href else None
        if path is None or not path.exists() or path.suffix.lower() not in IMAGE_TYPES:
            raise HTTPException(404, "No hay imagen publicada para esta figura.")
        return FileResponse(path, media_type=IMAGE_TYPES[path.suffix.lower()])

    # --- panels ------------------------------------------------------------------------

    def panel_figures() -> list[tuple[dict, dict, list[tuple[str, str]]]]:
        """Multipanel figures with a reliable box: (article, figure, [(letter, text)])."""
        ref = reference()
        if ref is None:
            return []
        out = []
        for item in apply_box_reviews(ref, store.box_reviews())["articles"]:
            if not (raw / f"{item['pmcid']}.xml").exists():
                continue
            captions = jats(item["pmcid"])
            for figure in item["figures"]:
                if figure["review_status"] not in ("auto", "reviewed") or not figure.get("bbox"):
                    continue
                caption = captions.get(figure.get("jats_id") or "", {}).get("caption", "")
                letters = [
                    (x, sub.text) for sub in parse_subcaptions(caption)[1] for x in sub.labels
                ]
                if len(letters) >= 2:
                    out.append((item, figure, letters))
        return out

    def panel_figure(pmcid: str, key: str):
        article(pmcid)  # 404 if the article or its PDF is missing
        for item, figure, letters in panel_figures():
            if item["pmcid"] == pmcid and figure_key(figure) == key:
                return item, figure, letters
        raise HTTPException(404, "Figura multipanel no encontrada en la referencia.")

    @router.get("/panels")
    def list_panels(annotator: str | None = None) -> dict:
        if reference() is None or not raw.exists():
            return {"available": False, "message": "Faltan la referencia o los PDF de SFI-48."}
        by_item: dict[tuple, list[dict]] = {}
        for review in store.panel_reviews():
            by_item.setdefault((review["pmcid"], review["figure"]), []).append(review)
        items = []
        for item, figure, letters in panel_figures():
            key = figure_key(figure)
            found = by_item.get((item["pmcid"], key), [])
            mine = next((r for r in found if r["annotator"] == annotator), None)
            items.append(
                {
                    "pmcid": item["pmcid"],
                    "key": key,
                    "label": figure["label"],
                    "split": item["split"],
                    "letters": "".join(x for x, _ in letters),
                    "mine": mine["decision"] if mine else None,
                    "reviewers": len(found),
                }
            )
        return {"available": True, "items": items}

    @router.get("/panel")
    def panel_detail(pmcid: str, figure: str, annotator: str | None = None) -> dict:
        item, entry, letters = panel_figure(pmcid, figure)
        mine = next(
            (
                r
                for r in store.panel_reviews()
                if (r["pmcid"], r["figure"], r["annotator"]) == (pmcid, figure, annotator)
            ),
            None,
        )
        return {
            "pmcid": pmcid,
            "key": figure,
            "label": entry["label"],
            "split": item["split"],
            "pages": item["pages"],
            "page": entry["page"],
            "figure_box": entry["bbox"],
            "panels": [{"label": x, "subcaption": text, "added": False} for x, text in letters]
            + [
                {"label": p["label"], "subcaption": "", "added": True}
                for p in (mine or {}).get("panels", [])
                if p.get("added")
            ],
            "review": mine,
        }

    @router.put("/panel")
    def save_panel(body: PanelReviewIn) -> dict:
        item, entry, letters = panel_figure(body.pmcid, body.figure)
        from_caption = [x for x, _ in letters]
        try:
            annotator = check_annotator(body.annotator)
            if body.decision not in PANEL_DECISIONS:
                raise ReviewError(f"Decisión desconocida: {body.decision!r}.")
            labels = [p.label for p in body.panels]
            if len(set(labels)) != len(labels):
                raise ReviewError("Cada letra de panel debe aparecer una sola vez.")
            added = [x for x in labels if x not in from_caption]
            if bad := [x for x in added if not PANEL_LETTER.match(x)]:
                raise ReviewError(f"Letra de panel no válida: {', '.join(bad)}.")
            absent = [p.label for p in body.panels if p.absent]
            if any(p.absent and p.bbox is not None for p in body.panels):
                raise ReviewError("Una letra marcada como «no existe» no puede tener caja.")
            if bad := [x for x in absent if x not in from_caption]:
                raise ReviewError(
                    f"Solo se marcan como «no existe» letras del pie: {', '.join(bad)}."
                )
            boxes = {p.label: check_box(p.bbox) for p in body.panels if p.bbox is not None}
            fx0, fy0, fx1, fy1 = entry["bbox"]
            for label, (x0, y0, x1, y1) in boxes.items():
                if x1 <= fx0 or x0 >= fx1 or y1 <= fy0 or y0 >= fy1:
                    raise ReviewError(f"La caja del panel {label} está fuera de la figura.")
            if body.decision == "done" and not boxes:
                raise ReviewError("Dibuja al menos un panel o marca la figura como dudosa.")
            if body.decision == "unclear" and not (body.note or "").strip():
                raise ReviewError("Explica en una nota por qué es dudosa.")
        except ReviewError as exc:
            raise HTTPException(400, str(exc)) from exc
        record = {
            "pmcid": body.pmcid,
            "figure": body.figure,
            "label": entry["label"],
            "annotator": annotator,
            "decision": body.decision,
            "page": entry["page"],
            # Letters of the caption first, then letters the reviewer added; the reviewer
            # is not limited to what the caption parser found.
            "panels": [
                {"label": x, "bbox": boxes.get(x), "absent": x in absent} for x in from_caption
            ]
            + [{"label": x, "bbox": boxes.get(x), "added": True} for x in added],
            "letters_added": added,
            "letters_absent": absent,
            "note": (body.note or "").strip() or None,
            "reference_version": require_reference()["version"],
            "reviewed_at": now(),
        }
        return store.save_panel_review(record)

    # --- explanations ------------------------------------------------------------------

    def rubric_json() -> dict:
        return {
            "version": RUBRIC_VERSION,
            "criteria": [
                {
                    "id": c.id,
                    "name": c.name,
                    "question": c.question,
                    "levels": list(c.levels),
                    "allows_na": c.allows_na,
                }
                for c in RUBRIC
            ],
            "critical_errors": CRITICAL_ERRORS,
        }

    def find_figure(repo: SQLiteRepository, document_id: str, figure_id: str):
        found = repo.find_documents(document_id) if len(document_id) >= 8 else []
        if len(found) != 1:
            raise HTTPException(404, "Documento no encontrado.")
        figure = next((f for f in document_figures(repo, found[0]) if f.id == figure_id), None)
        analysis = repo.latest_analysis(figure.id) if figure else None
        if analysis is None or analysis.explanation is None:
            raise HTTPException(404, "Esta figura no tiene explicación que puntuar.")
        return found[0], figure, analysis

    @router.get("/explanations")
    def list_explanations(repo: Repo, annotator: str | None = None) -> dict:
        mine = {r["analysis"]: r for r in store.claim_reviews() if r["annotator"] == annotator}
        by_sha, split_of = pmcid_by_sha(), splits()
        items = []
        for document in reversed(repo.find_documents()):
            pmcid = by_sha.get(document.id)
            for figure in document_figures(repo, document):
                analysis = repo.latest_analysis(figure.id)
                if analysis is None or analysis.explanation is None:
                    continue
                key = analysis_key(analysis)
                review = mine.get(key)
                items.append(
                    {
                        "document_id": short_id(document.id),
                        "figure_id": figure.id,
                        "filename": document.filename,
                        "pmcid": pmcid,
                        "split": split_of.get(pmcid),
                        "label": figure.label,
                        "page": figure.page_index + 1,
                        "status": analysis.status.value,
                        "claims": len(analysis.explanation.claims),
                        "scored": sum(1 for c in review["claims"] if claim_is_scored(c))
                        if review
                        else 0,
                        "critical": sum(1 for c in review["claims"] if c.get("critical"))
                        if review
                        else 0,
                    }
                )
        return {"rubric": rubric_json(), "items": items}

    @router.get("/explanations/{document_id}/{figure_id}")
    def explanation_review(
        document_id: str, figure_id: str, repo: Repo, annotator: str | None = None
    ) -> dict:
        _, _, analysis = find_figure(repo, document_id, figure_id)
        key = analysis_key(analysis)
        review = next(
            (
                r
                for r in store.claim_reviews()
                if r["analysis"] == key and r["annotator"] == annotator
            ),
            None,
        )
        return {"analysis": key, "rubric": rubric_json(), "review": review}

    @router.put("/explanations/{document_id}/{figure_id}")
    def save_explanation_review(
        document_id: str, figure_id: str, body: ExplanationReviewIn, repo: Repo
    ) -> dict:
        document, figure, analysis = find_figure(repo, document_id, figure_id)
        key = analysis_key(analysis)
        if body.analysis != key:
            raise HTTPException(409, "La explicación ha cambiado: recarga la página.")
        claims = {c.id: c for c in analysis.explanation.claims}
        try:
            annotator = check_annotator(body.annotator)
            unknown = set(body.claims) - set(claims)
            if unknown:
                raise ReviewError(f"Afirmaciones desconocidas: {', '.join(sorted(unknown))}.")
            scored = []
            for claim_id, claim in claims.items():
                given = body.claims.get(claim_id) or ClaimScoresIn()
                if given.critical is not None and given.critical not in CRITICAL_ERRORS:
                    raise ReviewError(f"Error crítico desconocido: {given.critical!r}.")
                scored.append(
                    {
                        "id": claim_id,
                        "type": claim.type,
                        "confidence": claim.confidence,
                        "text": claim.text,
                        "scores": check_scores(given.scores),
                        "critical": given.critical,
                        "note": (given.note or "").strip() or None,
                    }
                )
        except ReviewError as exc:
            raise HTTPException(400, str(exc)) from exc
        run = analysis.run
        pmcid = pmcid_by_sha().get(document.id)
        record = {
            "analysis": key,
            "annotator": annotator,
            "document_sha256": document.id.removeprefix("sha256:"),
            "filename": document.filename,
            "pmcid": pmcid,
            "split": splits().get(pmcid),
            "figure_label": figure.label,
            "page": figure.page_index + 1,
            "explanation_status": analysis.status.value,
            "model": (run.model_version or run.model) if run else None,
            "prompt_version": run.prompt_version if run else None,
            "schema_version": analysis.schema_version,
            "rubric_version": RUBRIC_VERSION,
            "comment": (body.comment or "").strip() or None,
            "claims": scored,
            "scored_at": now(),
        }
        return store.save_claim_review(record)

    return router
