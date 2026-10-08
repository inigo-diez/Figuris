"use strict";
// Review screens (Stage 5): check SFI-48 reference boxes and score explanations with the
// rubric. Uses the helpers of app.js. The box review never shows what the system extracted
// (annotation protocol, step 4). Text from PDFs and JATS is inserted with textContent only.

const enc = encodeURIComponent;
const REASONS = {
  low_score: ["coincidencia baja", "La imagen que publica PMC se localizó en el PDF con poca coincidencia. Comprueba la propuesta y corrígela si hace falta."],
  not_located: ["no localizada", "No se localizó en el PDF la imagen publicada por PMC. Busca la figura en las páginas y dibuja la caja."],
  scanned: ["escaneado", "Artículo escaneado: el JATS no enumera sus figuras y la etiqueta sale del texto OCR. Busca la figura en las páginas; si no existe, márcala como «No está en el PDF»."],
  no_jats: ["sin JATS", "La figura no aparece en el JATS. Búscala en las páginas."],
  added: ["añadida", "Figura que la referencia no listaba, añadida durante la revisión."],
  auto: ["automática", "Caja localizada automáticamente con buena coincidencia. Revisarla es opcional (por ejemplo, para la doble anotación)."],
};
const DECISIONS = { box: ["caja", "ok"], absent: ["no está", "neutral"], unclear: ["dudosa", "warn"] };
const decimal = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const score = (value) => (value === null || value === undefined ? "—" : decimal.format(value));

function getAnnotator() {
  try { return localStorage.getItem("sfi.annotator") || ""; } catch (_) { return ""; }
}

function setAnnotator(name) {
  try { localStorage.setItem("sfi.annotator", name); } catch (_) { /* storage unavailable */ }
}

function requireAnnotator() {
  const who = getAnnotator();
  if (!who) location.hash = "#/revision";
  return who;
}

function annotatorForm(onDone) {
  const input = h("input", { class: "input", type: "text", value: getAnnotator(), maxlength: "40", placeholder: "Tu nombre o iniciales", "aria-label": "Nombre de revisor", required: true });
  return h("form", {
    class: "row",
    onsubmit: (e) => {
      e.preventDefault();
      const name = input.value.trim();
      if (!name) return;
      setAnnotator(name);
      onDone(name);
    },
  }, input, h("button", { class: "btn primary", type: "submit" }, "Guardar"));
}

function progressBar(done, total) {
  const bar = h("div", { class: "progress" }, h("div"));
  bar.firstChild.style.width = `${total ? Math.round((100 * done) / total) : 0}%`;
  return bar;
}

function backLink(href, text) {
  return h("p", { class: "small" }, h("a", { href }, text));
}

async function jsonPut(path, body) {
  return api(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// --- hub ---------------------------------------------------------------------------------

async function renderReviewHub() {
  document.title = "Revisión · Figuris";
  const who = getAnnotator();
  const intro = [
    h("h1", {}, "Revisión humana"),
    h("p", { class: "muted" }, "Comprueba la referencia de SFI-48 y puntúa las explicaciones con la rúbrica del plan de evaluación. Cada anotación se guarda con tu nombre en data/sfi48/reviews/ y la usan los scripts de evaluación."),
  ];
  if (!who) {
    mount(intro, h("div", { class: "card pad" },
      h("p", {}, "Escribe tu nombre de revisor. Se guarda con cada anotación para poder medir después el acuerdo entre revisores."),
      annotatorForm(() => renderReviewHub())));
    return;
  }
  let boxes, explanations, panelData;
  try {
    [boxes, explanations, panelData] = await Promise.all([
      api(`/api/review/boxes?annotator=${enc(who)}`),
      api(`/api/review/explanations?annotator=${enc(who)}`),
      // A server started before panel review existed answers 404: say how to enable it.
      api(`/api/review/panels?annotator=${enc(who)}`).catch(() => ({
        available: false,
        message: "Reinicia la aplicación (sfi serve) para activar la revisión de paneles.",
      })),
    ]);
  } catch (error) {
    mount(intro, h("div", { class: "alert bad" }, error.message));
    return;
  }
  const change = h("button", { class: "btn", type: "button", onclick: () => { setAnnotator(""); renderReviewHub(); } }, "Cambiar");

  let boxCard;
  if (!boxes.available) {
    boxCard = h("div", { class: "card pad" }, h("h2", { class: "flush" }, "Cajas de referencia"), h("div", { class: "alert" }, boxes.message));
  } else {
    const pending = boxes.items.filter((i) => i.needs_review);
    const done = pending.filter((i) => i.mine).length;
    const next = pending.find((i) => !i.mine);
    boxCard = h("div", { class: "card pad" },
      h("h2", { class: "flush" }, "Cajas de referencia"),
      h("p", { class: "muted small" }, "Figuras cuya posición en el PDF no se pudo fijar automáticamente: localízalas y dibuja su caja. No se muestra lo que detecta el sistema."),
      h("div", {}, h("strong", {}, `${done} de ${pending.length}`), " figuras dudosas revisadas"),
      progressBar(done, pending.length),
      h("div", { class: "row" },
        next
          ? h("a", { class: "btn primary", href: `#/revision/cajas/${enc(next.pmcid)}/${enc(next.key)}` }, done ? "Continuar" : "Empezar")
          : h("span", { class: "badge ok" }, "todas revisadas"),
        h("a", { class: "btn", href: "#/revision/cajas" }, "Ver la lista")),
    );
  }

  const items = explanations.items;
  const complete = items.filter((i) => i.scored === i.claims).length;
  const nextExpl = items.find((i) => i.scored < i.claims);
  const explCard = h("div", { class: "card pad" },
    h("h2", { class: "flush" }, "Explicaciones"),
    h("p", { class: "muted small" }, "Puntúa cada afirmación de 0 a 2 en seis criterios y marca los errores críticos. Las explicaciones salen de los documentos procesados en esta aplicación."),
    items.length
      ? [
        h("div", {}, h("strong", {}, `${complete} de ${items.length}`), " explicaciones puntuadas"),
        progressBar(complete, items.length),
        h("div", { class: "row" },
          nextExpl
            ? h("a", { class: "btn primary", href: `#/revision/explicaciones/${nextExpl.document_id}/${nextExpl.figure_id}` }, complete ? "Continuar" : "Empezar")
            : h("span", { class: "badge ok" }, "todas puntuadas"),
          h("a", { class: "btn", href: "#/revision/explicaciones" }, "Ver la lista")),
      ]
      : h("p", { class: "muted" }, "Todavía no hay explicaciones. Procesa algún artículo con la clave de OpenAI configurada."),
  );

  mount(
    intro,
    h("div", { class: "row small muted" }, `Revisor: `, h("strong", {}, who), change),
    h("div", { class: "review-cards" }, boxCard, panelCard(panelData), explCard),
  );
}

function panelCard(data) {
  const title = h("h2", { class: "flush" }, "Paneles");
  if (!data.available) return h("div", { class: "card pad" }, title, h("div", { class: "alert" }, data.message));
  // dev and validation first: they are the ones used to measure while developing.
  const queue = panelQueue(data.items);
  const firstSplits = queue.filter((i) => i.split !== "test");
  const done = firstSplits.filter((i) => i.mine).length;
  const next = queue.find((i) => !i.mine);
  return h("div", { class: "card pad" },
    title,
    h("p", { class: "muted small" }, "En las figuras con varios paneles (a, b, c…), dibuja la caja de cada panel. Sirve para medir la separación de paneles. No se muestra lo que propone el sistema."),
    h("div", {}, h("strong", {}, `${done} de ${firstSplits.length}`), " figuras de dev y validation"),
    progressBar(done, firstSplits.length),
    h("div", { class: "row" },
      next
        ? h("a", { class: "btn primary", href: `#/revision/paneles/${enc(next.pmcid)}/${enc(next.key)}` }, done ? "Continuar" : "Empezar")
        : h("span", { class: "badge ok" }, "todas revisadas"),
      h("a", { class: "btn", href: "#/revision/paneles" }, "Ver la lista")),
  );
}

function panelQueue(items) {
  const rank = { dev: 0, validation: 1, test: 2 };
  return [...items].sort((a, b) => (rank[a.split] ?? 3) - (rank[b.split] ?? 3));
}

// --- reference boxes: list ---------------------------------------------------------------

async function renderBoxList() {
  const who = requireAnnotator();
  if (!who) return;
  document.title = "Cajas de referencia · Revisión";
  let data;
  try {
    data = await api(`/api/review/boxes?annotator=${enc(who)}`);
  } catch (error) {
    mount(backLink("#/revision", "← Revisión"), h("div", { class: "alert bad" }, error.message));
    return;
  }
  if (!data.available) {
    mount(backLink("#/revision", "← Revisión"), h("div", { class: "alert" }, data.message));
    return;
  }
  let scope = "pending";
  let split = "";
  try { scope = localStorage.getItem("sfi.review.scope") || scope; } catch (_) { /* ignore */ }
  const list = h("div", { class: "docs" });
  const scopeSelect = h("select", { class: "input", "aria-label": "Qué figuras mostrar" },
    h("option", { value: "pending" }, "Solo las dudosas"), h("option", { value: "all" }, "Todas las figuras"));
  const splitSelect = h("select", { class: "input", "aria-label": "Split" },
    h("option", { value: "" }, "Todos los splits"), ["dev", "validation", "test"].map((s) => h("option", { value: s }, s)));
  scopeSelect.value = scope;

  function draw() {
    const items = data.items.filter((i) => (scope === "all" || i.needs_review) && (!split || i.split === split));
    const groups = new Map();
    for (const item of items) {
      if (!groups.has(item.pmcid)) groups.set(item.pmcid, []);
      groups.get(item.pmcid).push(item);
    }
    const cards = [...groups.entries()].map(([pmcid, figures]) =>
      h("div", { class: "card pad" },
        h("div", { class: "row" }, h("strong", {}, pmcid), badge(figures[0].split, "neutral"),
          h("span", { class: "small muted" }, (figures[0].stratum || "").replace("/", " · "))),
        h("table", { class: "review-table" }, h("tbody", {}, figures.map((f) => h("tr", {},
          h("td", {}, h("a", { href: `#/revision/cajas/${enc(f.pmcid)}/${enc(f.key)}` }, f.label || f.key)),
          h("td", { class: "small muted" }, REASONS[f.reason][0], f.match_score !== null && f.reason !== "auto" ? ` (${score(f.match_score)})` : ""),
          h("td", {}, f.mine ? badge(...DECISIONS[f.mine]) : badge("sin revisar", "neutral")),
          h("td", { class: "small muted" }, f.reviewers > 1 ? `${f.reviewers} revisores` : ""),
        )))),
      ));
    list.replaceChildren(...(cards.length ? cards : [h("div", { class: "empty card" }, "No hay figuras con este filtro.")]));
  }
  scopeSelect.addEventListener("change", () => {
    scope = scopeSelect.value;
    try { localStorage.setItem("sfi.review.scope", scope); } catch (_) { /* ignore */ }
    draw();
  });
  splitSelect.addEventListener("change", () => { split = splitSelect.value; draw(); });
  const pending = data.items.filter((i) => i.needs_review);
  mount(
    backLink("#/revision", "← Revisión"),
    h("h1", {}, "Cajas de referencia"),
    h("p", { class: "muted small" }, `Referencia ${data.reference_version} · ${pending.filter((i) => i.mine).length} de ${pending.length} dudosas revisadas por ${who}`),
    h("div", { class: "row" }, scopeSelect, splitSelect),
    list,
  );
  draw();
}

// --- reference boxes: one figure ---------------------------------------------------------

async function renderBoxReview(pmcid, key) {
  const who = requireAnnotator();
  if (!who) return;
  let fig, list;
  try {
    [fig, list] = await Promise.all([
      api(`/api/review/box?pmcid=${enc(pmcid)}&figure=${enc(key)}&annotator=${enc(who)}`),
      api(`/api/review/boxes?annotator=${enc(who)}`),
    ]);
  } catch (error) {
    mount(backLink("#/revision/cajas", "← Lista"), h("div", { class: "alert bad" }, error.message));
    return;
  }
  document.title = `${fig.label || key} · ${pmcid} · Figuris`;
  const queue = list.items.filter((i) => i.needs_review);
  const index = queue.findIndex((i) => i.pmcid === pmcid && i.key === key);
  const href = (item) => `#/revision/cajas/${enc(item.pmcid)}/${enc(item.key)}`;
  const nextPending = () => {
    for (let k = 1; k <= queue.length; k++) {
      const item = queue[(Math.max(index, 0) + k) % queue.length];
      if (!item.mine && !(item.pmcid === pmcid && item.key === key)) return item;
    }
    return null;
  };

  const review = fig.review;
  let box = review?.decision === "box" ? review.bbox : null;
  let boxPage = review?.decision === "box" ? review.page : null;
  let proposalUsed = false;
  const captionPage = fig.label_pages.find((p) => p.caption_like) || fig.label_pages[0];
  let page = boxPage || fig.proposal?.page || captionPage?.page || 1;

  const viewer = createViewer();
  let showProposalDefault = true;
  try { showProposalDefault = localStorage.getItem("sfi.review.proposal") !== "hidden"; } catch (_) { /* ignore */ }
  const showProposal = h("input", { type: "checkbox", checked: showProposalDefault });
  const prevPage = h("button", { class: "btn icon", type: "button", "aria-label": "Página anterior", title: "Página anterior (←)", onclick: () => showPage(page - 1) }, "‹");
  const nextPage = h("button", { class: "btn icon", type: "button", "aria-label": "Página siguiente", title: "Página siguiente (→)", onclick: () => showPage(page + 1) }, "›");
  const pageLabel = h("span", { class: "muted small" });
  const drawBtn = h("button", { type: "button", title: "Arrastra para dibujar la caja o para mover y ajustar sus bordes (D)", onclick: () => setMode("draw") }, "✎ Dibujar");
  const panBtn = h("button", { type: "button", title: "Arrastra para desplazar la página (M)", onclick: () => setMode("pan") }, "✋ Mover");
  const state = h("div", { class: "small" });
  const message = h("div", { "aria-live": "polite" });
  const note = h("textarea", { class: "input", rows: "2", maxlength: "2000", placeholder: "Nota (obligatoria si es dudosa)" });
  note.value = review?.note || "";
  const saveBtn = h("button", { class: "btn primary", type: "button", title: "Guardar la caja (Intro)", onclick: () => save("box") }, "Guardar caja");

  function setMode(mode) {
    viewer.setMode(mode);
    drawBtn.setAttribute("aria-pressed", String(mode === "draw"));
    panBtn.setAttribute("aria-pressed", String(mode === "pan"));
  }
  function showPage(number) {
    page = Math.min(Math.max(number, 1), fig.pages);
    const overlays = [];
    if (fig.proposal && showProposal.checked && fig.proposal.page === page) {
      overlays.push({ box: fig.proposal.bbox, cls: "prop", label: "propuesta" });
    }
    viewer.show(`/api/review/articles/${enc(pmcid)}/pages/${page}`, `Página ${page} de ${pmcid}`, overlays);
    viewer.setEditable(boxPage === page ? box : null, (b) => {
      box = b;
      boxPage = b ? page : null;
      describe();
    });
    pageLabel.textContent = `Página ${page} de ${fig.pages}`;
    prevPage.disabled = page <= 1;
    nextPage.disabled = page >= fig.pages;
    describe();
  }
  function describe() {
    saveBtn.disabled = !box;
    if (!box) {
      state.replaceChildren("Todavía no hay caja: arrastra sobre la página para dibujarla.");
    } else if (boxPage !== page) {
      state.replaceChildren(`Tu caja está en la página ${boxPage}. `, h("a", { href: "#", onclick: (e) => { e.preventDefault(); showPage(boxPage); } }, "Ir a esa página"));
    } else {
      state.replaceChildren(`Caja dibujada en la página ${boxPage}. Ajusta sus bordes arrastrándolos o guárdala.`);
    }
  }
  async function save(decision) {
    if (decision === "box" && !box) return;
    if (decision === "unclear" && !note.value.trim()) {
      message.replaceChildren(h("div", { class: "alert" }, "Explica en la nota por qué es dudosa."));
      note.focus();
      return;
    }
    try {
      await jsonPut("/api/review/box", {
        pmcid,
        figure: key,
        annotator: who,
        decision,
        page: decision === "box" ? boxPage : null,
        bbox: decision === "box" ? box : null,
        note: note.value,
        label: fig.reason === "added" ? fig.label : null,
        proposal_shown: Boolean(fig.proposal && showProposal.checked) || proposalUsed,
      });
    } catch (error) {
      message.replaceChildren(h("div", { class: "alert bad" }, error.message));
      return;
    }
    const next = nextPending();
    location.hash = next ? href(next) : "#/revision/cajas";
  }

  showProposal.addEventListener("change", () => {
    try { localStorage.setItem("sfi.review.proposal", showProposal.checked ? "shown" : "hidden"); } catch (_) { /* ignore */ }
    showPage(page);
  });
  const [reasonShort, reasonText] = REASONS[fig.reason] || REASONS.auto;
  const pagesWithLabel = fig.label_pages.length
    ? h("div", { class: "row small" }, fig.label_pages.map((p) =>
      h("button", { class: "src", type: "button", onclick: () => showPage(p.page), title: p.caption_like ? "La etiqueta empieza una línea: probablemente el pie" : "Mención en el texto" },
        `p. ${p.page}${p.caption_like ? " · pie" : ""}`)))
    : h("p", { class: "small muted" }, "No aparece en el texto del PDF.");

  const proposalBlock = fig.proposal
    ? [h("h3", {}, "Propuesta automática"),
      h("p", { class: "small" }, `Página ${fig.proposal.page} · coincidencia ${score(fig.proposal.score)}. Es donde se localizó la imagen de PMC, no la salida del sistema.`),
      h("div", { class: "row small" },
        h("label", { class: "row" }, showProposal, "Mostrarla"),
        h("button", {
          class: "btn", type: "button",
          onclick: () => {
            box = [...fig.proposal.bbox];
            boxPage = fig.proposal.page;
            proposalUsed = true;
            showPage(boxPage);
          },
        }, "Partir de la propuesta"))]
    : null;
  const previous = review
    ? h("p", { class: "small muted" }, `Revisada el ${new Date(review.reviewed_at).toLocaleString("es-ES")}: `, badge(...DECISIONS[review.decision]), " ",
      h("a", {
        href: "#",
        onclick: async (e) => {
          e.preventDefault();
          try { await api(`/api/review/box?pmcid=${enc(pmcid)}&figure=${enc(key)}&annotator=${enc(who)}`, { method: "DELETE" }); } catch (error) { alert(error.message); }
          renderBoxReview(pmcid, key);
        },
      }, "borrar mi revisión"))
    : null;

  const side = h("section", { class: "card expl review-side", "aria-label": "Figura que revisar" },
    h("p", { class: "small muted" }, reasonText),
    proposalBlock,
    h("h3", {}, "Decisión"),
    h("p", { class: "small" }, "Rodea solo la figura: todos sus paneles, ejes, leyendas y rótulos, sin el pie ni el texto. Si ocupa dos páginas, marca la principal y explícalo en la nota."),
    state,
    note,
    h("div", { class: "row" },
      saveBtn,
      h("button", { class: "btn", type: "button", onclick: () => save("absent"), title: "La figura no existe en este PDF (o la etiqueta es errónea)" }, "No está en el PDF"),
      h("button", { class: "btn", type: "button", onclick: () => save("unclear"), title: "No se puede decidir; explica por qué en la nota" }, "Dudosa"),
    ),
    message,
    previous,
    h("h3", {}, `Páginas donde aparece «${fig.label || key}»`),
    pagesWithLabel,
    fig.has_image
      ? [h("h3", {}, "Imagen publicada en PMC (lo que buscas)"),
        h("img", { class: "published", src: `/api/review/articles/${enc(pmcid)}/figure-image?figure=${enc(key)}`, alt: `Imagen publicada de ${fig.label || key}` })]
      : null,
    fig.caption ? [h("h3", {}, "Pie según el JATS"), h("div", { class: "caption-text small" }, fig.caption)] : null,
    h("p", { class: "small muted" },
      h("a", {
        href: "#",
        onclick: (e) => {
          e.preventDefault();
          const label = (prompt("Etiqueta de la figura que falta (por ejemplo, Figure 5):") || "").trim();
          if (label) location.hash = `#/revision/cajas/${enc(pmcid)}/${enc(`label:${label}`)}`;
        },
      }, "¿Falta alguna figura en este artículo? Añádela")),
  );

  const position = index >= 0 ? `${index + 1} de ${queue.length}` : "";
  mount(
    backLink("#/revision/cajas", "← Lista de cajas"),
    h("div", { class: "figbar" },
      h("h1", {}, fig.label || key),
      h("span", { class: "muted" }, pmcid),
      badge(fig.split, "neutral"),
      badge(reasonShort, fig.reason === "auto" ? "neutral" : "warn"),
      h("div", { class: "nav" },
        position ? h("span", { class: "kbd" }, position) : null,
        h("button", { class: "btn", type: "button", disabled: index <= 0, onclick: () => { location.hash = href(queue[index - 1]); } }, "‹ Anterior"),
        h("button", { class: "btn", type: "button", disabled: index < 0 || index >= queue.length - 1, onclick: () => { location.hash = href(queue[index + 1]); } }, "Siguiente ›"),
      ),
    ),
    h("div", { class: "figure-layout" },
      h("div", { class: "left" },
        h("div", { class: "row" },
          h("div", { class: "seg", role: "group", "aria-label": "Modo" }, drawBtn, panBtn),
          h("span", { class: "spacer" }),
          prevPage, pageLabel, nextPage),
        viewer.el,
        h("p", { class: "small muted" }, "Rueda para ampliar · ← → cambian de página · D dibujar · M mover · Intro guarda la caja"),
      ),
      side,
    ),
  );
  setMode("draw");
  showPage(page);
  setKeys((e) => {
    if (e.target.closest("input, textarea, select")) return;
    if (e.key === "ArrowLeft") showPage(page - 1);
    else if (e.key === "ArrowRight") showPage(page + 1);
    else if (e.key === "d" || e.key === "D") setMode("draw");
    else if (e.key === "m" || e.key === "M") setMode("pan");
    else if (e.key === "Enter" && box) save("box");
    else return;
    e.preventDefault();
  });
}

// --- explanations: list ------------------------------------------------------------------

async function renderExplanationList() {
  const who = requireAnnotator();
  if (!who) return;
  document.title = "Explicaciones · Revisión";
  let data;
  try {
    data = await api(`/api/review/explanations?annotator=${enc(who)}`);
  } catch (error) {
    mount(backLink("#/revision", "← Revisión"), h("div", { class: "alert bad" }, error.message));
    return;
  }
  const list = h("div", { class: "docs" });
  const splitSelect = h("select", { class: "input", "aria-label": "Split" },
    h("option", { value: "" }, "Todos los documentos"),
    ["dev", "validation", "test"].map((s) => h("option", { value: s }, `SFI-48 ${s}`)),
    h("option", { value: "none" }, "Fuera de SFI-48"));
  function draw() {
    const split = splitSelect.value;
    const items = data.items.filter((i) => !split || (split === "none" ? !i.split : i.split === split));
    const groups = new Map();
    for (const item of items) {
      if (!groups.has(item.document_id)) groups.set(item.document_id, []);
      groups.get(item.document_id).push(item);
    }
    const cards = [...groups.values()].map((figures) =>
      h("div", { class: "card pad" },
        h("div", { class: "row" }, h("strong", {}, figures[0].filename),
          figures[0].split ? badge(figures[0].split, "neutral") : null),
        h("table", { class: "review-table" }, h("tbody", {}, figures.map((f) => h("tr", {},
          h("td", {}, h("a", { href: `#/revision/explicaciones/${f.document_id}/${f.figure_id}` }, f.label || "Región sin etiqueta")),
          h("td", {}, badge(...(ANALYSIS_BADGE[f.status] || [f.status, "neutral"]))),
          h("td", { class: "small" }, f.scored === f.claims ? badge("puntuada", "ok") : `${f.scored} de ${f.claims} afirmaciones`),
          h("td", { class: "small" }, f.critical ? h("span", { class: "bad-text" }, `${f.critical} error${f.critical > 1 ? "es" : ""} crítico${f.critical > 1 ? "s" : ""}`) : ""),
        )))),
      ));
    list.replaceChildren(...(cards.length ? cards : [h("div", { class: "empty card" }, "No hay explicaciones con este filtro.")]));
  }
  splitSelect.addEventListener("change", draw);
  mount(
    backLink("#/revision", "← Revisión"),
    h("h1", {}, "Explicaciones"),
    h("p", { class: "muted small" }, `${data.items.filter((i) => i.scored === i.claims).length} de ${data.items.length} puntuadas por ${who}`),
    h("div", { class: "row" }, splitSelect),
    list,
  );
  draw();
}

// --- explanations: score one -------------------------------------------------------------

async function renderExplanationReview(docId, figId) {
  const who = requireAnnotator();
  if (!who) return;
  let fig, rev, list;
  try {
    [fig, rev, list] = await Promise.all([
      api(`/api/documents/${docId}/figures/${figId}`),
      api(`/api/review/explanations/${docId}/${figId}?annotator=${enc(who)}`),
      api(`/api/review/explanations?annotator=${enc(who)}`),
    ]);
  } catch (error) {
    mount(backLink("#/revision/explicaciones", "← Lista"), h("div", { class: "alert bad" }, error.message));
    return;
  }
  document.title = `Puntuar ${fig.label || "figura"} · ${fig.filename}`;
  const analysis = fig.analysis;
  const explanation = analysis.explanation;
  const criteria = rev.rubric.criteria;
  const spans = new Map(analysis.spans.map((s) => [`${s.claim_id}:${s.evidence_index}`, s]));
  const draft = {};
  for (const claim of explanation.claims) draft[claim.id] = { scores: {}, critical: null, note: "" };
  for (const claim of rev.review?.claims || []) {
    if (draft[claim.id]) draft[claim.id] = { scores: { ...claim.scores }, critical: claim.critical, note: claim.note || "" };
  }
  const comment = h("textarea", { class: "input", rows: "2", maxlength: "4000", placeholder: "Comentario general sobre la explicación (opcional)" });
  comment.value = rev.review?.comment || "";

  const saveState = h("span", { class: "small muted", "aria-live": "polite" }, rev.review ? "Guardado" : "");
  const progress = h("strong");
  let timer = null;
  function scoredCount() {
    return explanation.claims.filter((c) => criteria.every((k) => draft[c.id].scores[k.id] !== undefined)).length;
  }
  function schedule() {
    progress.textContent = `${scoredCount()} de ${explanation.claims.length}`;
    saveState.textContent = "Guardando…";
    saveState.className = "small muted";
    clearTimeout(timer);
    timer = setTimeout(save, 500);
  }
  async function save() {
    try {
      await jsonPut(`/api/review/explanations/${docId}/${figId}`, { annotator: who, analysis: rev.analysis, claims: draft, comment: comment.value });
      saveState.textContent = "Guardado";
    } catch (error) {
      saveState.textContent = `No se pudo guardar: ${error.message}`;
      saveState.className = "small bad-text";
    }
  }
  comment.addEventListener("input", schedule);

  function quoteSource(claim, e, index) {
    if (e.kind === "figure_region") return e.panel ? `Figura · panel ${e.panel}` : "Figura";
    if (e.kind === "caption") return "Pie";
    const span = spans.get(`${claim.id}:${index}`);
    return span ? `Texto · ${span.ref} · p. ${span.page}` : "Texto · cita no encontrada";
  }
  function allGood(claim) {
    const scores = {};
    const cited = claim.evidence.some((e) => e.kind !== "figure_region");
    for (const c of criteria) scores[c.id] = c.allows_na && !cited ? "na" : 2;
    return scores;
  }
  function claimCard(claim) {
    const d = draft[claim.id];
    const [name, help] = TYPES[claim.type];
    const complete = criteria.every((c) => d.scores[c.id] !== undefined);
    const rows = criteria.map((c) => {
      const values = c.allows_na ? [0, 1, 2, "na"] : [0, 1, 2];
      return h("div", { class: "crit" },
        h("span", { class: "crit-name", title: c.question }, c.name),
        h("div", { class: "seg", role: "group", "aria-label": c.name }, values.map((v) =>
          h("button", {
            type: "button",
            "aria-pressed": String(d.scores[c.id] === v),
            title: v === "na" ? "No aplica" : `${v}: ${c.levels[v]}`,
            onclick: () => {
              if (d.scores[c.id] === v) delete d.scores[c.id];
              else d.scores[c.id] = v;
              redraw(claim);
              schedule();
            },
          }, v === "na" ? "N/A" : String(v)))));
    });
    const critical = h("select", { class: "input", "aria-label": "Error crítico" },
      h("option", { value: "" }, "Sin error crítico"),
      Object.entries(rev.rubric.critical_errors).map(([value, text]) => h("option", { value }, text)));
    critical.value = d.critical || "";
    critical.addEventListener("change", () => { d.critical = critical.value || null; redraw(claim); schedule(); });
    const note = h("input", { class: "input grow", type: "text", maxlength: "2000", placeholder: "Nota (opcional)", value: d.note });
    note.addEventListener("input", () => { d.note = note.value; schedule(); });
    return h("li", { class: `claim${d.critical ? " flagged" : complete ? " done" : ""}`, id: `claim-${claim.id}` },
      h("div", {},
        h("span", { class: `ct ${claim.type}`, title: help }, name),
        h("span", { class: "panel-tag", title: "Confianza declarada por el modelo" }, `confianza ${claim.confidence}`),
        claim.panels.map((p) => h("span", { class: "panel-tag" }, p)),
        claim.approximate ? h("span", { class: "panel-tag" }, "aprox.") : null),
      h("p", { class: "claim-text" }, claim.text),
      claim.evidence.length
        ? h("div", { class: "evidence" }, claim.evidence.map((e, i) =>
          h("div", { class: "ev" }, h("span", { class: "src" }, quoteSource(claim, e, i)), e.quote ? h("q", {}, e.quote) : null)))
        : null,
      h("div", { class: "rubric" }, rows),
      h("div", { class: "row" },
        h("button", { class: "btn", type: "button", title: "Todos los criterios a 2 (N/A en la cita si solo se apoya en la imagen)", onclick: () => { d.scores = allGood(claim); redraw(claim); schedule(); } }, "Todo bien"),
        critical, note),
    );
  }
  function redraw(claim) {
    const old = document.getElementById(`claim-${claim.id}`);
    if (old) old.replaceWith(claimCard(claim));
  }

  // Left column: what the reviewer checks the claims against.
  const viewer = createViewer();
  const context = analysis.context.length
    ? h("details", { open: true },
      h("summary", {}, `Fragmentos del artículo enviados como contexto (${analysis.context.length})`),
      h("ul", { class: "ctx" }, analysis.context.map((c) => h("li", {},
        h("div", { class: "small muted" }, `${c.ref} · página ${c.page}${c.section ? ` · ${c.section}` : ""}`),
        `${c.truncated ? "… " : ""}${c.text}${c.truncated ? " …" : ""}`))))
    : h("p", { class: "small muted" }, analysis.context_note || "No se envió texto del artículo.");

  const items = list.items;
  const index = items.findIndex((i) => i.document_id === docId && i.figure_id === figId);
  const go = (item) => { if (item) location.hash = `#/revision/explicaciones/${item.document_id}/${item.figure_id}`; };
  const nextUnscored = () => {
    for (let k = 1; k <= items.length; k++) {
      const item = items[(Math.max(index, 0) + k) % items.length];
      if (item.scored < item.claims && item.figure_id !== figId) return item;
    }
    return null;
  };

  const guide = h("details", {},
    h("summary", {}, "Guía de puntuación"),
    h("div", { class: "small" },
      h("p", {}, "Cada afirmación se puntúa de 0 a 2 en seis criterios. Compárala con la figura, el pie y los fragmentos de la izquierda. Usa «Todo bien» y corrige solo lo que falle."),
      h("ul", {}, criteria.map((c) => h("li", {}, h("strong", {}, `${c.name}: `), c.question, ` (0 ${c.levels[0]} · 1 ${c.levels[1]} · 2 ${c.levels[2]})`))),
      h("p", {}, "Un error crítico invalida la explicación aunque el resto esté bien: ", Object.values(rev.rubric.critical_errors).join(", ").toLowerCase(), "."),
    ));
  progress.textContent = `${scoredCount()} de ${explanation.claims.length}`;
  mount(
    backLink("#/revision/explicaciones", "← Lista de explicaciones"),
    h("div", { class: "figbar" },
      h("h1", {}, fig.label || "Región sin etiqueta"),
      h("span", { class: "muted" }, fig.filename),
      badge(...(ANALYSIS_BADGE[analysis.status] || [analysis.status, "neutral"])),
      h("div", { class: "nav" },
        index >= 0 ? h("span", { class: "kbd" }, `${index + 1} de ${items.length}`) : null,
        h("button", { class: "btn", type: "button", disabled: index <= 0, onclick: () => go(items[index - 1]) }, "‹ Anterior"),
        h("button", { class: "btn", type: "button", disabled: index < 0 || index >= items.length - 1, onclick: () => go(items[index + 1]) }, "Siguiente ›"),
      ),
    ),
    h("div", { class: "figure-layout" },
      h("div", { class: "left" },
        viewer.el,
        h("div", { class: "card caption-box" },
          h("div", { class: "row small muted" }, `Página ${fig.page} · `, h("a", { href: `#/d/${docId}/f/${figId}` }, "abrir en la vista de la figura")),
          h("h3", {}, "Pie de figura"),
          h("div", { class: "caption-text" }, fig.caption || "No se detectó el pie de esta figura.")),
        h("div", { class: "card caption-box" }, context),
      ),
      h("section", { class: "card expl", "aria-label": "Puntuación" },
        h("div", { class: "row" }, h("span", {}, progress, " afirmaciones puntuadas"), h("span", { class: "spacer" }), saveState),
        guide,
        h("h3", {}, "Resumen"),
        h("p", { class: "summary" }, explanation.summary),
        h("h3", {}, `Afirmaciones (${explanation.claims.length})`),
        h("ul", { class: "claims" }, explanation.claims.map(claimCard)),
        comment,
        h("div", { class: "row" },
          h("span", { class: "spacer" }),
          h("button", { class: "btn primary", type: "button", onclick: async () => { clearTimeout(timer); await save(); const next = nextUnscored(); if (next) go(next); else location.hash = "#/revision/explicaciones"; } }, "Guardar y seguir")),
      ),
    ),
  );
  if (fig.has_image) viewer.show(`/api/figures/${fig.id}/image`, fig.label || "Figura");
}

// --- panels: list ------------------------------------------------------------------------

async function renderPanelList() {
  const who = requireAnnotator();
  if (!who) return;
  document.title = "Paneles · Revisión";
  let data;
  try {
    data = await api(`/api/review/panels?annotator=${enc(who)}`);
  } catch (error) {
    mount(backLink("#/revision", "← Revisión"), h("div", { class: "alert bad" }, error.message));
    return;
  }
  if (!data.available) {
    mount(backLink("#/revision", "← Revisión"), h("div", { class: "alert" }, data.message));
    return;
  }
  const queue = panelQueue(data.items);
  const groups = new Map();
  for (const item of queue) {
    const key = `${item.split}|${item.pmcid}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  const PANEL_STATUS = { done: ["hecha", "ok"], unclear: ["dudosa", "warn"] };
  mount(
    backLink("#/revision", "← Revisión"),
    h("h1", {}, "Paneles"),
    h("p", { class: "muted small" }, `${queue.filter((i) => i.mine).length} de ${queue.length} figuras multipanel revisadas por ${who}. Empieza por dev y validation.`),
    h("div", { class: "docs" }, [...groups.values()].map((figures) =>
      h("div", { class: "card pad" },
        h("div", { class: "row" }, h("strong", {}, figures[0].pmcid), badge(figures[0].split, "neutral")),
        h("table", { class: "review-table" }, h("tbody", {}, figures.map((f) => h("tr", {},
          h("td", {}, h("a", { href: `#/revision/paneles/${enc(f.pmcid)}/${enc(f.key)}` }, f.label)),
          h("td", { class: "small muted" }, `paneles ${f.letters.split("").join(", ")}`),
          h("td", {}, f.mine ? badge(...PANEL_STATUS[f.mine]) : badge("sin revisar", "neutral")),
          h("td", { class: "small muted" }, f.reviewers > 1 ? `${f.reviewers} revisores` : ""),
        )))),
      ))),
  );
}

// --- panels: one figure ------------------------------------------------------------------

async function renderPanelReview(pmcid, key) {
  const who = requireAnnotator();
  if (!who) return;
  let fig, list;
  try {
    [fig, list] = await Promise.all([
      api(`/api/review/panel?pmcid=${enc(pmcid)}&figure=${enc(key)}&annotator=${enc(who)}`),
      api(`/api/review/panels?annotator=${enc(who)}`),
    ]);
  } catch (error) {
    mount(backLink("#/revision/paneles", "← Lista"), h("div", { class: "alert bad" }, error.message));
    return;
  }
  document.title = `Paneles de ${fig.label} · ${pmcid} · Figuris`;
  const queue = panelQueue(list.items);
  const index = queue.findIndex((i) => i.pmcid === pmcid && i.key === key);
  const href = (item) => `#/revision/paneles/${enc(item.pmcid)}/${enc(item.key)}`;
  const nextPending = () => {
    for (let k = 1; k <= queue.length; k++) {
      const item = queue[(Math.max(index, 0) + k) % queue.length];
      if (!item.mine && !(item.pmcid === pmcid && item.key === key)) return item;
    }
    return null;
  };

  const boxes = new Map((fig.review?.panels || []).filter((p) => p.bbox).map((p) => [p.label, p.bbox]));
  const absent = new Set((fig.review?.panels || []).filter((p) => p.absent).map((p) => p.label));
  const panelsInfo = [...fig.panels];
  const letters = panelsInfo.map((p) => p.label);
  const pending = () => letters.find((x) => !boxes.has(x) && !absent.has(x));
  let selected = pending() || letters[0];

  const viewer = createViewer();
  const message = h("div", { "aria-live": "polite" });
  const note = h("textarea", { class: "input", rows: "2", maxlength: "2000", placeholder: "Nota (obligatoria si es dudosa)" });
  note.value = fig.review?.note || "";
  const rows = h("ul", { class: "panel-rows" });
  const drawBtn = h("button", { type: "button", title: "Dibujar o ajustar la caja del panel elegido (D)", onclick: () => setMode("draw") }, "✎ Dibujar");
  const panBtn = h("button", { type: "button", title: "Desplazar la página (M)", onclick: () => setMode("pan") }, "✋ Mover");

  function setMode(mode) {
    viewer.setMode(mode);
    drawBtn.setAttribute("aria-pressed", String(mode === "draw"));
    panBtn.setAttribute("aria-pressed", String(mode === "pan"));
  }
  function refresh() {
    viewer.setOverlays([
      { box: fig.figure_box, cls: "figref" },
      ...[...boxes.entries()].filter(([x]) => x !== selected).map(([x, box]) => ({ box, cls: "pnl", label: x })),
    ]);
    viewer.setEditable(boxes.get(selected) || null, (box) => {
      if (box) { boxes.set(selected, box); absent.delete(selected); }
      else boxes.delete(selected);
      selected = pending() || selected;
      refresh();
    }, `panel ${selected}`);
    rows.replaceChildren(...panelsInfo.map((p) => h("li", { class: `${p.label === selected ? "selected" : ""}${absent.has(p.label) ? " absent" : ""}` },
      h("button", { class: "src", type: "button", "aria-pressed": String(p.label === selected), onclick: () => { selected = p.label; refresh(); } }, p.label),
      boxes.has(p.label) ? h("span", { class: "ok-text", title: "Caja dibujada" }, "✓")
        : absent.has(p.label) ? h("span", { class: "muted", title: "Marcada como inexistente en la figura" }, "✗") : h("span", { class: "muted" }, "—"),
      h("span", { class: "small", title: p.subcaption }, p.added ? "(letra añadida durante la revisión)"
        : p.subcaption.length > 110 ? `${p.subcaption.slice(0, 110)}…` : p.subcaption || "(sin texto propio)"),
      h("span", { class: "row small" },
        boxes.has(p.label) ? h("button", { class: "linkish", type: "button", title: "Quitar la caja de este panel", onclick: () => { boxes.delete(p.label); selected = p.label; refresh(); } }, "quitar") : null,
        !p.added && !boxes.has(p.label)
          ? h("button", { class: "linkish", type: "button", title: "El pie nombra esta letra, pero no está en la figura", onclick: () => { if (absent.has(p.label)) absent.delete(p.label); else absent.add(p.label); selected = pending() || selected; refresh(); } }, absent.has(p.label) ? "sí existe" : "no existe")
          : null,
        p.added ? h("button", { class: "linkish", type: "button", title: "Eliminar esta letra añadida", onclick: () => { boxes.delete(p.label); panelsInfo.splice(panelsInfo.indexOf(p), 1); letters.splice(letters.indexOf(p.label), 1); selected = pending() || letters[0]; refresh(); } }, "eliminar") : null),
    )));
  }
  const newLetter = h("input", { class: "input", type: "text", maxlength: "4", placeholder: "p. ej., f", "aria-label": "Letra que falta" });
  const addLetter = h("form", {
    class: "row small",
    onsubmit: (e) => {
      e.preventDefault();
      const label = newLetter.value.trim();
      if (!label) return;
      if (letters.includes(label)) { message.replaceChildren(h("div", { class: "alert" }, `La letra ${label} ya está en la lista.`)); return; }
      panelsInfo.push({ label, subcaption: "", added: true });
      letters.push(label);
      selected = label;
      newLetter.value = "";
      refresh();
    },
  }, h("span", { class: "muted" }, "¿Hay una letra en la figura que no está en la lista?"), newLetter, h("button", { class: "btn", type: "submit" }, "Añadir"));
  async function save(decision) {
    if (decision === "unclear" && !note.value.trim()) {
      message.replaceChildren(h("div", { class: "alert" }, "Explica en la nota por qué es dudosa."));
      note.focus();
      return;
    }
    try {
      await jsonPut("/api/review/panel", {
        pmcid, figure: key, annotator: who, decision, note: note.value,
        panels: letters
          .filter((label) => boxes.has(label) || absent.has(label) || panelsInfo.find((p) => p.label === label)?.added)
          .map((label) => ({ label, bbox: boxes.get(label) || null, absent: absent.has(label) })),
      });
    } catch (error) {
      message.replaceChildren(h("div", { class: "alert bad" }, error.message));
      return;
    }
    const next = nextPending();
    location.hash = next ? href(next) : "#/revision/paneles";
  }

  const position = index >= 0 ? `${index + 1} de ${queue.length}` : "";
  mount(
    backLink("#/revision/paneles", "← Lista de paneles"),
    h("div", { class: "figbar" },
      h("h1", {}, fig.label),
      h("span", { class: "muted" }, pmcid),
      badge(fig.split, "neutral"),
      h("div", { class: "nav" },
        position ? h("span", { class: "kbd" }, position) : null,
        h("button", { class: "btn", type: "button", disabled: index <= 0, onclick: () => { location.hash = href(queue[index - 1]); } }, "‹ Anterior"),
        h("button", { class: "btn", type: "button", disabled: index < 0 || index >= queue.length - 1, onclick: () => { location.hash = href(queue[index + 1]); } }, "Siguiente ›"),
      ),
    ),
    h("div", { class: "figure-layout" },
      h("div", { class: "left" },
        h("div", { class: "row" }, h("div", { class: "seg", role: "group", "aria-label": "Modo" }, drawBtn, panBtn),
          h("span", { class: "spacer" }), h("span", { class: "muted small" }, `Página ${fig.page}`)),
        viewer.el,
        h("p", { class: "small muted" }, "Rueda para ampliar · ↑ ↓ cambian de panel · D dibujar · M mover · Intro guarda"),
      ),
      h("section", { class: "card expl review-side", "aria-label": "Paneles que dibujar" },
        h("p", { class: "small" }, "Elige una letra y dibuja la caja de ese panel: el gráfico o la imagen con sus ejes, su leyenda y su letra. Al terminar una caja se pasa sola a la siguiente letra. El recuadro gris es la figura entera."),
        h("p", { class: "small muted" }, "Si el pie nombra una letra que no está en la figura, márcala con «no existe». Si en la figura hay una letra que no está en la lista, añádela abajo. Si un panel no se puede delimitar, déjalo sin caja y explícalo en la nota."),
        h("h3", {}, "Paneles según el pie"),
        rows,
        addLetter,
        note,
        h("div", { class: "row" },
          h("button", { class: "btn primary", type: "button", title: "Guardar (Intro)", onclick: () => save("done") }, "Guardar"),
          h("button", { class: "btn", type: "button", onclick: () => save("unclear") }, "Dudosa")),
        message,
        fig.review ? h("p", { class: "small muted" }, `Revisada el ${new Date(fig.review.reviewed_at).toLocaleString("es-ES")}.`) : null,
      ),
    ),
  );
  setMode("draw");
  viewer.show(`/api/review/articles/${enc(pmcid)}/pages/${fig.page}`, `Página ${fig.page} de ${pmcid}`, [], fig.figure_box);
  refresh();
  setKeys((e) => {
    if (e.target.closest("input, textarea, select")) return;
    const at = letters.indexOf(selected);
    if (e.key === "ArrowDown" && at < letters.length - 1) { selected = letters[at + 1]; refresh(); }
    else if (e.key === "ArrowUp" && at > 0) { selected = letters[at - 1]; refresh(); }
    else if (e.key === "d" || e.key === "D") setMode("draw");
    else if (e.key === "m" || e.key === "M") setMode("pan");
    else if (e.key === "Enter") save("done");
    else return;
    e.preventDefault();
  });
}

// --- routes ------------------------------------------------------------------------------

ROUTES.revision = (parts) => {
  if (parts[0] === "cajas" && parts[1] && parts[2]) renderBoxReview(parts[1], parts[2]);
  else if (parts[0] === "cajas") renderBoxList();
  else if (parts[0] === "paneles" && parts[1] && parts[2]) renderPanelReview(parts[1], parts[2]);
  else if (parts[0] === "paneles") renderPanelList();
  else if (parts[0] === "explicaciones" && parts[1] && parts[2]) renderExplanationReview(parts[1], parts[2]);
  else if (parts[0] === "explicaciones") renderExplanationList();
  else renderReviewHub();
};
