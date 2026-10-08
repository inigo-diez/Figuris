"use strict";
// Figuris: start page, document list, processing and settings. Uses the helpers of app.js.

// --- documents table (start page and "Documentos") ---------------------------------------

function jobState(job) {
  if (!job) return null;
  if (job.active) {
    const analyzing = job.status === "analyzing" && job.figures_total > 0;
    const bar = h("div", { class: `progress${analyzing ? "" : " indeterminate"}`, role: "progressbar", "aria-label": "Progreso" }, h("div"));
    if (analyzing) {
      const value = Math.round((100 * job.figures_done) / job.figures_total);
      bar.firstChild.style.width = `${value}%`;
      bar.setAttribute("aria-valuenow", String(value));
    }
    const text = job.status === "queued" ? "En cola"
      : analyzing ? `Explicando ${job.figures_done}/${job.figures_total}` : "Extrayendo figuras";
    return h("div", { class: "status-cell" }, badge(text, "busy"), bar);
  }
  if (job.status === "failed") return h("div", { class: "status-cell" }, badge("Error", "bad"), h("span", { class: "small muted" }, job.stage));
  return null;
}

function documentRow(d) {
  const running = jobState(d.job);
  const state = running || (d.unreliable
    ? h("div", { class: "status-cell" }, badge("Completado con avisos", "warn"), h("span", { class: "small muted" }, `${d.unreliable} explicación(es) no fiables`))
    : d.figures === 0 ? badge("Sin figuras", "neutral") : badge("Completado", "ok"));
  return h("tr", {},
    h("td", {}, h("div", { class: "doc-name" }, icon("file-text"), h("a", { href: `#/d/${d.id}` }, d.filename))),
    h("td", {}, state),
    h("td", { class: "num" }, h("span", { class: "num" }, String(d.figures)), d.figures ? h("div", { class: "small muted" }, `${d.explained} explicadas`) : null),
    h("td", { class: "num" }, String(d.pages)),
    h("td", { class: "small muted" }, dateFmt.format(new Date(d.created_at))),
    h("td", { class: "actions" },
      h("div", { class: "row" },
        h("a", { class: "btn sm", href: `#/d/${d.id}` }, "Abrir"),
        menuButton(`Más acciones para ${d.filename}`, [
          { icon: "layout-grid", label: "Ver galería de figuras", href: `#/d/${d.id}?vista=galeria` },
          { icon: "external-link", label: "Abrir el PDF original", href: `/api/documents/${d.id}/pdf`, target: "_blank" },
          d.figures ? { icon: "file-json", label: "Exportar resultados (JSON)", action: () => { download(`/api/documents/${d.id}/export`); toast("Exportación completada"); } } : null,
          { icon: "refresh-cw", label: "Reprocesar", action: () => reprocess(d.id, d.filename) },
        ]))),
  );
}

function pendingRow(job) {
  return h("tr", {},
    h("td", {}, h("div", { class: "doc-name" }, icon("file-text"),
      job.active ? h("a", { href: `#/trabajo/${job.id}` }, job.filename) : h("span", {}, job.filename))),
    h("td", {}, jobState(job) || badge("Error", "bad"), job.error ? h("div", { class: "small muted" }, job.error) : null),
    h("td", { class: "num" }, "—"), h("td", { class: "num" }, "—"),
    h("td", { class: "small muted" }, dateFmt.format(new Date(job.created_at))),
    h("td", { class: "actions" }, job.active ? h("a", { class: "btn sm", href: `#/trabajo/${job.id}` }, "Ver progreso") : null),
  );
}

async function reprocess(id, filename) {
  try {
    const job = await api(`/api/documents/${id}/reprocess`, { method: "POST" });
    toast(`${filename}: en cola. Lo ya analizado se reutiliza`);
    location.hash = `#/trabajo/${job.id}`;
  } catch (error) {
    toast(error.message, "bad");
  }
}

// A table of documents that refreshes while something is processing.
function documentsTable({ limit = null } = {}) {
  const body = h("tbody");
  const wrap = h("div", { class: "card table-card" },
    h("table", { class: "data" },
      h("caption", { class: "sr-only" }, "Análisis de documentos"),
      h("thead", {}, h("tr", {},
        h("th", { scope: "col" }, "Documento"), h("th", { scope: "col" }, "Estado"),
        h("th", { scope: "col", class: "num" }, "Figuras"), h("th", { scope: "col", class: "num" }, "Páginas"),
        h("th", { scope: "col" }, "Fecha"), h("th", { scope: "col", class: "actions" }, h("span", { class: "sr-only" }, "Acciones")))),
      body));
  let filter = "";
  let data = { documents: [], pending: [] };

  function draw() {
    const q = plain(filter);
    const docs = data.documents.filter((d) => !q || plain(d.filename).includes(q));
    const pending = data.pending.filter((j) => !q || plain(j.filename).includes(q));
    const rows = [...pending.map(pendingRow), ...(limit ? docs.slice(0, limit) : docs).map(documentRow)];
    body.replaceChildren(...(rows.length ? rows : [h("tr", {}, h("td", { colspan: "6" },
      h("div", { class: "empty" }, q ? `Ningún documento coincide con «${filter}».` : "Todavía no has analizado ningún documento.")))]));
  }

  async function refresh() {
    try {
      const [documents, jobs] = await Promise.all([api("/api/documents"), api("/api/jobs")]);
      const known = new Set(documents.map((d) => d.id));
      // Jobs that have not produced a document yet (queued, extracting, or rejected).
      const pending = jobs.filter((j) => (!j.document_id || !known.has(j.document_id)) && (j.active || j.status === "failed")).slice(0, 5);
      data = { documents, pending };
      draw();
      recentDocs = documents;
      activeJobs = jobs.filter((j) => j.active).length;
      renderSidebar();
      renderSys();
      if (activeJobs) poll(refresh, 2000);
    } catch (error) {
      body.replaceChildren(h("tr", {}, h("td", { colspan: "6" }, alertBox("bad", error.message))));
    }
  }
  refresh();
  return { el: wrap, filter: (q) => { filter = q; draw(); }, count: () => data.documents.length };
}

// --- start page --------------------------------------------------------------------------

function renderHome() {
  document.title = "Figuris";
  setCrumbs(["Nuevo análisis"]);
  const input = h("input", { type: "file", accept: "application/pdf,.pdf", multiple: true, class: "sr-only", id: "home-file", tabindex: "-1" });
  const message = h("div", { class: "upload-msg", "aria-live": "polite" });
  const limits = h("span", {}, "PDF de hasta 50 MB y 100 páginas.");
  const drop = h("section", { class: "upload", "aria-label": "Subir documentos" },
    h("div", {},
      h("div", { class: "idle-msg" },
        h("div", { class: "lead" }, "Arrastra aquí uno o varios artículos"),
        h("div", { class: "muted" }, "Cada PDF se procesa por separado: se localizan sus figuras, sus pies y los párrafos que las citan.")),
      h("div", { class: "over-msg", "aria-hidden": "true" }, "Suelta los archivos para analizarlos"),
      h("div", { class: "row" },
        h("button", { type: "button", class: "btn primary", onclick: () => input.click() }, icon("upload"), "Seleccionar PDF"),
        h("button", { type: "button", class: "btn", onclick: () => input.click() }, icon("files"), "Añadir varios documentos")),
      h("div", { class: "formats" }, limits, " Los archivos se guardan solo en este equipo."),
      message),
    pageSketch(),
    input,
  );
  api("/api/status").then((s) => {
    limits.textContent = `PDF de hasta ${s.max_pdf_mb} MB y ${s.max_pages} páginas.`;
  }).catch(() => {});

  input.addEventListener("change", () => { uploadFiles(input.files, message); input.value = ""; });
  let depth = 0;
  drop.addEventListener("dragenter", (e) => { e.preventDefault(); depth += 1; drop.classList.add("over"); });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; });
  drop.addEventListener("dragleave", () => { depth -= 1; if (depth <= 0) { depth = 0; drop.classList.remove("over"); } });
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    depth = 0;
    drop.classList.remove("over");
    uploadFiles(e.dataTransfer.files, message);
  });

  const table = documentsTable({ limit: 8 });
  setSearch("Buscar documentos", (q) => table.filter(q));
  mount(
    h("header", { class: "page-head" },
      h("h1", {}, "Analiza las figuras de un artículo"),
      h("p", {}, "Sube un PDF para localizar y extraer sus figuras y sus pies. Cada figura se explica con citas comprobadas del propio artículo.")),
    drop,
    h("div", { class: "section-head" }, h("h2", {}, "Análisis recientes"), h("a", { class: "small", href: "#/documentos" }, "Ver todos")),
    table.el,
  );
}

// --- all documents -----------------------------------------------------------------------

function renderDocuments() {
  document.title = "Documentos · Figuris";
  setCrumbs(["Documentos"]);
  const table = documentsTable();
  setSearch("Buscar documentos", (q) => table.filter(q));
  mount(
    h("header", { class: "page-head row" },
      h("div", {}, h("h1", {}, "Documentos"), h("p", {}, "Todos los artículos analizados en este equipo.")),
      h("span", { class: "spacer" }),
      h("button", { type: "button", class: "btn", onclick: () => document.getElementById("global-file").click() }, icon("plus"), "Añadir documentos")),
    table.el,
  );
}

// --- processing --------------------------------------------------------------------------

const PHASES = [
  ["queued", "En cola", "El documento espera su turno; se procesa uno cada vez."],
  ["extracting", "Lectura y extracción", "Páginas, regiones de figura, pies y párrafos que las citan."],
  ["analyzing", "Explicación de las figuras", "Cada figura se explica y sus citas se comprueban contra el artículo."],
  ["completed", "Análisis completado", null],
];
const ORDER = { queued: 0, extracting: 1, analyzing: 2, completed: 3, failed: -1 };

async function renderJob(jobId) {
  let job;
  try {
    job = await api(`/api/jobs/${jobId}`);
  } catch (error) {
    setCrumbs(["Procesamiento"]);
    mount(alertBox("bad", error.message));
    return;
  }
  document.title = `${job.filename} · Procesando`;
  setCrumbs(["Nuevo análisis", "#/"], [job.filename]);
  setSearch("Buscar", null);

  // Where the job is; a failed job stops at the phase it was in.
  const failedAt = job.status === "failed" ? (job.document_id ? 2 : 1) : null;
  const current = failedAt ?? ORDER[job.status];
  const phases = PHASES.map(([key, title, desc], i) => {
    const state = failedAt === i ? "failed" : i < current || job.status === "completed" ? "done" : i === current ? "current" : "pending";
    let extra = null;
    if (state === "current" && key === "extracting") extra = h("div", { class: "progress indeterminate", role: "progressbar", "aria-label": "Extrayendo" }, h("div"));
    if (key === "analyzing" && job.figures_total && (state === "current" || state === "done")) {
      const value = Math.round((100 * job.figures_done) / job.figures_total);
      extra = [h("div", { class: "progress", role: "progressbar", "aria-valuenow": String(value), "aria-label": "Figuras explicadas" }, h("div")),
        h("div", { class: "d num" }, `${job.figures_done} de ${job.figures_total} figuras`)];
      extra[0].firstChild.style.width = `${value}%`;
    }
    const doneText = key === "completed" && job.status === "completed"
      ? `${job.figures_total} ${job.figures_total === 1 ? "figura detectada" : "figuras detectadas"}` : null;
    return h("li", { class: `phase ${state}`, "aria-current": state === "current" ? "step" : null },
      h("span", { class: "mark", "aria-hidden": "true" }, state === "done" ? icon("check") : state === "failed" ? icon("x") : null),
      h("div", {},
        h("div", { class: "t" }, title, h("span", { class: "sr-only" }, ` (${{ done: "hecho", current: "en curso", pending: "pendiente", failed: "error" }[state]})`)),
        state === "failed" ? h("div", { class: "d" }, job.stage) : desc || doneText ? h("div", { class: "d" }, doneText || desc) : null,
        extra));
  });

  const thumb = job.document_id
    ? h("img", { src: `/api/documents/${job.document_id}/pages/1?thumb=1`, alt: "Primera página del documento" })
    : pageSketch();
  const actions = [];
  if (job.status === "completed" && job.document_id) {
    actions.push(h("a", { class: "btn primary", href: `#/d/${job.document_id}` }, "Ver resultados", icon("arrow-right")));
  }
  if (job.status === "failed") {
    actions.push(h("button", { type: "button", class: "btn primary", onclick: () => document.getElementById("global-file").click() }, icon("upload"), "Subir otro PDF"));
    if (job.document_id) actions.push(h("a", { class: "btn", href: `#/d/${job.document_id}` }, "Ver lo extraído"));
  }
  actions.push(h("a", { class: "btn quiet", href: "#/" }, "Volver al inicio"));

  mount(
    h("header", { class: "page-head" }, h("h1", {}, job.status === "completed" ? "Análisis completado" : job.status === "failed" ? "No se pudo completar el análisis" : "Analizando el documento")),
    h("section", { class: "card processing", "aria-live": "polite" },
      h("div", { class: "proc-thumb" }, thumb),
      h("div", {},
        h("div", { class: "proc-file" }, job.filename),
        h("div", { class: "small muted" }, job.status === "completed"
          ? `${job.figures_total} ${job.figures_total === 1 ? "figura detectada" : "figuras detectadas"}`
          : job.status === "failed" ? "El análisis se detuvo" : "Puedes seguir trabajando: el análisis continúa aunque cambies de pantalla."),
        job.status === "failed" ? alertBox("bad", h("strong", {}, `${job.stage}. `), job.error || "") : null,
        job.warnings?.length ? alertBox("warn", h("ul", {}, job.warnings.map((w) => h("li", {}, w)))) : null,
        h("ol", { class: "phases" }, phases),
        h("div", { class: "row" }, actions))),
  );
  if (job.active) poll(() => renderJob(jobId), 1500);
  else refreshService();
}

// --- settings (read-only: configured in .env) --------------------------------------------

async function renderSettings() {
  document.title = "Configuración · Figuris";
  setCrumbs(["Configuración"]);
  setSearch("Buscar", null);
  let s;
  try {
    s = await api("/api/status");
  } catch (error) {
    mount(alertBox("bad", error.message));
    return;
  }
  const spent = Math.min(1, s.spent_usd / Math.max(s.budget_usd, 0.0001));
  const meter = h("div", { class: "meter" }, h("div"));
  meter.style.width = "160px";
  meter.firstChild.style.width = `${Math.round(spent * 100)}%`;
  mount(
    h("header", { class: "page-head" },
      h("h1", {}, "Configuración"),
      h("p", {}, "Valores con los que funciona esta instalación. Se cambian en el archivo ", h("span", { class: "code" }, ".env"), " y se aplican al reiniciar la aplicación.")),
    h("div", { class: "settings" },
      h("section", { class: "card pad" },
        h("h2", { class: "flush" }, "Modelo"),
        h("dl", { class: "facts" },
          h("dt", {}, "Clave de OpenAI"), h("dd", {}, s.analysis_configured ? badge("Configurada", "ok") : badge("Sin configurar", "warn")),
          h("dt", {}, "Modelo"), h("dd", {}, s.model),
          h("dt", {}, "Gasto"), h("dd", {}, h("div", { class: "num" }, `${usd.format(s.spent_usd)} de ${usd.format(s.budget_usd)} USD`), meter)),
        s.analysis_configured ? null : h("p", { class: "small muted" }, "Sin clave, las figuras se extraen pero no se explican.")),
      h("section", { class: "card pad" },
        h("h2", { class: "flush" }, "Documentos"),
        h("dl", { class: "facts" },
          h("dt", {}, "Tamaño máximo"), h("dd", {}, `${s.max_pdf_mb} MB por PDF`),
          h("dt", {}, "Páginas"), h("dd", {}, `hasta ${s.max_pages} por documento`),
          h("dt", {}, "Almacenamiento"), h("dd", {}, "Solo en este equipo, en la carpeta ", h("span", { class: "code" }, "data/"))),
        h("p", { class: "small muted" }, "Las explicaciones se guardan en caché: reprocesar un documento no vuelve a gastar en lo ya analizado.")),
      h("section", { class: "card pad" },
        h("h2", { class: "flush" }, "Para desarrolladores"),
        h("p", { class: "small" }, "La API documentada está en ", h("a", { href: "/docs", target: "_blank", rel: "noopener" }, "/docs"), "."),
        h("p", { class: "small muted" }, "Línea de comandos: ", h("span", { class: "code" }, "sfi process"), ", ", h("span", { class: "code" }, "sfi list"), ", ", h("span", { class: "code" }, "sfi costs"), "."))),
  );
}
