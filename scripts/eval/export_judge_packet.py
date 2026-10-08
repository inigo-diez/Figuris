"""Export explanations for an external reviewer (another AI) to score with the rubric.

Writes, for a fixed random sample of explanations from the local database (one
figure per document), printable batches with everything the reviewer needs: the
figure image, its caption, the article passages the model received, and each
claim with its evidence. The first page explains the rubric and the exact JSON to
return. A keys file maps each item to its explanation, so the answer can be
imported with scripts/eval/import_judge_scores.py.

It also writes a ``revisor_lote_N/`` folder per batch for an agent that reads files
but must not run anything: INSTRUCCIONES.md, one Markdown file per explanation and
the figure as a PNG next to it. The agent returns that batch's JSON answer.

Scores given by another model are an LLM judgement, not human gold: they are
stored with ``annotator_kind: llm`` and reported apart from human scores.

Batches contain article figures and text (all SFI-48 articles are CC BY); they are
written under data/local/, which is not versioned.

Usage:
    python scripts/eval/export_judge_packet.py [--per-batch 5] [--limit 15]
        [--split validation] [--per-document 2] [--out DIR]
Needs playwright (and Chrome or Edge) for the PDF; the HTML is always written.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import io
import json
import random
import re
from pathlib import Path

from PIL import Image

from sfi.analysis.prompt import _WARNING_NOTES
from sfi.config import Settings
from sfi.domain.models import WarningCode
from sfi.review import CRITICAL_ERRORS, RUBRIC
from sfi.storage.blobs import LocalBlobStore
from sfi.storage.repository import SQLiteRepository

ROOT = Path(__file__).resolve().parents[2]
SEED = 20261007
TYPES = {
    "observed": ("observado", "se ve en la imagen de la figura"),
    "author_stated": ("según los autores", "lo dicen el pie o el texto del artículo"),
    "model_inference": ("inferencia", "deducción del modelo; el artículo no lo afirma"),
    "uncertain": ("incierto", "no se puede determinar con la evidencia disponible"),
}
# Keys the reviewer writes (Spanish, short) -> rubric ids.
CRITERIA_KEYS = {
    "correccion": "correctness",
    "respaldo": "support",
    "cita": "citation",
    "tipo": "claim_type",
    "calibracion": "calibration",
    "utilidad": "usefulness",
}
CRITICAL_KEYS = {
    "referencia_inventada": "invented_reference",
    "valor_inventado": "fabricated_value",
    "contradiccion": "contradiction",
    "falsa_certeza": "false_certainty",
}


def extraction_notes(document, figure) -> str:
    """The extraction notes the model was given with this figure (see analysis.prompt)."""
    codes = {w.code for w in figure.warnings}
    if document.pages[figure.page_index].is_scanned:
        codes.add(WarningCode.SCANNED_PAGE)
    return " ".join(note for code, note in _WARNING_NOTES.items() if code in codes)


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def image_data_uri(path: Path, long_side: int = 1400) -> str:
    image = Image.open(path).convert("RGB")
    image.thumbnail((long_side, long_side))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def pmcid_of(document) -> str | None:
    match = re.match(r"PMC\d+", Path(document.filename).stem)
    return match.group(0) if match else None


def sample(
    repository: SQLiteRepository,
    limit: int,
    per_document: int = 1,
    split: str | None = None,
    manifest: dict | None = None,
) -> list[tuple]:
    """A fixed random sample: ``per_document`` explained figures of each document."""
    rng = random.Random(SEED)
    chosen = []
    for document in sorted(repository.find_documents(), key=lambda d: d.filename):
        if split and (manifest or {}).get(pmcid_of(document), {}).get("split") != split:
            continue
        run = repository.latest_completed_run(document.id)
        if not run:
            continue
        candidates = []
        for figure in repository.list_figures(run.id):
            analysis = repository.latest_analysis(figure.id)
            if analysis and analysis.explanation and figure.crop_artifact_id:
                candidates.append((document, figure, analysis))
        chosen.extend(rng.sample(candidates, min(per_document, len(candidates))))
    rng.shuffle(chosen)
    return chosen[:limit]


def instructions(batch: int, batches: int, ids: list[str]) -> str:
    rows = "".join(
        f"<tr><td><code>{key}</code></td><td><b>{esc(c.name)}</b>: {esc(c.question)}</td>"
        f"<td>0 = {esc(c.levels[0])}<br>1 = {esc(c.levels[1])}<br>2 = {esc(c.levels[2])}"
        f"{'<br>NA = no aplica' if c.allows_na else ''}</td></tr>"
        for key, c in ((k, next(c for c in RUBRIC if c.id == v)) for k, v in CRITERIA_KEYS.items())
    )
    critical = "".join(
        f"<li><code>{key}</code>: {esc(CRITICAL_ERRORS[value])}</li>"
        for key, value in CRITICAL_KEYS.items()
    )
    types = "".join(
        f"<li><b>{esc(name)}</b>: {esc(meaning)}</li>" for name, meaning in TYPES.values()
    )
    example = {
        "revisor": "nombre y versión del modelo que revisa",
        "lote": batch,
        "explicaciones": [
            {
                "id": ids[0],
                "comentario": "valoración general breve",
                "afirmaciones": [
                    {
                        "id": "c1",
                        "correccion": 2,
                        "respaldo": 2,
                        "cita": "NA",
                        "tipo": 2,
                        "calibracion": 2,
                        "utilidad": 2,
                        "error_critico": None,
                        "nota": None,
                    },
                    {
                        "id": "c2",
                        "correccion": 1,
                        "respaldo": 0,
                        "cita": 1,
                        "tipo": 2,
                        "calibracion": 1,
                        "utilidad": 2,
                        "error_critico": "valor_inventado",
                        "nota": "El valor 0,82 no aparece en la figura ni en el texto.",
                    },
                ],
            }
        ],
    }
    return f"""
<section class="intro">
<h1>Revisión de explicaciones de figuras científicas — lote {batch} de {batches}</h1>
<p>Eres un revisor experto e independiente. Un sistema automático ha explicado figuras de
artículos científicos (licencia CC BY). Cada explicación se compone de <b>afirmaciones</b>
(c1, c2…), cada una con su tipo y su evidencia. Tu tarea es <b>puntuar cada afirmación</b>
con la rúbrica de abajo, comparándola con la imagen de la figura, su pie y los fragmentos
del artículo que recibió el sistema. Este lote contiene: {", ".join(ids)}.</p>

<h2>Cómo revisar</h2>
<ul>
<li>Mira la imagen con atención: comprueba valores, ejes, colores, leyendas y paneles.</li>
<li>Lo que la afirmación atribuye a los autores debe estar en el pie o en los fragmentos.
Puedes abrir el artículo en el enlace indicado para comprobarlo.</li>
<li>Las citas entre comillas deben aparecer en la fuente indicada (pie o fragmento). Cada fragmento indica la página donde empieza; la evidencia indica la página donde está la cita, que puede ser posterior si el fragmento continúa en otra página.</li>
<li>Las afirmaciones de tipo «incierto» señalan lo que no se puede determinar y, por diseño, no llevan evidencia: puntúa «respaldo» según si la duda está justificada por el material, usa «cita» = "NA" y no las penalices por no tener evidencia.</li>
<li>Las «notas de extracción» son avisos que el sistema recibió junto a la figura (por ejemplo, que el pie podía estar truncado); una afirmación que se apoye en ellas no inventa nada.</li>
<li>Sé estricto y concreto. Si no puedes comprobar algo con el material, eso es un problema
de <b>respaldo</b>, no lo des por bueno.</li>
<li>Puntúa <b>todas</b> las afirmaciones. Escribe una <b>nota</b> siempre que alguna
puntuación sea menor que 2 o marques un error crítico, explicando qué falla.</li>
<li>No corrijas la explicación ni añadas contenido: solo evalúa.</li>
</ul>

<h2>Tipos de afirmación que usa el sistema</h2>
<ul>{types}</ul>

<h2>Rúbrica (cada criterio de 0 a 2)</h2>
<table class="rubric"><tr><th>clave</th><th>criterio</th><th>niveles</th></tr>{rows}</table>
<p><code>cita</code> = <code>"NA"</code> solo cuando la afirmación se apoya únicamente en la
imagen de la figura (evidencia «Figura»). Si cita el pie o el texto, puntúa la cita.</p>

<h2>Errores críticos (como mucho uno por afirmación)</h2>
<ul>{critical}</ul>
<p>Un error crítico invalida la explicación aunque el resto esté bien. Usa
<code>null</code> si no hay ninguno.</p>

<h2>Respuesta</h2>
<p>Devuelve <b>solo</b> un bloque JSON con esta estructura exacta (mismos nombres de campo,
números enteros 0, 1 o 2, <code>"NA"</code> solo en <code>cita</code>), con todas las
explicaciones del lote y todas sus afirmaciones:</p>
<pre>{esc(json.dumps(example, ensure_ascii=False, indent=2))}</pre>
</section>
"""


def item_html(item_id: str, document, figure, analysis, image_path: Path, pmcid, manifest) -> str:
    explanation = analysis.explanation
    spans = {(s.claim_id, s.evidence_index): s for s in analysis.spans}
    meta = manifest.get(pmcid, {}) if pmcid else {}
    link = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/" if pmcid else None
    image = image_data_uri(image_path)
    fragments = (
        "".join(
            f"<div class='frag'><div class='small'>{esc(c.ref)} · empieza en la página {c.page}"
            f"{' · ' + esc(c.section) if c.section else ''}</div>"
            f"{'… ' if c.truncated else ''}{esc(c.text)}{' …' if c.truncated else ''}</div>"
            for c in analysis.context
        )
        or "<p class='small'>El sistema no recibió fragmentos del texto para esta figura.</p>"
    )
    claims = []
    for claim in explanation.claims:
        evidence = []
        for index, e in enumerate(claim.evidence):
            if e.kind == "figure_region":
                where = f"Figura{' · panel ' + esc(e.panel) if e.panel else ''}"
            elif e.kind == "caption":
                where = "Pie de figura"
            else:
                span = spans.get((claim.id, index))
                where = (
                    f"Texto · fragmento {esc(span.ref)} · la cita está en la página {span.page}"
                    if span
                    else "Texto · (la cita no se encontró en los fragmentos)"
                )
            quote = f" — «{esc(e.quote)}»" if e.quote else ""
            evidence.append(f"<li>{where}{quote}</li>")
        name, _ = TYPES[claim.type]
        panels = f" · paneles {esc(', '.join(claim.panels))}" if claim.panels else ""
        approx = " · valor aproximado" if claim.approximate else ""
        claims.append(
            f"<div class='claim'><div><b>{esc(claim.id)}</b> · <i>{esc(name)}</i> · "
            f"confianza {esc(claim.confidence)}{panels}{approx}</div>"
            f"<p>{esc(claim.text)}</p>"
            f"<div class='small'>Evidencia:</div><ul>{''.join(evidence) or '<li>ninguna</li>'}</ul>"
            f"</div>"
        )
    caption = figure.caption.text if figure.caption else "(no se detectó el pie)"
    notes = extraction_notes(document, figure)
    return f"""
<section class="item">
<h1>{item_id} · {esc(figure.label or "Figura sin etiqueta")}</h1>
<p class="small">{esc(meta.get("title") or document.filename)}
{f'<br>Artículo: <a href="{link}">{link}</a>' if link else ""}</p>
<img src="{image}" alt="{esc(figure.label)}">
<h2>Pie de figura</h2><p>{esc(caption)}</p>
{f'<p class="small"><b>Notas de extracción que recibió el sistema:</b> {esc(notes)}</p>' if notes else ""}
<h2>Fragmentos del artículo que recibió el sistema</h2>{fragments}
<h2>Explicación del sistema</h2>
<p><b>Resumen:</b> {esc(explanation.summary)}</p>
<h2>Afirmaciones que hay que puntuar ({len(explanation.claims)})</h2>
{"".join(claims)}
</section>
"""


CSS = """
body { font: 11pt/1.45 system-ui, "Segoe UI", Arial, sans-serif; color: #111; margin: 0; }
section { padding: 18mm 16mm; page-break-after: always; }
h1 { font-size: 17pt; margin: 0 0 6px; } h2 { font-size: 12.5pt; margin: 16px 0 6px; }
img { max-width: 100%; max-height: 150mm; display: block; margin: 10px auto; border: 1px solid #ccc; }
.small { font-size: 9pt; color: #555; } .frag { border-left: 3px solid #bbb; padding: 2px 8px; margin: 6px 0; font-size: 9.5pt; }
.claim { border: 1px solid #ccc; border-radius: 6px; padding: 6px 10px; margin: 8px 0; page-break-inside: avoid; }
.claim p { margin: 4px 0; } ul { margin: 4px 0; padding-left: 20px; }
table.rubric { border-collapse: collapse; font-size: 9.5pt; } .rubric td, .rubric th { border: 1px solid #bbb; padding: 4px 6px; vertical-align: top; text-align: left; }
pre { background: #f4f4f4; padding: 8px; font-size: 8.5pt; white-space: pre-wrap; }
"""


def instructions_md(ids: list[str], batch: int) -> str:
    rubric = "\n".join(
        f"| `{key}` | **{c.name}**: {c.question} | 0 = {c.levels[0]}; 1 = {c.levels[1]}; "
        f"2 = {c.levels[2]}{'; NA = no aplica' if c.allows_na else ''} |"
        for key, c in ((k, next(c for c in RUBRIC if c.id == v)) for k, v in CRITERIA_KEYS.items())
    )
    critical = "\n".join(f"- `{k}`: {CRITICAL_ERRORS[v]}" for k, v in CRITICAL_KEYS.items())
    types = "\n".join(f"- **{name}**: {meaning}" for name, meaning in TYPES.values())
    example = {
        "revisor": "nombre y versión del modelo que revisa",
        "lote": batch,
        "explicaciones": [
            {
                "id": ids[0],
                "comentario": "valoración general breve",
                "afirmaciones": [
                    {
                        "id": "c1",
                        "correccion": 2,
                        "respaldo": 2,
                        "cita": "NA",
                        "tipo": 2,
                        "calibracion": 2,
                        "utilidad": 2,
                        "error_critico": None,
                        "nota": None,
                    },
                    {
                        "id": "c2",
                        "correccion": 1,
                        "respaldo": 0,
                        "cita": 1,
                        "tipo": 2,
                        "calibracion": 1,
                        "utilidad": 2,
                        "error_critico": "valor_inventado",
                        "nota": "El valor 0,82 no aparece en la figura ni en el texto.",
                    },
                ],
            }
        ],
    }
    files = "\n".join(f"- `{i}.md` y su figura `{i}.png`" for i in ids)
    return f"""# Revisión de explicaciones de figuras científicas — lote {batch}

Un sistema automático ha explicado figuras de artículos científicos (licencia CC BY). Cada
explicación se compone de **afirmaciones** (c1, c2…), cada una con su tipo y su evidencia.
Tu tarea es **puntuar cada afirmación** con la rúbrica de abajo, comparándola con la imagen
de la figura, su pie y los fragmentos del artículo que recibió el sistema.

## Material (todo en esta carpeta)

{files}

Cada `.md` contiene el pie de la figura, los fragmentos del artículo, el resumen y las
afirmaciones con su evidencia. El `.png` del mismo nombre es la imagen de la figura.

## Cómo revisar

- Mira la imagen con atención: comprueba valores, ejes, unidades, colores, leyendas y paneles.
- Lo que la afirmación atribuye a los autores debe estar en el pie o en los fragmentos.
- Las citas entre comillas deben aparecer en la fuente indicada (pie o fragmento). Cada fragmento indica la página donde empieza; la evidencia indica la página donde está la cita, que puede ser posterior si el fragmento continúa en otra página.
- Las afirmaciones de tipo «incierto» señalan lo que no se puede determinar y, por diseño, no llevan evidencia: puntúa «respaldo» según si la duda está justificada por el material, usa «cita» = "NA" y no las penalices por no tener evidencia.
- Las «notas de extracción» son avisos que el sistema recibió junto a la figura (por ejemplo, que el pie podía estar truncado); una afirmación que se apoye en ellas no inventa nada.
- Sé estricto y concreto. Si no puedes comprobar algo con el material, eso es un problema
  de **respaldo**: no lo des por bueno.
- Puntúa **todas** las afirmaciones. Escribe una **nota** siempre que alguna puntuación sea
  menor que 2 o marques un error crítico, explicando qué falla.
- No corrijas la explicación ni añadas contenido: solo evalúa.

## Tipos de afirmación que usa el sistema

{types}

## Rúbrica (cada criterio de 0 a 2)

| clave | criterio | niveles |
|---|---|---|
{rubric}

`cita` = `"NA"` solo cuando la afirmación se apoya únicamente en la imagen de la figura
(evidencia «Figura»). Si cita el pie o el texto, puntúa la cita.

## Errores críticos (como mucho uno por afirmación)

{critical}

Un error crítico invalida la explicación aunque el resto esté bien. Usa `null` si no hay ninguno.

## Respuesta

Escribe un único archivo, `informe_revision.json`, en esta carpeta, con esta estructura
exacta: mismos nombres de campo, enteros 0, 1 o 2, y `"NA"` solo en `cita`. Debe incluir
**todas** las explicaciones ({", ".join(ids)}) y todas sus afirmaciones.

```json
{json.dumps(example, ensure_ascii=False, indent=2)}
```
"""


def item_md(item_id: str, document, figure, analysis, pmcid, manifest) -> str:
    explanation = analysis.explanation
    spans = {(s.claim_id, s.evidence_index): s for s in analysis.spans}
    title = (manifest.get(pmcid, {}) if pmcid else {}).get("title") or document.filename
    link = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/" if pmcid else None
    fragments = (
        "\n\n".join(
            f"> **{c.ref}** · empieza en la página {c.page}{' · ' + c.section if c.section else ''}\n>\n> "
            f"{'… ' if c.truncated else ''}{c.text}{' …' if c.truncated else ''}"
            for c in analysis.context
        )
        or "_El sistema no recibió fragmentos del texto para esta figura._"
    )
    claims = []
    for claim in explanation.claims:
        evidence = []
        for index, e in enumerate(claim.evidence):
            if e.kind == "figure_region":
                where = f"Figura{' · panel ' + e.panel if e.panel else ''}"
            elif e.kind == "caption":
                where = "Pie de figura"
            else:
                span = spans.get((claim.id, index))
                where = (
                    f"Texto · fragmento {span.ref} · la cita está en la página {span.page}"
                    if span
                    else "Texto · (la cita no se encontró en los fragmentos)"
                )
            evidence.append(f"  - {where}{f' — «{e.quote}»' if e.quote else ''}")
        name, _ = TYPES[claim.type]
        extra = f" · paneles {', '.join(claim.panels)}" if claim.panels else ""
        extra += " · valor aproximado" if claim.approximate else ""
        claims.append(
            f"### {claim.id} · {name} · confianza {claim.confidence}{extra}\n\n{claim.text}\n\n"
            f"- Evidencia:\n" + ("\n".join(evidence) or "  - ninguna")
        )
    caption = figure.caption.text if figure.caption else "(no se detectó el pie)"
    notes = extraction_notes(document, figure)
    return f"""# {item_id} · {figure.label or "Figura sin etiqueta"}

Artículo: {title}{f" — {link}" if link else ""}

Imagen de la figura: `{item_id}.png`

## Pie de figura

{caption}
{f"{chr(10)}**Notas de extracción que recibió el sistema:** {notes}{chr(10)}" if notes else ""}
## Fragmentos del artículo que recibió el sistema

{fragments}

## Explicación del sistema

**Resumen:** {explanation.summary}

## Afirmaciones que hay que puntuar ({len(explanation.claims)})

{(chr(10) * 2).join(claims)}
"""


def to_pdf(html_path: Path, pdf_path: Path) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    with sync_playwright() as p:
        browser = None
        for options in ({}, {"channel": "chrome"}, {"channel": "msedge"}):
            try:
                browser = p.chromium.launch(**options)
                break
            except Exception:  # noqa: BLE001 - try the next installed browser
                continue
        if browser is None:
            return False
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri())
        page.pdf(path=str(pdf_path), format="A4", print_background=True)
        browser.close()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=15, help="explanations in total")
    parser.add_argument("--per-batch", type=int, default=5)
    parser.add_argument("--per-document", type=int, default=1, help="figures per document")
    parser.add_argument("--split", help="only SFI-48 documents of this split")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    settings = Settings.from_env()
    repository = SQLiteRepository(settings.database_path)
    blobs = LocalBlobStore(settings.blob_dir)
    manifest = {
        a["pmcid"]: a
        for a in json.loads((ROOT / "data/sfi48/manifest.json").read_text("utf-8"))["articles"]
    }
    out = args.out or settings.data_dir / "revision_ia" / dt.date.today().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    items = sample(repository, args.limit, args.per_document, args.split, manifest)
    keys = {}
    batches = [items[i : i + args.per_batch] for i in range(0, len(items), args.per_batch)]
    number = 0
    for b, batch in enumerate(batches, start=1):
        sections, ids = [], []
        folder = out / f"revisor_lote_{b}"  # one folder per batch for an agent reviewer
        folder.mkdir(exist_ok=True)
        for document, figure, analysis in batch:
            number += 1
            item_id = f"E{number:02d}"
            ids.append(item_id)
            pmcid = pmcid_of(document)
            image_path = blobs.path(repository.get_artifact(figure.crop_artifact_id).storage_key)
            sections.append(
                item_html(item_id, document, figure, analysis, image_path, pmcid, manifest)
            )
            (folder / f"{item_id}.md").write_text(
                item_md(item_id, document, figure, analysis, pmcid, manifest), encoding="utf-8"
            )
            image = Image.open(image_path).convert("RGB")
            image.thumbnail((2000, 2000))
            image.save(folder / f"{item_id}.png", optimize=True)
            run = analysis.run
            keys[item_id] = {
                "lote": b,
                "analysis": analysis.reused_from or analysis.id,
                "document_sha256": document.id.removeprefix("sha256:"),
                "filename": document.filename,
                "pmcid": pmcid,
                "split": manifest.get(pmcid, {}).get("split"),
                "figure_label": figure.label,
                "page": figure.page_index + 1,
                "explanation_status": analysis.status.value,
                "model": (run.model_version or run.model) if run else None,
                "prompt_version": run.prompt_version if run else None,
                "schema_version": analysis.schema_version,
                "claims": [
                    {"id": c.id, "type": c.type, "confidence": c.confidence, "text": c.text}
                    for c in analysis.explanation.claims
                ],
            }
        page = (
            f"<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            f"<title>Revisión de explicaciones · lote {b}</title><style>{CSS}</style></head>"
            f"<body>{instructions(b, len(batches), ids)}{''.join(sections)}</body></html>"
        )
        html_path = out / f"lote_{b}.html"
        html_path.write_text(page, encoding="utf-8")
        made_pdf = to_pdf(html_path, out / f"lote_{b}.pdf")
        (folder / "INSTRUCCIONES.md").write_text(instructions_md(ids, b), encoding="utf-8")
        claims = sum(len(keys[i]["claims"]) for i in ids)
        print(
            f"lote {b}: {', '.join(ids)} ({claims} afirmaciones) -> {out / f'lote_{b}.pdf' if made_pdf else html_path}"
        )
    (out / "claves.json").write_text(
        json.dumps({"seed": SEED, "items": keys}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"claves -> {out / 'claves.json'}; carpetas para un agente: {out}/revisor_lote_N")
    repository.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
