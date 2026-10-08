"use strict";
// Figuris: one figure with its explanation and the evidence behind every claim.

async function renderFigure(docId, figId) {
  let fig;
  try {
    fig = await api(`/api/documents/${docId}/figures/${figId}`);
  } catch (error) {
    setCrumbs(["Documentos", "#/documentos"], ["Figura no encontrada"]);
    mount(alertBox("bad", error.message), h("p", {}, h("a", { href: `#/d/${docId}` }, "Volver al documento")));
    return;
  }
  document.title = `${fig.label || "Figura"} · ${fig.filename}`;
  setCrumbs(["Documentos", "#/documentos"], [fig.filename, `#/d/${docId}?f=${fig.id}`], [fig.label || "Región sin etiqueta"]);
  setSearch("Buscar", null);
  const analysis = fig.analysis;
  const explanation = analysis?.explanation;
  const spans = new Map((analysis?.spans || []).map((s) => [`${s.claim_id}:${s.evidence_index}`, s]));
  const passages = new Map(fig.passages.map((p) => [p.id, p]));

  // Left column: figure or page, with zoom.
  const viewer = createViewer();
  const tabFigure = h("button", { role: "tab", type: "button" }, "Figura");
  const tabPage = h("button", { role: "tab", type: "button" }, `Página ${fig.page}`);
  const pager = h("span", { class: "row small" });
  let currentPage = fig.page;

  function select(tab) {
    tabFigure.setAttribute("aria-selected", String(tab === "figure"));
    tabPage.setAttribute("aria-selected", String(tab === "page"));
    pager.hidden = tab !== "page";
  }
  // Panels with a reliable region, by letter (claims refer to them as "a", "B"...).
  fig.panels = fig.panels || []; // servers before panel detection do not send them
  const panels = new Map(fig.panels.filter((p) => p.image_box).map((p) => [p.label.toLowerCase(), p]));
  // Values that claims read in the image, linked to where they are printed (evidence layer).
  const valuesByClaim = new Map();
  for (const ref of fig.token_refs || []) {
    if (!ref.image_box) continue;
    if (!valuesByClaim.has(ref.claim_id)) valuesByClaim.set(ref.claim_id, new Map());
    const byValue = valuesByClaim.get(ref.claim_id);
    if (!byValue.has(ref.value)) byValue.set(ref.value, []);
    byValue.get(ref.value).push(ref);
  }
  function showFigure(panel = null, values = null) {
    select("figure");
    if (!fig.has_image) { showPage(fig.page); return; }
    const boxes = [...panels.values()].map((p) => ({ box: p.image_box, cls: `pnl${p === panel ? " active" : ""}`, label: p.label }));
    for (const ref of values || []) boxes.push({ box: ref.image_box, cls: "tok", label: ref.text });
    const focusBox = panel ? panel.image_box : values?.length ? values[0].image_box : null;
    viewer.show(`/api/figures/${fig.id}/image`, fig.label || "Figura", boxes, focusBox);
    if (panel || values) viewer.el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  function showPage(number, activePassage = null) {
    select("page");
    currentPage = number;
    tabPage.textContent = `Página ${number}`;
    const boxes = [];
    if (number === fig.page && fig.box) boxes.push({ box: fig.box, cls: "fig", label: fig.label || "figura" });
    if (number === fig.page) for (const p of panels.values()) boxes.push({ box: p.box, cls: "pnl", label: p.label });
    if (number === fig.caption_page && fig.caption_box) boxes.push({ box: fig.caption_box, cls: "cap" });
    let focusBox = null;
    for (const passage of fig.passages) {
      for (const segment of passage.segments) {
        if (segment.page !== number) continue;
        const active = passage.id === activePassage;
        boxes.push({ box: segment.box, cls: `psg${active ? " active" : ""}`, label: active && !focusBox ? "texto citado" : null });
        if (active && !focusBox) focusBox = segment.box;
      }
    }
    viewer.show(`/api/documents/${docId}/pages/${number}`, `Página ${number} del artículo`, boxes, focusBox);
    pageLabel.textContent = `${number} / ${fig.pages}`;
    prevPage.disabled = number <= 1;
    nextPage.disabled = number >= fig.pages;
  }
  const prevPage = h("button", { class: "btn icon", type: "button", "aria-label": "Página anterior", onclick: () => showPage(currentPage - 1) }, "‹");
  const nextPage = h("button", { class: "btn icon", type: "button", "aria-label": "Página siguiente", onclick: () => showPage(currentPage + 1) }, "›");
  const pageLabel = h("span", { class: "muted" });
  pager.append(prevPage, pageLabel, nextPage);
  tabFigure.addEventListener("click", () => showFigure());
  tabPage.addEventListener("click", () => showPage(fig.page));

  const pdfLink = (page) => h("a", { href: `/api/documents/${docId}/pdf#page=${page}`, target: "_blank", rel: "noopener" }, "abrir en el PDF");
  const captionBox = h("div", { class: "card caption-box" },
    h("div", { class: "row small muted" },
      `${fig.label || "Región sin etiqueta"} · página ${fig.page}`, " · ",
      h("a", { href: "#", onclick: (e) => { e.preventDefault(); showPage(fig.page); } }, "ver en la página"), " · ",
      pdfLink(fig.page)),
    h("h3", {}, "Pie de figura"),
    h("div", { class: "caption-text" }, fig.caption || "No se detectó el pie de esta figura."),
    panelList(),
    fig.warnings.length ? h("ul", { class: "small muted" }, fig.warnings.map((w) => h("li", {}, w))) : null,
  );

  function panelList() {
    if (!fig.panels.length) return null;
    const located = panels.size > 0;
    return [
      h("h3", {}, `Paneles (${fig.panels.length})`),
      located
        ? h("p", { class: "small muted" }, "Delimitados automáticamente por los huecos entre paneles y el orden de las letras del pie; comprueba que encajan. Pulsa una letra para ampliar el panel.")
        : h("p", { class: "small muted" }, "Cada letra con su parte del pie. Los paneles todavía no se delimitan con fiabilidad en la imagen, así que se muestra la figura completa."),
      h("ul", { class: "panels" }, fig.panels.map((p) => h("li", {},
        panels.has(p.label.toLowerCase())
          ? h("button", { class: "src", type: "button", title: `Ampliar el panel ${p.label}`, onclick: () => showFigure(panels.get(p.label.toLowerCase())) }, p.label)
          : h("span", { class: "src" }, p.label),
        " ", p.subcaption || h("span", { class: "muted" }, "sin texto propio en el pie")))),
    ];
  }
  function flashCaption() {
    captionBox.classList.remove("flash");
    void captionBox.offsetWidth;
    captionBox.classList.add("flash");
    captionBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // Right column: explanation.
  const right = h("section", { class: "card expl", "aria-label": "Explicación" });
  right.append(...explanationContent());

  function explanationContent() {
    const out = [h("h2", { class: "expl-title" }, "Explicación")];
    if (!analysis) {
      out.push(h("p", { class: "muted" }, fig.has_image
        ? "Esta figura todavía no tiene explicación. Si el documento se está procesando, aparecerá en unos segundos; si no, usa «Reprocesar» en la lista de figuras."
        : "Solo se detectó el pie de figura; no hay imagen que explicar."));
      return out;
    }
    if (analysis.status === "failed") {
      out.push(alertBox("bad", "No se pudo generar la explicación: ", analysis.error || "error del servicio", ". Reprocesa el documento para reintentarlo."));
      return out;
    }
    if (analysis.status !== "ok") {
      const general = analysis.issues.filter((i) => i.severity === "error" && !i.claim_id).map((i) => i.message);
      out.push(alertBox("bad",
        h("strong", {}, analysis.status === "invalid" ? "Explicación no fiable. " : "Explicación incompleta. "),
        "Incumple alguna regla de verificación (por ejemplo, una cita que no aparece literalmente en la fuente). Las afirmaciones afectadas están marcadas en rojo.",
        general.length ? h("ul", {}, general.map((m) => h("li", {}, m))) : null));
    }
    if (!explanation) return out;

    out.push(legend());
    out.push(h("p", { class: "summary" }, explanation.summary));
    const claims = new Map(explanation.claims.map((c) => [c.id, c]));
    const flags = new Map();
    for (const issue of analysis.issues) {
      if (!issue.claim_id) continue;
      if (!flags.has(issue.claim_id)) flags.set(issue.claim_id, []);
      flags.get(issue.claim_id).push(issue);
    }
    const list = (ids) => {
      const items = ids.filter((id) => claims.has(id)).map((id) => claimItem(claims.get(id), flags.get(id) || []));
      return items.length ? h("ul", { class: "claims" }, items) : h("p", { class: "muted" }, "—");
    };

    out.push(h("h3", {}, "Cómo leerla"), h("p", {}, explanation.layout.description));
    if (explanation.layout.panels.length) {
      out.push(h("ul", {}, explanation.layout.panels.map((p) => h("li", {}, h("strong", {}, p.label), ": ", p.content))));
    }
    const enc = explanation.visual_encoding;
    if (enc.axes.length) {
      out.push(h("h3", {}, "Ejes"), h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Panel", "Eje", "Título", "Unidad", "Rango", "Escala"].map((t) => h("th", {}, t)))),
        h("tbody", {}, enc.axes.map((a) => h("tr", {}, [a.panel, a.axis, a.label, a.unit, a.range, a.scale].map((v) => h("td", {}, v || "—"))))),
      )));
    }
    const symbols = [
      ...enc.legend.map((l) => [l.panel, `${l.symbol}: ${l.meaning}`]),
      ...enc.scale_bars.map((b) => [b.panel, `barra de escala ${b.value}${b.source === "caption" ? " (según el pie)" : ""}`]),
      ...enc.other.map((o) => [null, o]),
    ];
    if (symbols.length) {
      out.push(h("h3", {}, "Colores, símbolos y escalas"), h("ul", {}, symbols.map(([panel, text]) => h("li", {}, panel ? h("strong", {}, `${panel} `) : null, text))));
    }
    out.push(h("h3", {}, "Resultados principales"), list(explanation.main_findings));
    out.push(h("h3", {}, "Interpretación"), h("p", {}, explanation.interpretation.text));
    if (explanation.role_in_article?.text) {
      out.push(h("h3", {}, "Papel en el artículo"), h("p", {}, explanation.role_in_article.text));
    }
    out.push(h("h3", {}, "Incertidumbres"),
      explanation.limitations.length ? list(explanation.limitations) : h("p", { class: "muted" }, explanation.limitations_justification || "Ninguna indicada."));
    out.push(h("details", {}, h("summary", {}, `Todas las afirmaciones (${explanation.claims.length})`), list(explanation.claims.map((c) => c.id))));

    if (analysis.context.length) {
      const used = new Set(analysis.spans.map((s) => s.ref));
      out.push(h("details", {},
        h("summary", {}, `Fragmentos del artículo usados como contexto (${analysis.context.length})`),
        h("ul", { class: "ctx" }, analysis.context.map((c) => h("li", { class: used.has(c.ref) ? "cited" : "" },
          h("div", { class: "small muted" }, `${c.ref} · página ${c.page}${c.section ? ` · ${c.section}` : ""}${used.has(c.ref) ? " · citado" : ""}`),
          `${c.truncated ? "… " : ""}${c.text}${c.truncated ? " …" : ""}`))),
      ));
    }
    if (analysis.context_note) out.push(h("p", { class: "small muted" }, analysis.context_note));
    const run = analysis.run;
    if (run) {
      out.push(h("div", { class: "meta" },
        `${run.model} · ${run.prompt_version} · ${run.input_tokens} + ${run.output_tokens} tokens · ${usd.format(run.cost_usd)} USD · ${run.latency_s} s${run.reused ? " · resultado reutilizado, sin coste nuevo" : ""}`));
    }
    return out;
  }

  function legend() {
    let open = true;
    try { open = localStorage.getItem("sfi.legend") !== "closed"; } catch (_) { /* storage unavailable */ }
    const details = h("details", { open },
      h("summary", {}, "Cómo leer esta explicación"),
      h("div", { class: "legend" },
        Object.entries(TYPES).map(([type, [name, text]]) => h("div", {}, h("span", { class: `ct ${type}` }, name), h("span", {}, text))),
        h("div", { class: "small muted" }, "Pulsa una fuente («Pie», «Texto · p. 5») para ver de dónde sale cada afirmación."),
      ));
    details.addEventListener("toggle", () => {
      try { localStorage.setItem("sfi.legend", details.open ? "open" : "closed"); } catch (_) { /* ignore */ }
    });
    return details;
  }

  function claimItem(claim, issues) {
    const [name, help] = TYPES[claim.type];
    const evidence = claim.evidence.map((e, index) => {
      if (e.kind === "figure_region") {
        const panel = e.panel ? panels.get(e.panel.toLowerCase()) : null;
        return h("div", { class: "ev" }, h("button", { class: "src", type: "button", onclick: () => showFigure(panel) }, e.panel ? `Figura · panel ${e.panel}` : "Figura"));
      }
      let source;
      if (e.kind === "caption") {
        source = h("button", { class: "src", type: "button", onclick: flashCaption }, "Pie");
      } else {
        const span = spans.get(`${claim.id}:${index}`);
        source = span && passages.has(span.passage_id)
          ? h("button", { class: "src", type: "button", onclick: () => showPage(span.page, span.passage_id) },
            `Texto · p. ${span.page}${span.section ? ` · ${span.section}` : ""}`)
          : h("span", { class: "src missing" }, "Texto · cita no encontrada");
      }
      return h("div", { class: "ev" }, source, e.quote ? h("q", {}, e.quote) : null);
    });
    return h("li", { class: `claim${issues.some((i) => i.severity === "error") ? " flagged" : ""}` },
      h("span", { class: `ct ${claim.type}`, title: help }, name),
      claim.text,
      claim.panels.map((p) => panels.has(p.toLowerCase())
        ? h("button", { class: "panel-tag link", type: "button", title: `Ver el panel ${p}`, onclick: () => showFigure(panels.get(p.toLowerCase())) }, p)
        : h("span", { class: "panel-tag" }, p)),
      claim.approximate ? h("span", { class: "panel-tag", title: "Valor estimado leyendo la gráfica" }, "aprox.") : null,
      evidence.length ? h("div", { class: "evidence" }, evidence) : null,
      valuesByClaim.has(claim.id)
        ? h("div", { class: "ev" }, [...valuesByClaim.get(claim.id)].map(([value, refs]) =>
          h("button", { class: "src value", type: "button", title: "Ver dónde está impreso este valor en la figura", onclick: () => showFigure(null, refs) }, `«${value}» en la figura`)))
        : null,
      // "Number not found in the figure" is stored but not shown: with OCR at ~0.90 number
      // accuracy (E03) most of those warnings are OCR misses, not errors of the explanation.
      issues.filter((i) => i.code !== "number_not_in_figure")
        .map((i) => h("div", { class: `flag${i.severity === "warning" ? " warn" : ""}` }, i.message)),
    );
  }

  const go = (id) => { if (id) location.hash = `#/d/${docId}/f/${id}`; };
  mount(
    h("div", { class: "figbar" },
      h("h1", {}, fig.label || "Región sin etiqueta"),
      analysis ? badge(...(ANALYSIS_BADGE[analysis.status] || ["", "neutral"])) : badge("sin explicar", "neutral"),
      fig.confidence < LOW_CONFIDENCE ? badge("confianza de detección baja", "warn") : null,
      h("div", { class: "nav" },
        h("a", { class: "btn", href: `#/d/${docId}?f=${fig.id}` }, icon("arrow-left"), "Volver al visor"),
        fig.has_image ? h("a", { class: "btn", href: `/api/figures/${fig.id}/image?download=1`, download: "" }, icon("download"), "Descargar imagen") : null,
        h("span", { class: "kbd num" }, `${fig.position} de ${fig.count}`),
        h("button", { class: "btn icon", type: "button", disabled: !fig.previous, onclick: () => go(fig.previous), "aria-label": "Figura anterior", "data-tip": "Figura anterior (←)" }, icon("chevron-left")),
        h("button", { class: "btn icon tip-left", type: "button", disabled: !fig.next, onclick: () => go(fig.next), "aria-label": "Figura siguiente", "data-tip": "Figura siguiente (→)" }, icon("chevron-right")),
      ),
    ),
    h("div", { class: "figure-layout" },
      h("div", { class: "left" }, h("div", { class: "row" }, h("div", { class: "tabs", role: "tablist" }, tabFigure, tabPage), h("span", { class: "spacer" }), pager), viewer.el, captionBox),
      right,
    ),
  );
  showFigure();
  setKeys((e) => {
    if (typing(e)) return;
    if (e.key === "ArrowLeft") go(fig.previous);
    if (e.key === "ArrowRight") go(fig.next);
    if (e.key === "Escape") location.hash = `#/d/${docId}?f=${fig.id}`;
  });
  if (!analysis && fig.has_image) {
    // The document may still be processing: look again shortly.
    api(`/api/documents/${docId}`).then((doc) => { if (doc.job?.active) poll(() => renderFigure(docId, figId), 2500); }).catch(() => {});
  }
}
