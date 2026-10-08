"use strict";
// Figuris: the document workspace. Page thumbnails, the page with its detected regions and
// the details of the selected figure (viewer), or every figure as a catalogue (gallery).
// State that is worth sharing lives in the URL: #/d/<id>?p=<page>&f=<figure>&vista=galeria.

const MM_PER_PT = 25.4 / 72;
const figureCache = new Map(); // figure id -> detail from the API

function wsParams(state) {
  const q = new URLSearchParams();
  if (state.view === "galeria") q.set("vista", "galeria");
  if (state.page && state.view !== "galeria") q.set("p", String(state.page));
  if (state.selected) q.set("f", state.selected);
  const s = q.toString();
  return `#/d/${state.docId}${s ? `?${s}` : ""}`;
}

async function renderDocument(docId, params = {}) {
  let doc;
  try {
    doc = await api(`/api/documents/${docId}`);
  } catch (error) {
    setCrumbs(["Documentos", "#/documentos"], ["No encontrado"]);
    mount(alertBox("bad", error.message), h("p", {}, h("a", { href: "#/documentos" }, "Volver a los documentos")));
    return;
  }
  document.title = `${doc.filename} · Figuris`;
  setCrumbs(["Documentos", "#/documentos"], [doc.filename]);

  const figures = doc.figures.map((f) => ({ ...f, cat: category(f), low: f.confidence < LOW_CONFIDENCE }));
  const byId = new Map(figures.map((f) => [f.id, f]));
  const firstPage = figures.find((f) => f.box)?.page || 1;
  const narrow = window.matchMedia("(max-width: 1100px)").matches;
  const state = {
    docId,
    view: params.vista === "galeria" ? "galeria" : "visor",
    page: Math.min(Math.max(Number(params.p) || (byId.get(params.f)?.page ?? firstPage), 1), doc.pages),
    selected: byId.has(params.f) ? params.f : null,
    filter: "todas",
    query: "",
    regions: true,
    captions: false,
    layout: store("layout") || "grid",
    picked: new Set(),
    leftOpen: store("left") ? store("left") === "open" : !narrow,
    rightOpen: store("right") !== "closed",
    mobile: params.f ? "detail" : "page",
  };
  const pagesWithFigures = new Map();
  for (const f of figures) {
    if (!pagesWithFigures.has(f.page)) pagesWithFigures.set(f.page, []);
    pagesWithFigures.get(f.page).push(f);
  }
  const visible = () => figures.filter((f) => {
    if (state.filter !== "todas" && f.cat !== state.filter) return false;
    if (!state.query) return true;
    const q = plain(state.query);
    return [f.label, f.caption, f.summary, typeName(f)].some((t) => t && plain(t).includes(q));
  });
  const syncUrl = () => history.replaceState(null, "", wsParams(state));

  // --- header ------------------------------------------------------------------------
  const active = doc.job?.active;
  const explained = figures.filter((f) => f.analysis_status === "ok").length;
  const unreliable = figures.filter((f) => f.analysis_status === "invalid" || f.analysis_status === "incomplete").length;
  const statusBadge = active ? badge("Procesando", "busy")
    : doc.job?.status === "failed" ? badge("Con errores", "bad")
      : unreliable ? badge("Completado con avisos", "warn") : badge("Análisis completado", "ok");
  const pagesUsed = new Set(figures.map((f) => f.page)).size;

  const counts = { todas: figures.length };
  for (const f of figures) counts[f.cat] = (counts[f.cat] || 0) + 1;
  const filterDefs = [["todas", "Todas"], ...CATEGORIES.map(([k, label]) => [k, label]), ["sin", "Sin clasificar"]]
    .filter(([k]) => k === "todas" || counts[k]);
  const filterSeg = h("div", { class: "seg", role: "group", "aria-label": "Filtrar por tipo" },
    filterDefs.map(([key, label]) => h("button", {
      type: "button", "aria-pressed": String(state.filter === key),
      onclick: (e) => {
        state.filter = key;
        for (const b of filterSeg.children) b.setAttribute("aria-pressed", String(b === e.currentTarget));
        redraw();
      },
    }, label, h("span", { class: "count" }, String(counts[key] || 0)))));
  const viewSeg = h("div", { class: "seg", role: "group", "aria-label": "Vista" },
    h("button", { type: "button", "aria-pressed": String(state.view === "visor"), onclick: () => switchView("visor") }, icon("file-text"), "Visor"),
    h("button", { type: "button", "aria-pressed": String(state.view === "galeria"), onclick: () => switchView("galeria") }, icon("layout-grid"), "Galería"));

  const head = h("header", { class: "ws-head" },
    h("div", { class: "ws-title" },
      h("h1", { title: doc.filename }, doc.filename),
      h("div", { class: "meta" },
        statusBadge,
        h("span", { class: "num" }, `${figures.length} ${figures.length === 1 ? "figura detectada" : "figuras detectadas"} en ${doc.pages} páginas`),
        explained ? h("span", { class: "num" }, `${explained} explicadas`) : null)),
    h("div", { class: "ws-tools" },
      figures.length ? filterSeg : null,
      figures.length ? viewSeg : null,
      h("a", { class: "btn", href: `/api/documents/${docId}/pdf`, target: "_blank", rel: "noopener", "data-tip": "Abrir el PDF original" }, icon("external-link"), h("span", { class: "add-txt" }, "PDF")),
      figures.length ? h("button", {
        type: "button", class: "btn primary",
        onclick: () => { download(`/api/documents/${docId}/export`); toast(`Exportación completada: ${figures.length} figuras en JSON`); },
      }, icon("download"), "Exportar resultados") : null,
      menuButton("Más acciones del documento", [
        { icon: "refresh-cw", label: "Reprocesar el documento", action: () => reprocess(docId, doc.filename) },
        { icon: "file-json", label: "Exportar resultados (JSON)", action: () => { download(`/api/documents/${docId}/export`); toast("Exportación completada"); } },
      ])));

  const alerts = h("div", { class: "ws-alerts" },
    active ? alertBox("info", h("strong", {}, `${doc.job.stage}. `),
      doc.job.figures_total ? `${doc.job.figures_done} de ${doc.job.figures_total} figuras explicadas. ` : "",
      h("a", { href: `#/trabajo/${doc.job.id}` }, "Ver el progreso")) : null,
    !active && doc.job?.status === "failed" ? alertBox("bad", h("strong", {}, `${doc.job.stage}. `), doc.job.error || "") : null,
    doc.warnings.length ? h("details", {}, h("summary", {}, `Avisos de la extracción (${doc.warnings.length})`), h("ul", { class: "small" }, doc.warnings.map((w) => h("li", {}, w)))) : null);
  if (!alerts.childNodes.length) alerts.hidden = true;

  if (!figures.length) {
    mountWorkspace(head, alerts, h("div", { class: "gallery" },
      h("div", { class: "empty" },
        icon("file-text"),
        h("h2", {}, active ? "Extrayendo figuras…" : "No hemos encontrado figuras en este documento"),
        h("p", {}, active ? "Las figuras aparecerán aquí en cuanto termine la extracción."
          : "Puede que el artículo no tenga figuras o que estén en un formato que no se reconoce, como una página escaneada sin pies de figura."),
        active ? null : h("div", { class: "row" },
          h("a", { class: "btn", href: `/api/documents/${docId}/pdf`, target: "_blank", rel: "noopener" }, icon("external-link"), "Revisar el PDF"),
          h("button", { type: "button", class: "btn", onclick: () => reprocess(docId, doc.filename) }, icon("refresh-cw"), "Reprocesar")))));
    setSearch("Buscar en los pies", null);
    if (active) poll(() => renderDocument(docId, params), 2500);
    return;
  }

  // --- left: page thumbnails ----------------------------------------------------------
  const thumbs = h("ol", { class: "thumbs", "aria-label": "Páginas" });
  const thumbButtons = [];
  for (let n = 1; n <= doc.pages; n += 1) {
    const [w, hgt] = doc.page_sizes[n - 1] || [612, 792];
    const imgBox = h("div", { class: "thumb-img" }, h("img", { src: `/api/documents/${docId}/pages/${n}?thumb=1`, alt: "", loading: "lazy" }));
    imgBox.style.setProperty("--ar", String(w / hgt));
    for (const f of pagesWithFigures.get(n) || []) {
      if (!f.box) continue;
      const mini = h("span", { class: "ov-mini", "aria-hidden": "true" });
      mini.style.left = `${f.box[0] * 100}%`;
      mini.style.top = `${f.box[1] * 100}%`;
      mini.style.width = `${(f.box[2] - f.box[0]) * 100}%`;
      mini.style.height = `${(f.box[3] - f.box[1]) * 100}%`;
      imgBox.append(mini);
    }
    const count = (pagesWithFigures.get(n) || []).length;
    const button = h("button", {
      type: "button", class: "thumb-btn",
      "aria-label": `Página ${n}${count ? `, ${count} ${count === 1 ? "figura" : "figuras"}` : ""}`,
      onclick: () => { goPage(n); if (isMobile()) setMobile("page"); },
    }, imgBox, h("div", { class: "thumb-cap" }, h("span", { class: "num" }, `p. ${n}`), count ? h("span", { class: "count-pill", title: `${count} figuras` }, String(count)) : null));
    thumbButtons.push(button);
    thumbs.append(h("li", {}, button));
  }
  const jump = h("input", {
    class: "input", type: "number", min: "1", max: String(doc.pages), inputmode: "numeric", "aria-label": "Ir a la página", placeholder: "Ir a",
    onkeydown: (e) => {
      if (e.key !== "Enter") return;
      const n = Number(jump.value);
      if (n >= 1 && n <= doc.pages) { goPage(n); jump.value = ""; }
    },
  });
  const left = h("aside", { class: "pane pane-left", "aria-label": "Páginas del documento" },
    h("div", { class: "pane-head" }, h("span", { class: "ttl" }, `${doc.pages} páginas`), h("span", { class: "spacer" }), jump),
    thumbs);

  // --- center: the page --------------------------------------------------------------
  const viewer = createViewer();
  const pageLabel = h("span", { class: "pg" });
  const prev = iconButton("chevron-left", "Página anterior", () => goPage(state.page - 1), { cls: "sm" });
  const next = iconButton("chevron-right", "Página siguiente", () => goPage(state.page + 1), { cls: "sm" });
  const regionsToggle = h("input", { type: "checkbox", checked: state.regions, onchange: (e) => { state.regions = e.target.checked; drawPage(); } });
  const captionsToggle = h("input", { type: "checkbox", checked: state.captions, onchange: (e) => { state.captions = e.target.checked; drawPage(); } });
  const leftToggle = iconButton("panel-left-close", "Ocultar las páginas", () => setPane("left", !state.leftOpen), { cls: "sm quiet pane-tg" });
  const rightToggle = iconButton("panel-right-close", "Ocultar los detalles", () => setPane("right", !state.rightOpen), { cls: "sm quiet tip-left pane-tg" });
  const center = h("section", { class: "pane-center", "aria-label": "Página del documento" },
    h("div", { class: "view-bar" },
      leftToggle, prev, pageLabel, next,
      h("span", { class: "spacer" }),
      h("label", { class: "toggle", title: "Mostrar regiones detectadas" }, regionsToggle, "Regiones"),
      h("label", { class: "toggle", title: "Mostrar los pies de figura" }, captionsToggle, "Pies"),
      rightToggle),
    viewer.el);
  viewer.onTap(([x, y]) => {
    const hits = (state.regions ? visible() : []).filter((f) => f.page === state.page && f.box
      && x >= f.box[0] && x <= f.box[2] && y >= f.box[1] && y <= f.box[3]);
    hits.sort((a, b) => (a.box[2] - a.box[0]) * (a.box[3] - a.box[1]) - (b.box[2] - b.box[0]) * (b.box[3] - b.box[1]));
    select(hits[0]?.id || null, { focus: false });
  });

  function drawPage(focusBox = null, passageBoxes = []) {
    pageLabel.textContent = `${state.page} / ${doc.pages}`;
    prev.disabled = state.page <= 1;
    next.disabled = state.page >= doc.pages;
    thumbButtons.forEach((b, i) => b.setAttribute("aria-current", String(i + 1 === state.page)));
    const boxes = [];
    if (state.regions) {
      for (const f of visible()) {
        if (f.page !== state.page || !f.box) continue;
        const sel = f.id === state.selected;
        const type = typeName(f);
        boxes.push({
          box: f.box,
          cls: `fig${f.low ? " low" : ""}${sel ? " sel" : ""}${state.selected && !sel ? " dim" : ""}`,
          label: `${f.label || "Región"}${type ? ` · ${type}` : ""}${f.low ? " · revisar" : ""}`,
        });
      }
    }
    if (state.captions) {
      for (const f of figures) {
        if (f.caption_page === state.page && f.caption_box) boxes.push({ box: f.caption_box, cls: "cap", label: `Pie · ${f.label || ""}`.trim() });
      }
    }
    for (const box of passageBoxes) boxes.push({ box, cls: "psg active", label: "texto que la cita" });
    viewer.show(`/api/documents/${docId}/pages/${state.page}`, `Página ${state.page} de ${doc.filename}`, boxes, focusBox);
  }

  function goPage(n, focusBox = null, passageBoxes = []) {
    if (n < 1 || n > doc.pages) return;
    state.page = n;
    drawPage(focusBox, passageBoxes);
    thumbButtons[n - 1]?.scrollIntoView({ block: "nearest" });
    if (!state.selected) drawDetail();
    syncUrl();
  }

  // --- right: details ----------------------------------------------------------------
  const right = h("aside", { class: "pane pane-right", "aria-label": "Detalles", "aria-live": "polite" });

  function figureListItems(list) {
    return h("ul", { class: "fig-list" }, list.map((f) => h("li", {}, h("button", { type: "button", onclick: () => select(f.id, { focus: true }) },
      h("span", { class: "mini" }, f.has_image ? h("img", { src: `/api/figures/${f.id}/image`, alt: "", loading: "lazy" }) : icon("file-text")),
      h("span", {}, h("span", { class: "l" }, figLabel(f)),
        h("span", { class: "c" }, [typeName(f), f.low ? "confianza baja" : null].filter(Boolean).join(" · ") || "sin clasificar"))))));
  }

  function drawDetail() {
    const f = state.selected && byId.get(state.selected);
    if (!f) {
      const here = visible().filter((x) => x.page === state.page);
      right.replaceChildren(h("div", { class: "detail" },
        h("div", { class: "detail-head" }, h("div", {}, h("h2", {}, `Página ${state.page}`),
          h("div", { class: "sub" }, here.length ? `${here.length} ${here.length === 1 ? "figura detectada" : "figuras detectadas"}` : "Sin figuras detectadas en esta página"))),
        here.length ? figureListItems(here) : null,
        h("p", { class: "small muted" }, here.length
          ? "Pulsa una región en la página o en la lista para ver su pie, su tipo y la confianza de la detección."
          : "Usa las miniaturas o las flechas para ir a una página con figuras."),
        here.length ? null : h("div", {}, h("h3", {}, "Figuras del documento"), figureListItems(visible()))));
      return;
    }
    const detail = figureCache.get(f.id);
    const type = typeName(f);
    const [badgeText, badgeKind] = ANALYSIS_BADGE[f.analysis_status] || (active ? ["en proceso", "busy"] : ["sin explicar", "neutral"]);
    const size = detail?.size_pt ? `${Math.round(detail.size_pt[0] * MM_PER_PT)} × ${Math.round(detail.size_pt[1] * MM_PER_PT)} mm` : f.box ? "…" : "—";
    const context = detail?.analysis?.context || [];
    const passages = new Map((detail?.passages || []).map((p) => [p.id, p]));
    const spanByRef = new Map((detail?.analysis?.spans || []).map((s) => [s.ref, s]));
    right.replaceChildren(h("div", { class: "detail" },
      h("div", { class: "detail-head" },
        h("div", { class: "grow" },
          h("h2", {}, f.label || "Región sin etiqueta"),
          h("div", { class: "sub" }, [type ? type[0].toUpperCase() + type.slice(1) : "Sin clasificar", `página ${f.page}`].join(" · "))),
        h("span", { class: "spacer" }),
        iconButton("x", "Cerrar los detalles", () => select(null), { cls: "sm quiet tip-left" })),
      f.low ? alertBox("warn", h("strong", {}, "Revisa esta región: "), "la confianza de detección es baja. Comprueba en la página que la caja rodea la figura completa.") : null,
      f.status === "caption_only" ? alertBox("info", "Solo se detectó el pie: esta figura no tiene región en la página.") : null,
      f.status === "region_only" ? alertBox("info", "Región sin pie asociado.") : null,
      h("a", { class: "preview", href: `#/d/${docId}/f/${f.id}`, "aria-label": `Ver la explicación de ${f.label || "la figura"}` },
        f.has_image ? h("img", { src: `/api/figures/${f.id}/image`, alt: f.label || "Figura" }) : h("div", { class: "none" }, "Sin imagen de la figura")),
      h("dl", { class: "facts" },
        h("dt", {}, "Tipo"), h("dd", {}, type || h("span", { class: "muted" }, "sin clasificar")),
        h("dt", {}, "Página"), h("dd", {}, String(f.page)),
        h("dt", {}, "Confianza"), h("dd", {}, confidenceMeter(f.confidence)),
        h("dt", {}, "Región"), h("dd", { class: "num" }, size),
        f.panels ? [h("dt", {}, "Paneles"), h("dd", {}, String(f.panels))] : null,
        h("dt", {}, "Explicación"), h("dd", {}, badge(badgeText, badgeKind))),
      h("div", {},
        h("div", { class: "block-head" }, h("h3", {}, "Pie de figura"),
          f.caption ? iconButton("copy", "Copiar el pie", () => copyText(f.caption, "Pie"), { cls: "sm quiet tip-left" }) : null),
        f.caption ? h("div", { class: "caption" }, f.caption) : h("p", { class: "small muted" }, "No se detectó el pie de esta figura.")),
      f.summary ? h("div", {}, h("h3", {}, "Resumen"), h("div", { class: "summary-box" }, f.summary)) : null,
      h("div", {},
        h("h3", {}, "Referencias en el texto"),
        !detail ? h("p", { class: "small muted" }, "Cargando…")
          : context.length ? h("ul", { class: "refs" }, context.map((c) => {
            const span = spanByRef.get(c.ref);
            const segs = span && passages.get(span.passage_id)?.segments || [];
            return h("li", {}, h("button", {
              type: "button",
              onclick: () => {
                const onPage = segs.filter((s) => s.page === c.page).map((s) => s.box);
                goPage(c.page, onPage[0] || null, onPage);
                if (isMobile()) setMobile("page");
              },
            }, h("span", { class: "where" }, `Página ${c.page}${c.section ? ` · ${c.section}` : ""}${span ? " · citado en la explicación" : ""}`),
            h("span", { class: "snip" }, c.text)));
          }))
            : h("p", { class: "small muted" }, f.analysis_status ? "La explicación no usó párrafos del artículo." : "Aparecerán cuando la figura esté explicada.")),
      h("div", { class: "actions-grid" },
        h("a", { class: "btn primary wide", href: `#/d/${docId}/f/${f.id}` }, "Ver la explicación con su evidencia", icon("arrow-right")),
        f.has_image ? h("a", { class: "btn", href: `/api/figures/${f.id}/image?download=1`, download: "" }, icon("download"), "Descargar imagen") : null,
        f.caption ? h("button", { type: "button", class: "btn", onclick: () => copyText(f.caption, "Pie") }, icon("copy"), "Copiar pie") : null,
        h("a", { class: "btn", href: `/api/documents/${docId}/pdf#page=${f.page}`, target: "_blank", rel: "noopener" }, icon("external-link"), "Ver en el PDF"))));
    if (!detail) {
      api(`/api/documents/${docId}/figures/${f.id}`).then((d) => {
        figureCache.set(f.id, d);
        if (state.selected === f.id) drawDetail();
      }).catch(() => {});
    }
  }

  function select(id, { focus = false } = {}) {
    state.selected = id;
    const f = id && byId.get(id);
    if (f && state.view === "galeria") switchView("visor");
    if (f && !state.rightOpen) setPane("right", true);
    if (f && f.page !== state.page) {
      state.page = f.page;
      drawPage(focus && f.box ? f.box : null);
    } else {
      drawPage(focus && f?.box ? f.box : null);
    }
    drawDetail();
    syncUrl();
    if (f && isMobile()) setMobile("detail");
  }

  // --- gallery -----------------------------------------------------------------------
  const gallery = h("section", { class: "gallery", "aria-label": "Galería de figuras" });

  function drawGallery() {
    const list = visible();
    const picked = [...state.picked].filter((id) => byId.has(id));
    const allPicked = list.length > 0 && list.every((f) => state.picked.has(f.id));
    const selectAll = h("input", {
      type: "checkbox", "aria-label": "Seleccionar todas las figuras visibles", checked: allPicked,
      onchange: (e) => { for (const f of list) e.target.checked ? state.picked.add(f.id) : state.picked.delete(f.id); drawGallery(); },
    });
    selectAll.indeterminate = !allPicked && list.some((f) => state.picked.has(f.id));
    const layoutSeg = h("div", { class: "seg", role: "group", "aria-label": "Disposición" },
      h("button", { type: "button", "aria-pressed": String(state.layout === "grid"), "aria-label": "Cuadrícula", "data-tip": "Cuadrícula", onclick: () => { state.layout = "grid"; store("layout", "grid"); drawGallery(); } }, icon("layout-grid")),
      h("button", { type: "button", "aria-pressed": String(state.layout === "list"), "aria-label": "Lista detallada", "data-tip": "Lista detallada", onclick: () => { state.layout = "list"; store("layout", "list"); drawGallery(); } }, icon("list")));
    const tools = picked.length ? h("div", { class: "sel-tools" },
      h("strong", { class: "num" }, `${picked.length} ${picked.length === 1 ? "seleccionada" : "seleccionadas"}`),
      h("button", { type: "button", class: "btn sm primary", onclick: () => { download(`/api/documents/${docId}/export?figures=${encodeURIComponent(picked.join(","))}`); toast(`Exportación completada: ${picked.length} figuras en JSON`); } }, icon("file-json"), "Exportar figuras seleccionadas"),
      h("button", { type: "button", class: "btn sm", onclick: () => downloadImages(picked) }, icon("download"), "Descargar imágenes"),
      iconButton("x", "Quitar la selección", () => { state.picked.clear(); drawGallery(); }, { cls: "sm quiet" })) : null;

    const items = list.map((f) => {
      const checked = state.picked.has(f.id);
      const type = typeName(f);
      return h("li", { class: `cat-item${checked ? " selected" : ""}` },
        h("label", { class: "check" }, h("input", {
          type: "checkbox", checked, "aria-label": `Seleccionar ${figLabel(f)}`,
          onchange: (e) => { e.target.checked ? state.picked.add(f.id) : state.picked.delete(f.id); drawGallery(); },
        })),
        h("button", { type: "button", class: "frame", "aria-label": `Abrir ${figLabel(f)} en el visor`, onclick: () => select(f.id, { focus: true }) },
          f.has_image ? h("img", { src: `/api/figures/${f.id}/image`, alt: "", loading: "lazy" }) : h("span", { class: "none" }, "Solo se detectó el pie")),
        h("div", {},
          h("div", { class: "ttl" }, h("strong", {}, f.label || "Región sin etiqueta"), h("span", { class: "pg" }, `p. ${f.page}`)),
          h("div", { class: "typ" }, type || "sin clasificar"),
          f.caption ? h("div", { class: "cap" }, f.caption) : h("div", { class: "cap muted" }, "Sin pie detectado.")),
        state.layout === "list"
          ? h("div", { class: "side" }, confidenceMeter(f.confidence), badge(...(ANALYSIS_BADGE[f.analysis_status] || ["sin explicar", "neutral"])))
          : h("div", { class: "small muted" }, confidenceMeter(f.confidence)));
    });
    gallery.replaceChildren(
      h("div", { class: "gal-bar" },
        h("label", { class: "toggle" }, selectAll, `${list.length} ${list.length === 1 ? "figura" : "figuras"}`),
        tools,
        h("span", { class: "spacer" }),
        layoutSeg),
      list.length ? h("ul", { class: state.layout === "list" ? "cat-list" : "cat-grid" }, items)
        : h("div", { class: "empty" }, `Ninguna figura coincide${state.query ? ` con «${state.query}»` : " con el filtro"}.`));
  }

  async function downloadImages(ids) {
    const withImage = ids.map((id) => byId.get(id)).filter((f) => f?.has_image);
    for (const f of withImage) {
      download(`/api/figures/${f.id}/image?download=1`);
      await new Promise((r) => setTimeout(r, 250));
    }
    toast(`${withImage.length} ${withImage.length === 1 ? "imagen descargada" : "imágenes descargadas"}`);
  }

  // --- layout: panes, splitters, mobile ----------------------------------------------
  const body = h("div", { class: "ws-body", "data-mobile": state.mobile });
  const leftW = store("leftW"), rightW = store("rightW");
  if (leftW) body.style.setProperty("--left-w", `${leftW}px`);
  if (rightW) body.style.setProperty("--right-w", `${rightW}px`);

  function splitter(side) {
    const min = side === "left" ? 140 : 280, max = side === "left" ? 320 : 560;
    const current = () => parseInt(getComputedStyle(body).getPropertyValue(`--${side}-w`), 10) || (side === "left" ? 196 : 360);
    const set = (w) => {
      const v = Math.round(Math.min(Math.max(w, min), max));
      body.style.setProperty(`--${side}-w`, `${v}px`);
      el.setAttribute("aria-valuenow", String(v));
      store(`${side}W`, String(v));
    };
    const el = h("button", {
      type: "button", class: `split split-${side}`, role: "separator", "aria-orientation": "vertical",
      "aria-label": side === "left" ? "Ancho del panel de páginas" : "Ancho del panel de detalles",
      "aria-valuemin": String(min), "aria-valuemax": String(max), "aria-valuenow": String(current()),
      onkeydown: (e) => {
        const step = e.shiftKey ? 48 : 16;
        if (e.key === "ArrowLeft") { e.preventDefault(); set(current() + (side === "left" ? -step : step)); }
        if (e.key === "ArrowRight") { e.preventDefault(); set(current() + (side === "left" ? step : -step)); }
      },
    });
    el.addEventListener("pointerdown", (e) => {
      const start = e.clientX, w0 = current();
      el.setPointerCapture(e.pointerId);
      el.classList.add("dragging");
      const move = (ev) => set(w0 + (side === "left" ? ev.clientX - start : start - ev.clientX));
      const up = () => { el.classList.remove("dragging"); el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
    });
    return el;
  }

  function setPane(side, open, remember = true) {
    if (side === "left") state.leftOpen = open; else state.rightOpen = open;
    body.classList.toggle(`${side}-closed`, !open);
    if (remember) store(side, open ? "open" : "closed");
    const btn = side === "left" ? leftToggle : rightToggle;
    const label = side === "left" ? (open ? "Ocultar las páginas" : "Mostrar las páginas") : (open ? "Ocultar los detalles" : "Mostrar los detalles");
    btn.replaceChildren(icon(side === "left" ? (open ? "panel-left-close" : "panel-left-open") : (open ? "panel-right-close" : "panel-right-open")));
    btn.setAttribute("aria-label", label);
    btn.setAttribute("data-tip", label);
    btn.setAttribute("aria-pressed", String(!open));
  }

  const isMobile = () => window.matchMedia("(max-width: 760px)").matches;
  const mobileSeg = h("div", { class: "seg", role: "group", "aria-label": "Sección" },
    [["pages", "Páginas"], ["page", "Página"], ["detail", "Detalle"]].map(([key, label]) =>
      h("button", { type: "button", "data-key": key, "aria-pressed": String(state.mobile === key), onclick: () => setMobile(key) }, label)));
  function setMobile(key) {
    state.mobile = key;
    body.dataset.mobile = key;
    for (const b of mobileSeg.children) b.setAttribute("aria-pressed", String(b.dataset.key === key));
    if (key === "page") requestAnimationFrame(() => viewer.reset());
  }
  const paneSwitch = h("div", { class: "pane-switch" }, mobileSeg);

  function switchView(next) {
    state.view = next;
    for (const b of viewSeg.children) b.setAttribute("aria-pressed", String(b.textContent.trim().toLowerCase() === (next === "galeria" ? "galería" : "visor")));
    body.hidden = next === "galeria";
    paneSwitch.hidden = next === "galeria";
    gallery.hidden = next !== "galeria";
    redraw();
    syncUrl();
    if (next === "visor") requestAnimationFrame(() => viewer.reset());
  }

  function redraw() {
    if (state.view === "galeria") drawGallery();
    else { drawPage(); drawDetail(); }
  }

  body.append(left, splitter("left"), center, splitter("right"), right);
  mountWorkspace(head, alerts, paneSwitch, body, gallery);
  setPane("left", state.leftOpen, false);
  setPane("right", state.rightOpen, false);
  setSearch("Buscar en los pies de figura", (q) => { state.query = q; redraw(); });
  gallery.hidden = state.view !== "galeria";
  body.hidden = state.view === "galeria";
  paneSwitch.hidden = state.view === "galeria";
  if (state.view === "galeria") drawGallery();
  else {
    drawPage(byId.get(state.selected)?.box || null);
    drawDetail();
  }
  requestAnimationFrame(() => thumbButtons[state.page - 1]?.scrollIntoView({ block: "nearest" }));

  setKeys((e) => {
    if (typing(e) || state.view !== "visor") return;
    if (e.target.closest(".split, [role='menu']")) return;
    if (e.key === "ArrowLeft") goPage(state.page - 1);
    if (e.key === "ArrowRight") goPage(state.page + 1);
    if (e.key === "Escape" && state.selected) select(null);
  });
  if (active) poll(() => renderDocument(docId, Object.fromEntries(new URLSearchParams(location.hash.split("?")[1] || ""))), 3000);
}
