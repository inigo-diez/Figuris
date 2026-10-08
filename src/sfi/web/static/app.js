"use strict";
// Figuris: local web client. No build step, no dependencies (icons.js holds the Lucide icons).
// Everything that comes from a PDF is inserted with textContent, never as HTML.

const view = document.getElementById("view");
let pollTimer = null;
let keyHandler = null;
let searchHandler = null;
let status = null; // last /api/status

const TYPES = {
  observed: ["observado", "Se ve en la imagen de la figura."],
  author_stated: ["según los autores", "Lo dicen los autores en el pie o en el texto del artículo; lleva la cita."],
  model_inference: ["inferencia", "Deducción del modelo a partir de la evidencia; el artículo no lo afirma."],
  uncertain: ["incierto", "No se puede determinar con la figura, el pie y el texto disponibles."],
};
const ANALYSIS_BADGE = {
  ok: ["explicada", "ok"],
  invalid: ["no fiable", "bad"],
  incomplete: ["incompleta", "warn"],
  failed: ["error", "bad"],
};
const LOW_CONFIDENCE = 0.7; // detections below this are flagged for review
const usd = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
const dateFmt = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const pct = (v) => `${Math.round(v * 100)} %`;

// --- small DOM helpers -------------------------------------------------------------------

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const SVG = "http://www.w3.org/2000/svg";
function icon(name, cls = "") {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", `i ${cls}`.trim());
  for (const [tag, attrs] of ICONS[name] || []) {
    const el = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    svg.append(el);
  }
  return svg;
}

// Icon-only button with an accessible name and a tooltip.
function iconButton(name, label, onclick, extra = {}) {
  return h("button", { type: "button", class: `btn icon ${extra.cls || ""}`.trim(), "aria-label": label, "data-tip": label, onclick, ...extra.attrs }, icon(name));
}

// Replace the view; optional parts may be null and are skipped (never shown as "null").
function mount(...children) {
  view.className = "page";
  view.replaceChildren(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
}

function mountWorkspace(...children) {
  view.className = "workspace";
  view.replaceChildren(...children.flat(Infinity).filter(Boolean));
}

function badge(text, kind) {
  return h("span", { class: `badge ${kind}` }, text);
}

function alertBox(kind, ...content) {
  const name = kind === "info" ? "info" : kind === "bad" ? "circle-x" : "triangle-alert";
  return h("div", { class: `alert ${kind}`, role: kind === "bad" ? "alert" : null }, icon(name), h("div", {}, ...content));
}

function confidenceMeter(value) {
  const low = value < LOW_CONFIDENCE;
  const bar = h("div", { class: `meter${low ? " low" : ""}`, "aria-hidden": "true" }, h("div"));
  bar.firstChild.style.width = pct(value).replace(" ", "");
  const word = value >= 0.85 ? "alta" : low ? "baja" : "media";
  return h("span", { class: "meter-row" }, bar, h("span", { class: "num" }, `${pct(value)} · ${word}`));
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `Error ${response.status}`;
    try {
      const body = await response.json();
      const detail = body.detail;
      message = typeof detail === "string" ? detail : detail?.message || message;
    } catch (_) { /* not JSON */ }
    throw new Error(message);
  }
  return response.json();
}

function stopPolling() {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = null;
}

function poll(fn, ms = 1500) {
  stopPolling();
  pollTimer = setTimeout(fn, ms);
}

function setKeys(handler) {
  if (keyHandler) document.removeEventListener("keydown", keyHandler);
  keyHandler = handler;
  if (handler) document.addEventListener("keydown", handler);
}

function typing(e) {
  return e.target.closest("input, textarea, select, [contenteditable]");
}

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(`figuris.${key}`);
    localStorage.setItem(`figuris.${key}`, value);
  } catch (_) { /* storage unavailable */ }
  return null;
}

function toast(message, kind = "ok") {
  const el = h("div", { class: `toast ${kind}` }, icon(kind === "bad" ? "circle-x" : "circle-check"), message);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), 3800);
}

// Trigger a browser download of a URL served by the API.
function download(url) {
  const a = h("a", { href: url, download: "" });
  document.body.append(a);
  a.click();
  a.remove();
}

async function copyText(text, what) {
  try {
    await navigator.clipboard.writeText(text);
    toast(`${what} copiado`);
  } catch (_) {
    toast("No se pudo copiar: el navegador no lo permite", "bad");
  }
}

// Menu button: arrow keys move, Escape closes and returns focus, Tab closes.
function menuButton(label, items, { iconName = "ellipsis", text = null } = {}) {
  const id = `m${Math.random().toString(36).slice(2, 8)}`;
  const button = h("button", {
    type: "button", class: text ? "btn sm" : "btn sm icon quiet", "aria-haspopup": "menu", "aria-expanded": "false",
    "aria-controls": id, "aria-label": label, "data-tip": text ? null : label,
  }, icon(iconName), text);
  const menu = h("div", { class: "menu", role: "menu", id, hidden: true },
    items.filter(Boolean).map((item) => {
      const attrs = { role: "menuitem", tabindex: "-1" };
      return item.href
        ? h("a", { ...attrs, href: item.href, target: item.target || null, rel: item.target ? "noopener" : null, download: item.download ? "" : null, onclick: close }, icon(item.icon), item.label)
        : h("button", { ...attrs, type: "button", onclick: () => { close(); item.action(); } }, icon(item.icon), item.label);
    }));
  const entries = () => [...menu.querySelectorAll('[role="menuitem"]')];
  function open(focusLast = false) {
    menu.hidden = false;
    button.setAttribute("aria-expanded", "true");
    const list = entries();
    (focusLast ? list[list.length - 1] : list[0])?.focus();
    document.addEventListener("pointerdown", outside, true);
  }
  function close(refocus = false) {
    if (menu.hidden) return;
    menu.hidden = true;
    button.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", outside, true);
    if (refocus === true) button.focus();
  }
  function outside(e) {
    if (!wrap.contains(e.target)) close();
  }
  button.addEventListener("click", () => (menu.hidden ? open() : close()));
  button.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); open(); }
    if (e.key === "ArrowUp") { e.preventDefault(); open(true); }
  });
  menu.addEventListener("keydown", (e) => {
    const list = entries();
    const i = list.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); list[(i + 1) % list.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); list[(i - 1 + list.length) % list.length].focus(); }
    else if (e.key === "Home") { e.preventDefault(); list[0].focus(); }
    else if (e.key === "End") { e.preventDefault(); list[list.length - 1].focus(); }
    else if (e.key === "Escape") { e.preventDefault(); close(true); }
    else if (e.key === "Tab") close();
  });
  const wrap = h("span", { class: "menu-wrap" }, button, menu);
  return wrap;
}

// --- figure types --------------------------------------------------------------------------

const TYPE_NAMES = {
  chart: "gráfico", line_chart: "gráfico de líneas", scatter_plot: "gráfico de dispersión", bar_chart: "gráfico de barras",
  box_plot: "diagrama de caja", heatmap: "mapa de calor", forest_plot: "forest plot", histogram: "histograma",
  micrograph: "micrografía", photograph: "fotografía", western_blot: "western blot", map: "mapa",
  schematic: "esquema", diagram: "diagrama", flowchart: "diagrama de flujo", flow_diagram: "diagrama de flujo",
  molecular_structure: "estructura molecular", table: "tabla", network: "red", timeline: "cronología",
};
const CATEGORIES = [
  ["graficos", "Gráficos", /chart|plot|graph|grafic|histogra|heat|calor|curv|spectr|espectr|barra|line|dispers|kaplan|surviv|supervivencia|series/],
  ["imagenes", "Imágenes", /microgra|photo|fotogra|image|imagen|blot|gel|micros|map|satel|histolog|stain|tinci|tomogra|scan|radiogra/],
  ["diagramas", "Diagramas", /diagram|esquem|schem|flow|flujo|struct|estructura|network|red|pathway|ruta|timeline|model|ilustra|illustra|scheme/],
];
const plain = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

function typeName(fig) {
  const first = fig.figure_type?.[0];
  if (!first) return fig.kind === "scheme" ? "esquema" : null;
  return TYPE_NAMES[first] || first.replace(/_/g, " ");
}

function category(fig) {
  for (const type of fig.figure_type || []) {
    const t = plain(type);
    for (const [key, , re] of CATEGORIES) if (re.test(t)) return key;
  }
  return fig.kind === "scheme" ? "diagramas" : "sin";
}

function figLabel(fig) {
  return fig.label || `Región sin etiqueta · p. ${fig.page}`;
}

// --- shell: sidebar and top bar ----------------------------------------------------------

const NAV = [
  ["#/", "file-plus", "Nuevo análisis", (p) => p === "" || p === "trabajo"],
  ["#/documentos", "files", "Documentos", (p) => p === "documentos" || p === "d"],
  ["#/revision", "clipboard-check", "Revisión", (p) => p === "revision"],
  ["#/configuracion", "settings-2", "Configuración", (p) => p === "configuracion"],
];
let recentDocs = [];

function renderSidebar() {
  const section = location.hash.replace(/^#\/?/, "").split(/[/?]/)[0];
  const nav = document.getElementById("side-nav");
  nav.replaceChildren(...[
    ...NAV.map(([href, ic, label, active]) =>
      h("a", { href, "aria-current": active(section) ? "page" : null, title: label }, icon(ic), h("span", {}, label))),
    recentDocs.length ? h("div", { class: "sep", role: "presentation" }) : null,
    recentDocs.length ? h("div", { class: "label-sm" }, "Documentos recientes") : null,
    recentDocs.slice(0, 5).map((d) => h("a", { class: "recent", href: `#/d/${d.id}`, title: d.filename }, icon("file-text"), h("span", {}, d.filename))),
  ].flat(Infinity).filter(Boolean));
  const foot = document.getElementById("side-foot");
  const spent = status ? Math.min(1, status.spent_usd / Math.max(status.budget_usd, 0.0001)) : 0;
  const meter = h("div", { class: "meter" }, h("div"));
  meter.firstChild.style.width = `${Math.round(spent * 100)}%`;
  const collapsed = document.body.classList.contains("side-collapsed");
  foot.replaceChildren(...[
    h("div", { class: "who" },
      h("img", { class: "avatar", src: "/static/figuris-mark.svg", alt: "" }),
      h("div", { class: "txt" }, h("div", {}, "Espacio local"), h("div", { class: "muted" }, status ? `Modelo ${status.model}` : "…"))),
    status ? h("div", { class: "txt" },
      h("div", { class: "row small" }, h("span", { class: "muted" }, "Gasto"), h("span", { class: "spacer" }), h("span", { class: "num" }, `${usd.format(status.spent_usd)} / ${usd.format(status.budget_usd)} USD`)),
      meter) : null,
    h("button", {
      type: "button", class: "btn sm icon quiet side-toggle", "aria-label": collapsed ? "Expandir la barra lateral" : "Contraer la barra lateral",
      "data-tip": collapsed ? "Expandir" : "Contraer", "aria-pressed": String(collapsed),
      onclick: () => {
        document.body.classList.toggle("side-collapsed");
        store("side", document.body.classList.contains("side-collapsed") ? "closed" : "open");
        renderSidebar();
      },
    }, icon(collapsed ? "panel-left-open" : "panel-left-close")),
  ].filter(Boolean));
}

let crumbs = [];
function setCrumbs(...items) {
  crumbs = items;
  renderTopbar();
}

let searchPlaceholder = "Buscar";
function setSearch(placeholder, handler) {
  searchPlaceholder = placeholder;
  searchHandler = handler;
  const input = document.getElementById("search");
  if (input) {
    input.placeholder = placeholder;
    input.value = "";
    input.disabled = !handler;
  }
}

function renderTopbar() {
  const bar = document.getElementById("topbar");
  const search = h("input", {
    id: "search", type: "search", placeholder: searchPlaceholder, "aria-label": searchPlaceholder, disabled: !searchHandler,
    oninput: (e) => searchHandler && searchHandler(e.target.value.trim()),
  });
  const sys = h("div", { class: "sys", id: "sys", role: "status" });
  bar.replaceChildren(
    h("button", {
      type: "button", class: "btn icon quiet menu-btn", "aria-label": "Abrir el menú", onclick: () => toggleDrawer(true),
    }, icon("panel-left-open")),
    h("nav", { class: "crumbs", "aria-label": "Ruta" },
      h("a", { href: "#/" }, "Figuris"),
      crumbs.map(([text, href], i) => [
        h("span", { class: "slash", "aria-hidden": "true" }, "/"),
        href && i < crumbs.length - 1 ? h("a", { href }, text) : h("span", { class: "here", "aria-current": "page" }, text),
      ])),
    h("div", { class: "search", role: "search" }, icon("search"), search),
    sys,
    h("button", { type: "button", class: "btn primary", onclick: () => document.getElementById("global-file").click() },
      icon("plus"), h("span", { class: "add-txt" }, "Añadir documentos")),
  );
  renderSys();
}

let activeJobs = 0;
function renderSys() {
  const sys = document.getElementById("sys");
  if (!sys) return;
  let dot = "dot", text = "Listo";
  if (!status) { dot = "dot bad"; text = "Servidor no disponible"; }
  else if (activeJobs) { dot = "dot busy"; text = activeJobs === 1 ? "Procesando 1 documento" : `Procesando ${activeJobs} documentos`; }
  else if (!status.analysis_configured) { dot = "dot warn"; text = "Sin clave del modelo"; }
  sys.replaceChildren(h("span", { class: dot, "aria-hidden": "true" }), h("span", { class: "txt" }, text));
  sys.title = status && !status.analysis_configured
    ? "Sin clave de OpenAI: las figuras se extraen pero no se explican"
    : text;
}

async function refreshService() {
  try {
    const [s, docs, jobs] = await Promise.all([api("/api/status"), api("/api/documents"), api("/api/jobs")]);
    status = s;
    recentDocs = docs;
    activeJobs = jobs.filter((j) => j.active).length;
  } catch (_) {
    status = null;
  }
  renderSidebar();
  renderSys();
}

function toggleDrawer(open) {
  document.body.classList.toggle("side-open", open);
  document.getElementById("scrim").hidden = !open;
}

// Upload from anywhere: one file opens its processing view; several stay on the list.
async function uploadFiles(files, messageEl = null) {
  const pdfs = [...files].filter((f) => /\.pdf$/i.test(f.name) || f.type === "application/pdf");
  if (!pdfs.length) {
    toast("Solo se admiten archivos PDF", "bad");
    return [];
  }
  const jobs = [];
  for (const file of pdfs) {
    const form = new FormData();
    form.append("file", file);
    if (messageEl) messageEl.replaceChildren(h("p", { class: "small muted" }, `Subiendo ${file.name}…`));
    try {
      jobs.push(await api("/api/documents", { method: "POST", body: form }));
    } catch (error) {
      const msg = `${file.name}: ${error.message}`;
      if (messageEl) messageEl.replaceChildren(alertBox("bad", h("strong", {}, "No se pudo leer el documento. "), msg));
      else toast(msg, "bad");
    }
  }
  if (messageEl && jobs.length) messageEl.replaceChildren();
  refreshService();
  if (jobs.length === 1) location.hash = `#/trabajo/${jobs[0].id}`;
  else if (jobs.length > 1) {
    toast(`${jobs.length} documentos en cola`);
    if (location.hash !== "#/documentos") location.hash = "#/documentos";
  }
  return jobs;
}

// --- page sketch for the upload area -----------------------------------------------------

function pageSketch() {
  const s = (tag, attrs) => {
    const el = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };
  const svg = s("svg", { viewBox: "0 0 220 170", class: "sketch", "aria-hidden": "true" });
  svg.append(
    s("rect", { class: "pg", x: 46, y: 6, width: 118, height: 156, rx: 2 }),
    ...[16, 22, 28].map((y, i) => s("rect", { class: "tx", x: 56, y, width: i === 2 ? 60 : 98, height: 3 })),
    s("rect", { class: "fig", x: 56, y: 38, width: 98, height: 48 }),
    s("polyline", { points: "62,78 78,66 92,71 108,52 124,58 146,44", fill: "none", stroke: "#176B67", "stroke-width": 1.5 }),
    s("rect", { class: "box", x: 53, y: 35, width: 104, height: 54 }),
    s("rect", { class: "tag", x: 53, y: 28, width: 30, height: 7 }),
    s("rect", { class: "box b3", x: 53, y: 91, width: 104, height: 10 }),
    ...[95, 98].map((y) => s("rect", { class: "tx", x: 57, y, width: 94, height: 2 })),
    ...[108, 114, 120].map((y) => s("rect", { class: "tx", x: 56, y, width: 98, height: 3 })),
    s("rect", { class: "fig", x: 56, y: 128, width: 46, height: 26 }),
    s("rect", { class: "box b2", x: 53, y: 125, width: 52, height: 32 }),
    s("rect", { class: "tag b2", x: 53, y: 118, width: 24, height: 7 }),
    ...[130, 136, 142, 148].map((y) => s("rect", { class: "tx", x: 110, y, width: 44, height: 3 })),
  );
  return svg;
}

// --- zoomable viewer (also used by review.js) ------------------------------------------

function createViewer() {
  const img = h("img", { alt: "" });
  const stage = h("div", { class: "stage" }, img);
  const layer = h("div");
  const hint = h("div", { class: "hint" }, "Rueda o +/− para ampliar · arrastra para mover · doble clic para ampliar");
  const root = h("div", { class: "viewer" }, stage, layer, hint);
  let s = 1, tx = 0, ty = 0, fit = 1, natural = [1, 1], overlays = [], pendingFocus = null;
  // Optional editable box (review): drawn, resized or moved by dragging in "draw" mode.
  let edit = null, mode = "pan";
  let onTap = null; // called with a normalized page point on a click without drag

  function place(el, [x0, y0, x1, y1]) {
    el.style.left = `${tx + x0 * natural[0] * s}px`;
    el.style.top = `${ty + y0 * natural[1] * s}px`;
    el.style.width = `${(x1 - x0) * natural[0] * s}px`;
    el.style.height = `${(y1 - y0) * natural[1] * s}px`;
  }
  function apply() {
    stage.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`;
    for (const o of overlays) place(o.el, o.box);
    if (edit) {
      edit.el.hidden = !edit.box;
      if (edit.box) place(edit.el, edit.box);
    }
  }
  // Pointer position as normalized page coordinates, clamped to the page.
  function toPage(e) {
    const r = root.getBoundingClientRect();
    const clamp = (v) => Math.min(Math.max(v, 0), 1);
    return [clamp((e.clientX - r.left - tx) / (natural[0] * s)), clamp((e.clientY - r.top - ty) / (natural[1] * s))];
  }
  // Which edges of the editable box are under the pointer ("" = none, "move" = inside).
  function hit(e) {
    if (!edit?.box) return "";
    const r = root.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top, tol = 7;
    const [x0, y0, x1, y1] = [tx + edit.box[0] * natural[0] * s, ty + edit.box[1] * natural[1] * s, tx + edit.box[2] * natural[0] * s, ty + edit.box[3] * natural[1] * s];
    if (px < x0 - tol || px > x1 + tol || py < y0 - tol || py > y1 + tol) return "";
    const edges = (Math.abs(py - y0) <= tol ? "n" : Math.abs(py - y1) <= tol ? "s" : "") + (Math.abs(px - x0) <= tol ? "w" : Math.abs(px - x1) <= tol ? "e" : "");
    return edges || "move";
  }
  function reset() {
    const w = root.clientWidth, hgt = root.clientHeight;
    if (!w || !hgt) return;
    fit = Math.min((w - 24) / natural[0], (hgt - 24) / natural[1]);
    s = fit;
    tx = (w - natural[0] * s) / 2;
    ty = (hgt - natural[1] * s) / 2;
    apply();
  }
  function fitWidth() {
    const w = root.clientWidth;
    s = (w - 32) / natural[0];
    tx = 16;
    ty = 16;
    apply();
  }
  function zoomAt(px, py, factor) {
    const next = Math.min(Math.max(s * factor, fit * 0.5), Math.max(fit * 10, 3));
    tx = px - ((px - tx) * next) / s;
    ty = py - ((py - ty) * next) / s;
    s = next;
    apply();
  }
  function focus(box) {
    const w = root.clientWidth, hgt = root.clientHeight;
    const [x0, y0, x1, y1] = box;
    const bw = (x1 - x0) * natural[0], bh = (y1 - y0) * natural[1];
    s = Math.min(Math.max(Math.min((w * 0.85) / bw, (hgt * 0.8) / bh), fit), fit * 4);
    tx = w / 2 - (x0 * natural[0] + bw / 2) * s;
    ty = hgt / 2 - (y0 * natural[1] + bh / 2) * s;
    apply();
  }
  img.addEventListener("load", () => {
    natural = [img.naturalWidth, img.naturalHeight];
    img.width = natural[0];
    img.height = natural[1];
    reset();
    if (pendingFocus) { focus(pendingFocus); pendingFocus = null; }
  });
  root.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = root.getBoundingClientRect();
    zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.2 : 1 / 1.2);
  }, { passive: false });
  root.addEventListener("dblclick", (e) => {
    if (e.target.closest(".controls")) return;
    const r = root.getBoundingClientRect();
    zoomAt(e.clientX - r.left, e.clientY - r.top, 2);
  });
  let drag = null;
  const dismissHint = () => hint.classList.add("gone");
  root.addEventListener("wheel", dismissHint, { passive: true });
  root.addEventListener("pointerdown", (e) => {
    dismissHint();
    if (e.target.closest(".controls")) return;
    if (edit && mode === "draw" && e.button === 0) {
      const edges = hit(e);
      drag = { edit: edges || "new", start: toPage(e), box: edit.box ? [...edit.box] : null };
    } else {
      drag = { x: e.clientX, y: e.clientY, tx, ty, moved: false };
      root.classList.add("dragging");
    }
    root.setPointerCapture(e.pointerId);
  });
  const CURSORS = { n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize", nw: "nwse-resize", se: "nwse-resize", ne: "nesw-resize", sw: "nesw-resize", move: "move" };
  root.addEventListener("pointermove", (e) => {
    if (!drag) {
      if (edit && mode === "draw") root.style.cursor = CURSORS[hit(e)] || "crosshair";
      return;
    }
    if (!drag.edit) {
      if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 4) drag.moved = true;
      tx = drag.tx + e.clientX - drag.x;
      ty = drag.ty + e.clientY - drag.y;
      apply();
      return;
    }
    const [px, py] = toPage(e);
    const [sx, sy] = drag.start;
    if (drag.edit === "new") {
      edit.box = [Math.min(sx, px), Math.min(sy, py), Math.max(sx, px), Math.max(sy, py)];
    } else if (drag.edit === "move") {
      const [x0, y0, x1, y1] = drag.box;
      const dx = Math.min(Math.max(px - sx, -x0), 1 - x1), dy = Math.min(Math.max(py - sy, -y0), 1 - y1);
      edit.box = [x0 + dx, y0 + dy, x1 + dx, y1 + dy];
    } else {
      let [x0, y0, x1, y1] = drag.box;
      if (drag.edit.includes("n")) y0 = py;
      if (drag.edit.includes("s")) y1 = py;
      if (drag.edit.includes("w")) x0 = px;
      if (drag.edit.includes("e")) x1 = px;
      edit.box = [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];
    }
    apply();
  });
  const end = (e) => {
    if (drag?.edit) {
      const b = edit.box;
      if (!b || b[2] - b[0] < 0.01 || b[3] - b[1] < 0.01) edit.box = drag.box; // a click, not a box
      apply();
      if (edit.box !== drag.box) edit.onChange(edit.box && edit.box.map((v) => Math.round(v * 10000) / 10000));
    } else if (drag && !drag.moved && onTap && e.type === "pointerup") {
      onTap(toPage(e));
    }
    drag = null;
    root.classList.remove("dragging");
  };
  root.addEventListener("pointerup", end);
  root.addEventListener("pointercancel", end);
  const center = (factor) => zoomAt(root.clientWidth / 2, root.clientHeight / 2, factor);
  root.append(h("div", { class: "controls" },
    iconButton("zoom-in", "Ampliar", () => center(1.4), { cls: "tip-left" }),
    iconButton("zoom-out", "Reducir", () => center(1 / 1.4), { cls: "tip-left" }),
    iconButton("scan", "Ajustar a la página", reset, { cls: "tip-left" }),
    iconButton("maximize-2", "Ajustar al ancho", fitWidth, { cls: "tip-left" }),
  ));
  new ResizeObserver(() => { if (img.complete && img.naturalWidth) reset(); }).observe(root);

  return {
    el: root,
    // Make one box editable; onChange(box) is called after each drag.
    setEditable(box, onChange, tag = "tu caja") {
      if (!edit) {
        edit = { el: h("div", { class: "ov edit" }, h("span", { class: "tag" })), box: null, onChange };
        root.insertBefore(edit.el, hint);
      }
      edit.el.firstChild.textContent = tag;
      edit.box = box;
      edit.onChange = onChange;
      apply();
    },
    // Replace the static boxes without moving or zooming the view.
    setOverlays(boxes) {
      overlays = boxes.map((b) => ({
        box: b.box,
        el: h("div", { class: `ov ${b.cls}`, id: b.id || null }, b.label ? h("span", { class: "tag" }, b.label) : null),
      }));
      layer.replaceChildren(...overlays.map((o) => o.el));
      apply();
    },
    setMode(next) {
      mode = next;
      root.classList.toggle("drawing", mode === "draw");
      root.style.cursor = "";
      hint.textContent = mode === "draw"
        ? "Arrastra para dibujar la caja o para ajustar sus bordes · rueda para ampliar"
        : "Rueda o +/− para ampliar · arrastra para mover · doble clic para ampliar";
    },
    onTap(fn) {
      onTap = fn;
      root.classList.toggle("selectable", Boolean(fn));
      hint.textContent = "Pulsa una región para ver sus detalles · rueda para ampliar · arrastra para mover";
    },
    focus,
    reset,
    show(src, alt, boxes = [], focusBox = null) {
      this.setOverlays(boxes);
      img.alt = alt;
      pendingFocus = focusBox;
      if (img.getAttribute("src") === src && img.complete && img.naturalWidth) {
        if (focusBox) focus(focusBox);
        pendingFocus = null;
      } else {
        img.src = src;
      }
    },
  };
}

// --- router ------------------------------------------------------------------------------

// Extra screens (review.js) register here: name -> render(parts).
const ROUTES = {};

function route() {
  stopPolling();
  setKeys(null);
  toggleDrawer(false);
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const params = Object.fromEntries(new URLSearchParams(query || ""));
  setSearch("Buscar", null);
  if (ROUTES[parts[0]]) {
    setCrumbs(["Revisión", "#/revision"], ...(parts.length > 1 ? [[parts[1] === "cajas" ? "Cajas de figura" : parts[1] === "paneles" ? "Paneles" : "Explicaciones"]] : []));
    ROUTES[parts[0]](parts.slice(1));
  } else if (parts[0] === "d" && parts[1] && parts[2] === "f" && parts[3]) renderFigure(parts[1], parts[3]);
  else if (parts[0] === "d" && parts[1]) renderDocument(parts[1], params);
  else if (parts[0] === "trabajo" && parts[1]) renderJob(parts[1]);
  else if (parts[0] === "documentos") renderDocuments();
  else if (parts[0] === "configuracion") renderSettings();
  else renderHome();
  renderSidebar();
  view.scrollTo(0, 0);
}

window.addEventListener("hashchange", route);
document.addEventListener("DOMContentLoaded", () => {
  if (store("side") === "closed") document.body.classList.add("side-collapsed");
  document.getElementById("scrim").addEventListener("click", () => toggleDrawer(false));
  document.getElementById("skip").addEventListener("click", () => view.focus());
  const file = document.getElementById("global-file");
  file.addEventListener("change", () => { uploadFiles(file.files); file.value = ""; });
  renderTopbar();
  refreshService();
  route();
});
