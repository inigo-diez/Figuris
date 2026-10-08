"""Static HTML gallery of extracted figures, linked back to the source pages.

Each figure shows its region, caption and its structured explanation with typed
claims. Quotes from the article text link to the passage, highlighted on its page
(Stage 3). The interactive web application arrives in Stage 4.
"""

from __future__ import annotations

import html
import shutil
from pathlib import Path

import pypdfium2 as pdfium

from sfi.analysis.schema import AnalysisStatus, Claim, FigureAnalysis, SpanRef
from sfi.domain.models import Document, Figure, ProcessorRun
from sfi.extract.render import render_page_png
from sfi.storage.blobs import BlobStore
from sfi.storage.repository import Repository

PAGE_DPI = 110

STYLE = """
:root { --bg:#f7f7f5; --card:#fff; --ink:#1d1d1b; --muted:#6b6b66; --line:#e2e2dc;
        --accent:#2563eb; --ok:#15803d; --warn:#b45309; --bad:#b91c1c;
        --observed:#0e7490; --author:#7c3aed; --inference:#b45309; --uncertain:#6b6b66; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#161615; --card:#20201e; --ink:#ececea; --muted:#a3a39c; --line:#33332f;
          --accent:#60a5fa; --ok:#4ade80; --warn:#fbbf24; --bad:#f87171;
          --observed:#22d3ee; --author:#c4b5fd; --inference:#fbbf24; --uncertain:#a3a39c; } }
* { box-sizing:border-box; }
body { margin:0; font:15px/1.5 system-ui, sans-serif; background:var(--bg); color:var(--ink); }
header, main { max-width:1200px; margin:0 auto; padding:16px; }
h1 { font-size:20px; margin:8px 0 4px; } h2 { font-size:17px; margin:32px 0 12px; }
.meta { color:var(--muted); font-size:13px; overflow-wrap:anywhere; }
.grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(min(320px, 100%), 1fr)); gap:16px; }
.card { min-width:0; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px;
        display:flex; flex-direction:column; gap:8px; }
.card img { width:100%; max-height:320px; object-fit:contain; background:#fff; border-radius:6px; }
.card .crop { display:block; }
.row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.label { font-weight:600; }
.badge { font-size:12px; padding:1px 8px; border-radius:99px; border:1px solid currentColor; }
.ok { color:var(--ok); } .caption_only, .region_only, .incomplete, .skipped { color:var(--warn); }
.invalid, .failed { color:var(--bad); }
.card.explained { grid-column:1 / -1; display:grid; grid-template-columns:minmax(0, 2fr) minmax(0, 3fr);
                  gap:16px; align-items:start; }
.card .fig { display:flex; flex-direction:column; gap:8px; min-width:0; }
.card.explained img { max-height:520px; }
@media (max-width: 760px) { .card.explained { grid-template-columns:minmax(0, 1fr); } }
.expl { min-width:0; font-size:14px; display:flex; flex-direction:column; gap:6px; }
.expl h4 { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:10px 0 2px; }
.expl p, .expl ul { margin:0; } .expl ul { padding-left:18px; }
.expl .summary { font-size:15px; }
.expl .unreliable { color:var(--bad); font-size:13px; border-left:3px solid var(--bad); padding-left:8px; }
.expl .axes { overflow-x:auto; } .expl table { font-size:13px; } .expl td, .expl th { padding:3px 6px; }
.tag { font-size:11px; padding:0 6px; border-radius:4px; border:1px solid var(--line); color:var(--muted); }
.ct { font-size:11px; font-weight:600; padding:0 6px; border-radius:4px; border:1px solid currentColor;
      white-space:nowrap; }
.ct.observed { color:var(--observed); } .ct.author_stated { color:var(--author); }
.ct.model_inference { color:var(--inference); } .ct.uncertain { color:var(--uncertain); }
.claims li { margin-bottom:4px; } .claims q { font-style:italic; color:var(--muted); }
.claims .flag { color:var(--bad); font-size:12px; }
details summary { cursor:pointer; color:var(--accent); font-size:13px; margin-top:6px; }
.caption { font-size:13px; max-height:9.5em; overflow:auto; }
.warn { font-size:12px; color:var(--warn); margin:0; padding-left:18px; }
a { color:var(--accent); }
.page { position:relative; display:inline-block; max-width:100%; border:1px solid var(--line); }
.page img { display:block; max-width:100%; height:auto; }
.box { position:absolute; border:2px solid var(--accent); background:rgba(37,99,235,.08); }
.box span { position:absolute; top:-1.6em; left:-2px; background:var(--accent); color:#fff;
            font-size:11px; padding:0 4px; white-space:nowrap; }
.capbox { position:absolute; border:1.5px dashed var(--warn); }
.psg { position:absolute; border:2px dashed var(--author); background:rgba(124,58,237,.06); }
.psg span { position:absolute; top:-1.5em; right:-2px; background:var(--author); color:#fff;
            font-size:11px; padding:0 4px; white-space:nowrap; }
.psg:target { outline:3px solid var(--author); background:rgba(124,58,237,.16); }
.src { font-size:11px; color:var(--muted); white-space:nowrap; }
.src.bad { color:var(--bad); }
.ctx li { margin-bottom:6px; font-size:13px; } .ctx .cited { font-weight:600; color:var(--author); }
.box:target { border-color:var(--bad); background:rgba(185,28,28,.12); outline:3px solid var(--bad); }
.pages section { margin-bottom:28px; }
table { border-collapse:collapse; width:100%; font-size:14px; }
td, th { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; }
"""


def _pct(value: float) -> str:
    return f"{value * 100:.3f}%"


def _box_style(norm: tuple[float, float, float, float]) -> str:
    x0, y0, x1, y1 = norm
    return f"left:{_pct(x0)};top:{_pct(y0)};width:{_pct(x1 - x0)};height:{_pct(y1 - y0)}"


def write_document_report(
    document: Document,
    run: ProcessorRun,
    figures: list[Figure],
    repository: Repository,
    blobs: BlobStore,
    out_root: Path,
) -> Path:
    short = document.id.split(":")[-1][:12]
    out = out_root / short
    (out / "figures").mkdir(parents=True, exist_ok=True)
    (out / "pages").mkdir(parents=True, exist_ok=True)

    original = repository.get_artifact(document.source_artifact_id)
    pdf_path = blobs.path(original.storage_key).resolve()
    pdf = pdfium.PdfDocument(pdf_path)

    passages = {p.id: p for p in repository.list_passages(run.id)}
    cited: dict[str, set[str]] = {}  # passage id -> refs shown on it
    cards = []
    for figure in figures:
        anchor = f"page-{figure.page_index + 1}-{figure.id}"
        img = ""
        if figure.crop_artifact_id:
            artifact = repository.get_artifact(figure.crop_artifact_id)
            target = out / "figures" / f"{figure.id}.png"
            if not target.exists():
                shutil.copyfile(blobs.path(artifact.storage_key), target)
            img = (
                f'<a class="crop" href="figures/{figure.id}.png" target="_blank">'
                f'<img loading="lazy" src="figures/{figure.id}.png" alt="{html.escape(figure.label or "")}"></a>'
            )
        caption = (
            html.escape(figure.caption.text) if figure.caption else "<em>Sin pie detectado</em>"
        )
        warnings = "".join(f"<li>{html.escape(w.message)}</li>" for w in figure.warnings)
        analysis = repository.latest_analysis(figure.id)
        explained = analysis is not None and analysis.status != AnalysisStatus.FAILED
        if explained:
            for span in analysis.spans:
                if span.passage_id in passages:
                    cited.setdefault(span.passage_id, set()).add(span.ref)
        cards.append(f"""
<article class="card{" explained" if explained else ""}">
 <div class="fig">
  {img}
  <div class="row"><span class="label">{html.escape(figure.label or "Región sin etiqueta")}</span>
    <span class="badge {figure.status}">{figure.status}</span>
    <span class="meta">confianza {figure.confidence:.2f}</span></div>
  <div class="row meta">Página {figure.page_index + 1} ·
    <a href="#{anchor}">ver en la página</a> ·
    <a href="{pdf_path.as_uri()}#page={figure.page_index + 1}" target="_blank">abrir PDF</a></div>
  <div class="caption">{caption}</div>
  {f'<ul class="warn">{warnings}</ul>' if warnings else ""}
 </div>
 {explanation_html(analysis, set(passages)) if explained else ""}
</article>""")

    passage_boxes: dict[int, list[str]] = {}
    for passage_id, refs in cited.items():
        for number, segment in enumerate(passages[passage_id].segments):
            anchor = f' id="psg-{passage_id}"' if number == 0 else ""
            label = f"<span>{html.escape(', '.join(sorted(refs)))}</span>" if number == 0 else ""
            passage_boxes.setdefault(segment.page_index, []).append(
                f'<a class="psg"{anchor} style="{_box_style(segment.bbox_normalized)}">{label}</a>'
            )

    sections = []
    for page_index in sorted({f.page_index for f in figures} | set(passage_boxes)):
        page_png = out / "pages" / f"p{page_index + 1}.png"
        if not page_png.exists():
            page_png.write_bytes(render_page_png(pdf[page_index], PAGE_DPI))
        boxes = []
        for figure in (f for f in figures if f.page_index == page_index):
            page = document.pages[page_index]
            if figure.bbox_normalized:
                boxes.append(
                    f'<a class="box" id="page-{page_index + 1}-{figure.id}" '
                    f'style="{_box_style(figure.bbox_normalized)}">'
                    f"<span>{html.escape(figure.label or 'sin etiqueta')}</span></a>"
                )
            elif figure.caption:
                boxes.append(
                    f'<a class="box" id="page-{page_index + 1}-{figure.id}" '
                    f'style="{_box_style(figure.caption.bbox.normalized(page.width, page.height))}">'
                    f"<span>{html.escape(figure.label or '')} (solo pie)</span></a>"
                )
            if figure.caption:
                norm = figure.caption.bbox.normalized(page.width, page.height)
                boxes.append(f'<div class="capbox" style="{_box_style(norm)}"></div>')
        boxes += passage_boxes.get(page_index, [])
        sections.append(f"""
<section id="page-{page_index + 1}"><h3>Página {page_index + 1}</h3>
  <div class="page"><img loading="lazy" src="pages/p{page_index + 1}.png" alt="Página {page_index + 1}">{"".join(boxes)}</div>
</section>""")
    pdf.close()

    run_warnings = "".join(
        f"<li>{html.escape(w.message)}"
        + (f" (p. {w.page_index + 1})" if w.page_index is not None else "")
        + "</li>"
        for w in run.warnings
        if w.code.value != "scanned_page"
    )
    scanned = sum(1 for p in document.pages if p.is_scanned)
    counts = {
        s: sum(1 for f in figures if f.status == s) for s in ("ok", "caption_only", "region_only")
    }
    analyses = [a for f in figures if (a := repository.latest_analysis(f.id))]
    explained = sum(1 for a in analyses if a.status == AnalysisStatus.OK)
    spent = sum(a.run.estimated_cost_usd for a in analyses if a.run)
    page = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Figuras · {html.escape(document.filename)}</title><style>{STYLE}</style></head>
<body><header>
  <p class="meta"><a href="../index.html">← todos los documentos</a></p>
  <h1>{html.escape(document.filename)}</h1>
  <p class="meta">{document.page_count} páginas{f" ({scanned} escaneadas)" if scanned else ""} ·
    {counts["ok"]} figuras con región · {counts["caption_only"]} solo pie · {counts["region_only"]} regiones sin pie ·
    {explained} explicaciones válidas de {len(analyses)} ({spent:.4f} USD) ·
    extractor {html.escape(run.producer)} {html.escape(run.producer_version)} · {run.duration_ms} ms ·
    <a href="{pdf_path.as_uri()}" target="_blank">PDF original</a></p>
  {f'<ul class="warn">{run_warnings}</ul>' if run_warnings else ""}
</header>
<main>
  <div class="grid">{"".join(cards)}</div>
  <h2>Páginas de origen</h2>
  <p class="meta">Recuadro azul: región de la figura. Discontinuo naranja: pie detectado.
    Discontinuo violeta: pasaje del texto citado en una explicación.</p>
  <div class="pages">{"".join(sections)}</div>
</main></body></html>"""
    path = out / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def write_index(
    entries: list[tuple[Document, ProcessorRun, list[Figure]]],
    out_root: Path,
    repository: Repository,
) -> Path:
    rows = []
    for document, run, figures in entries:
        short = document.id.split(":")[-1][:12]
        ok = sum(1 for f in figures if f.status == "ok")
        analyses = [a for f in figures if (a := repository.latest_analysis(f.id))]
        explained = sum(1 for a in analyses if a.status == AnalysisStatus.OK)
        rows.append(
            f"<tr><td><a href='{short}/index.html'>{html.escape(document.filename)}</a></td>"
            f"<td>{document.page_count}</td><td>{ok}</td><td>{len(figures) - ok}</td>"
            f"<td>{explained}/{len(analyses)}</td>"
            f"<td>{sum(1 for w in run.warnings if w.code.value != 'scanned_page')}</td>"
            f"<td class='meta'>{short}</td></tr>"
        )
    page = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Documentos procesados</title><style>{STYLE}</style></head>
<body><header><h1>Documentos procesados</h1></header><main>
<table><thead><tr><th>Documento</th><th>Páginas</th><th>Figuras</th><th>Incompletas</th><th>Explicadas</th><th>Avisos</th><th>ID</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></main></body></html>"""
    out_root.mkdir(parents=True, exist_ok=True)
    path = out_root / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


CLAIM_TYPES = {
    "observed": "observado",
    "author_stated": "según los autores",
    "model_inference": "inferencia del modelo",
    "uncertain": "incierto",
}
STATUS_NOTES = {
    AnalysisStatus.INCOMPLETE: "Explicación incompleta: no debe tomarse como fiable.",
    AnalysisStatus.INVALID: (
        "Explicación no válida: incumple las reglas de validación y no debe tomarse como fiable."
    ),
}


def _source(span: SpanRef | None, linkable: set[str]) -> str:
    if span is None:
        return "<span class='src bad'>texto (cita no encontrada)</span>"
    where = f"texto · p. {span.page}" + (f" · {html.escape(span.section)}" if span.section else "")
    if span.passage_id in linkable:
        return f"<a class='src' href='#psg-{span.passage_id}'>{where}</a>"
    return f"<span class='src'>{where}</span>"


def _claim_html(
    claim: Claim,
    flags: dict[str, list[str]],
    spans: dict[tuple[str, int], SpanRef],
    linkable: set[str],
) -> str:
    quotes = []
    for index, evidence in enumerate(claim.evidence):
        if not evidence.quote or evidence.kind == "figure_region":
            continue
        source = (
            "<span class='src'>pie</span>"
            if evidence.kind == "caption"
            else _source(spans.get((claim.id, index)), linkable)
        )
        quotes.append(f"<q>{html.escape(evidence.quote)}</q> {source}")
    panels = (
        f" <span class='tag'>{html.escape(', '.join(claim.panels))}</span>" if claim.panels else ""
    )
    approx = " <span class='tag'>aprox.</span>" if claim.approximate else ""
    problems = "".join(
        f"<div class='flag'>⚠ {html.escape(m)}</div>" for m in flags.get(claim.id, [])
    )
    return (
        f"<li><span class='ct {claim.type}'>{CLAIM_TYPES[claim.type]}</span> "
        f"{html.escape(claim.text)}{panels}{approx}"
        + "".join(f"<br>{q}" for q in quotes)
        + problems
        + "</li>"
    )


def explanation_html(analysis: FigureAnalysis, linkable: set[str] | None = None) -> str:
    """Render one stored analysis: summary, reading guide, encoding, typed claims, the
    article passages used and provenance. ``linkable``: passage ids drawn on the pages."""
    linkable = linkable or set()
    spans = {(s.claim_id, s.evidence_index): s for s in analysis.spans}
    run = analysis.run
    meta = ""
    if run:
        meta = (
            f"{html.escape(run.model_version or run.model)} · {html.escape(run.prompt_version)} · "
            f"{run.input_tokens} + {run.output_tokens} tokens · {run.estimated_cost_usd:.4f} USD · "
            f"{run.latency_ms / 1000:.1f} s" + (" · reutilizada" if analysis.reused_from else "")
        )
    head = (
        "<div class='row'><span class='label'>Explicación</span>"
        f"<span class='badge {analysis.status.value}'>{analysis.status.value}</span></div>"
    )
    note = ""
    if analysis.status in STATUS_NOTES:
        items = "".join(
            f"<li>{html.escape(i.message)}</li>"
            for i in analysis.issues
            if i.severity == "error" and not i.claim_id
        )
        note = (
            f"<div class='unreliable'>{STATUS_NOTES[analysis.status]}"
            + (f"<ul>{items}</ul>" if items else "")
            + "</div>"
        )
    explanation = analysis.explanation
    if explanation is None:
        return f"<section class='expl'>{head}{note}<p class='meta'>{meta}</p></section>"

    flags: dict[str, list[str]] = {}
    for issue in analysis.issues:
        if issue.claim_id:
            flags.setdefault(issue.claim_id, []).append(issue.message)
    claims = {c.id: c for c in explanation.claims}

    def claim_list(ids: list[str]) -> str:
        items = "".join(_claim_html(claims[i], flags, spans, linkable) for i in ids if i in claims)
        return f"<ul class='claims'>{items}</ul>" if items else ""

    types = "".join(f"<span class='tag'>{html.escape(t)}</span>" for t in explanation.figure_type)
    panels = "".join(
        f"<li><b>{html.escape(p.label)}</b>: {html.escape(p.content)}</li>"
        for p in explanation.layout.panels
    )
    encoding = explanation.visual_encoding
    axes = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(v or '—')}</td>"
            for v in (a.panel, a.axis, a.label, a.unit, a.range, a.scale)
        )
        + "</tr>"
        for a in encoding.axes
    )

    def prefix(panel: str | None) -> str:
        return f"<b>{html.escape(panel)}</b> " if panel else ""

    symbols = [
        f"{prefix(e.panel)}{html.escape(e.symbol)}: {html.escape(e.meaning)}"
        for e in encoding.legend
    ]
    symbols += [
        f"{prefix(b.panel)}barra de escala {html.escape(b.value)}" for b in encoding.scale_bars
    ]
    symbols += [html.escape(o) for o in encoding.other]
    limitations = claim_list(explanation.limitations) or (
        f"<p>{html.escape(explanation.limitations_justification or 'Ninguna indicada.')}</p>"
    )
    other_issues = "".join(
        f"<li>{html.escape(i.message)}</li>"
        for i in analysis.issues
        if i.severity == "warning" and not i.claim_id
    )
    used = {s.ref for s in analysis.spans}
    context_items = "".join(
        f"<li><span class='{'cited' if c.ref in used else 'meta'}'>{c.ref}</span> "
        f"<span class='meta'>p. {c.page}{' · ' + html.escape(c.section) if c.section else ''}"
        f"{' · citado' if c.ref in used else ''}</span><br>"
        f"{'… ' if c.truncated else ''}{html.escape(c.text)}{' …' if c.truncated else ''}</li>"
        for c in analysis.context
    )
    context_block = (
        f"<details><summary>Fragmentos del artículo enviados ({len(analysis.context)})</summary>"
        f"<ul class='ctx'>{context_items}</ul></details>"
        if analysis.context
        else ""
    )
    if analysis.context_note:
        context_block += f"<p class='meta'>{html.escape(analysis.context_note)}</p>"
    role = explanation.role_in_article
    role_block = (
        f"<h4>Papel en el artículo</h4><p>{html.escape(role.text)}</p>" if role.text.strip() else ""
    )
    axes_table = (
        "<h4>Ejes</h4><div class='axes'><table><thead><tr><th>Panel</th><th>Eje</th>"
        "<th>Título</th><th>Unidad</th><th>Rango</th><th>Escala</th></tr></thead>"
        f"<tbody>{axes}</tbody></table></div>"
        if axes
        else ""
    )
    symbol_list = (
        "<h4>Colores, símbolos y escalas</h4><ul>"
        + "".join(f"<li>{s}</li>" for s in symbols)
        + "</ul>"
        if symbols
        else ""
    )
    return f"""<section class="expl">
  {head}{note}
  <p class="summary">{html.escape(explanation.summary)}</p>
  <div class="row">{types}</div>
  <h4>Cómo leerla</h4><p>{html.escape(explanation.layout.description)}</p>
  {f"<ul>{panels}</ul>" if panels else ""}
  {axes_table}
  {symbol_list}
  <h4>Resultados principales</h4>{claim_list(explanation.main_findings) or "<p>—</p>"}
  <h4>Interpretación</h4><p>{html.escape(explanation.interpretation.text)}</p>
  {role_block}
  <h4>Incertidumbres</h4>{limitations}
  {context_block}
  <details><summary>Todas las afirmaciones ({len(explanation.claims)})</summary>
    {claim_list([c.id for c in explanation.claims])}
    {f'<ul class="warn">{other_issues}</ul>' if other_issues else ""}
  </details>
  <p class="meta">{meta}</p>
</section>"""
