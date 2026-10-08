"""Figures of the README (docs/img/*.svg): diagrams and charts as plain SVG.

No plotting library: every figure is a few rectangles, lines and text, written so it
renders the same in GitHub and in a browser. The numbers come from the evaluation runs
named next to each chart (docs/reports/). Chart colours were checked with the dataviz
palette validator (light surface, all pairs): series 1 #00998A, series 2 #D96C4D.

Figures 1, 3 and 5 are not generated here: they are screenshots of the app and a render
of one real figure with the panel boxes of the evaluation runs.

Usage:
    python scripts/docs/make_readme_figures.py
"""

from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "docs" / "img"

INK = "#17212B"
MUTED = "#66717D"
LINE = "#DDE1DC"
GRID = "#E8EBE6"
BRAND = "#176B67"  # diagrams (not data)
SERIES_1 = "#00998A"
SERIES_2 = "#D96C4D"
REMOTE = "#D96C4D"
SOFT = "#EEF5F4"
FONT = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif"


def num(value: float, digits: int = 2) -> str:
    """Spanish decimal comma."""
    return f"{value:.{digits}f}".replace(".", ",")


class Svg:
    def __init__(self, width: int, height: int, title: str, desc: str):
        self.width, self.height = width, height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}" role="img" aria-labelledby="t d" '
            f'font-family="{FONT}">',
            f'<title id="t">{escape(title)}</title><desc id="d">{escape(desc)}</desc>',
            f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{INK}"/>'
            "</marker></defs>",
        ]

    def add(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x, y, s, size=13, fill=INK, weight=400, anchor="start", italic=False):
        style = ' font-style="italic"' if italic else ""
        self.add(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" '
            f'text-anchor="{anchor}"{style}>{escape(s)}</text>'
        )

    def rect(self, x, y, w, h, fill="#FFFFFF", stroke=INK, sw=1.2, rx=6, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"{d}/>'
        )

    def line(self, x1, y1, x2, y2, stroke=INK, sw=1.2, arrow=False, dash=None):
        m = ' marker-end="url(#arrow)"' if arrow else ""
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
            f'stroke-width="{sw}"{m}{d}/>'
        )

    def path(self, d, stroke=INK, sw=1.2, arrow=False, fill="none"):
        m = ' marker-end="url(#arrow)"' if arrow else ""
        self.add(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{m}/>')

    def save(self, name: str) -> None:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_text("\n".join([*self.parts, "</svg>"]) + "\n", encoding="utf-8")


# --- Figure 2: architecture ------------------------------------------------------------


def architecture() -> None:
    s = Svg(
        960,
        470,
        "Arquitectura de Figuris",
        "Diez etapas en dos filas. La extracción, la evidencia, los paneles, el contexto y la "
        "validación son locales y deterministas, salvo el OCR, que usa redes neuronales locales. "
        "Solo la explicación llama a un modelo multimodal remoto.",
    )
    w, h, gap, x0 = 164, 96, 22, 28
    xs = [x0 + i * (w + gap) for i in range(5)]
    rows = [
        (
            92,
            [
                ("1", "Ingesta", ["Validación del PDF", "y huella SHA-256"], "det"),
                ("2", "Maquetación", ["pdfium: líneas de texto", "y elementos gráficos"], "det"),
                (
                    "3",
                    "Figuras y pies",
                    ["Rejilla de ocupación;", "región ↔ pie más cercano"],
                    "det",
                ),
                ("4", "Capa de evidencia", ["Texto del PDF + OCR", "PP-OCRv6 (ONNX)"], "nn"),
                ("5", "Paneles", ["Cortes por huecos y", "anclas en las letras"], "det"),
            ],
        ),
        (
            300,
            [
                (
                    "6",
                    "Texto y menciones",
                    ["Párrafos con página;", "«Fig. 2b», «Figs. 3–5»"],
                    "det",
                ),
                ("7", "Contexto", ["Párrafos que citan la", "figura, con presupuesto"], "det"),
                ("8", "Explicación", ["Modelo multimodal;", "JSON con esquema estricto"], "llm"),
                ("9", "Validación", ["Citas literales, paneles", "y números comprobados"], "det"),
                (
                    "10",
                    "Almacén e interfaz",
                    ["SQLite + archivos; caché", "por contenido; Figuris"],
                    "det",
                ),
            ],
        ),
    ]
    s.text(22, 30, "Procesamiento del documento", 14, INK, 600)
    s.text(22, 50, "Local y reproducible: el mismo PDF da siempre el mismo resultado", 12, MUTED)
    s.text(22, 252, "Explicación y control", 14, INK, 600)
    s.text(
        22, 272, "Una sola llamada a un modelo remoto por figura, vigilada por reglas", 12, MUTED
    )
    for y, boxes in rows:
        for i, (n, title, lines, kind) in enumerate(boxes):
            x = xs[i]
            fill = SOFT if kind == "nn" else "#FFFFFF"
            stroke = REMOTE if kind == "llm" else INK
            s.rect(
                x, y, w, h, fill=fill, stroke=stroke, sw=1.4, dash="5 3" if kind == "llm" else None
            )
            s.add(
                f'<circle cx="{x + 18}" cy="{y + 20}" r="10" fill="{BRAND if kind != "llm" else REMOTE}"/>'
            )
            s.text(x + 18, y + 24, n, 11, "#FFFFFF", 700, "middle")
            s.text(x + 34, y + 25, title, 13.5, INK, 600)
            for j, ln in enumerate(lines):
                s.text(x + 12, y + 52 + j * 17, ln, 11.5, MUTED)
            if i < 4:
                s.line(x + w, y + h / 2, x + w + gap - 1, y + h / 2, arrow=True)
    # row 1 -> row 2
    end_x = xs[4] + w / 2
    turn_y = 92 + h + 22
    s.path(f"M{end_x} {92 + h} V{turn_y} H{x0 - 12} V{300 + h / 2} H{x0 - 1}", arrow=True)
    s.text(
        end_x - 8,
        turn_y - 6,
        "figuras, pies, paneles y texto de cada figura",
        11,
        MUTED,
        anchor="end",
    )
    # legend
    ly = 438
    s.rect(22, ly - 12, 16, 14, rx=3)
    s.text(46, ly, "Determinista (reglas y geometría)", 12, INK)
    s.rect(272, ly - 12, 16, 14, fill=SOFT, rx=3)
    s.text(296, ly, "Red neuronal local (OCR)", 12, INK)
    s.rect(478, ly - 12, 16, 14, stroke=REMOTE, dash="4 2", rx=3)
    s.text(502, ly, "Modelo multimodal remoto (API)", 12, INK)
    s.save("fig02-arquitectura.svg")


# --- Figure 3: what an explanation is ---------------------------------------------------


def explanation() -> None:
    s = Svg(
        960,
        400,
        "Estructura de una explicación",
        "Cada afirmación tiene un tipo y cita su evidencia: la región o el panel de la figura, "
        "una cita literal del pie o de un párrafo con su página, o un valor impreso en la "
        "figura. El validador comprueba cada cita antes de mostrarla.",
    )
    s.text(22, 30, "Afirmaciones tipadas", 14, INK, 600)
    s.text(600, 30, "Evidencia que cita cada una", 14, INK, 600)
    claims = [
        ("observado", "La curva de circDIDO1 cae a partir del día 3.", BRAND),
        ("según los autores", "«CircDIDO1 inhibe la progresión del cáncer»", "#3E6B89"),
        ("inferencia", "El efecto parece depender de la dosis.", "#9A5B12"),
        ("incierto", "No se puede leer el valor exacto del panel h.", MUTED),
    ]
    evidence = [
        ("Región o panel de la figura", "panel c, ampliado en el visor"),
        ("Cita literal del pie", "comprobada carácter a carácter"),
        ("Cita literal de un párrafo", "con su página y su sección"),
        ("Valor impreso en la figura", "localizado por el texto PDF u OCR"),
    ]
    links = [(0, 0), (0, 3), (1, 1), (1, 2), (2, 0), (2, 2), (3, 0)]
    cy = [70 + i * 74 for i in range(4)]
    for i, (kind, text, color) in enumerate(claims):
        y = cy[i]
        s.rect(22, y, 420, 56, sw=1.1)
        tw = 8 + len(kind) * 7.2
        s.rect(34, y + 10, tw, 20, stroke=color, rx=3)
        s.text(34 + tw / 2, y + 24, kind, 11.5, color, 600, "middle")
        s.text(34, y + 47, text, 12.5, INK)
    for i, (title, sub) in enumerate(evidence):
        y = cy[i]
        s.rect(600, y, 338, 56, fill=SOFT if i == 3 else "#FFFFFF", sw=1.1)
        s.text(616, y + 25, title, 13, INK, 600)
        s.text(616, y + 44, sub, 11.5, MUTED)
    for c, e in links:
        s.path(
            f"M442 {cy[c] + 28} C520 {cy[c] + 28} 520 {cy[e] + 28} 598 {cy[e] + 28}",
            stroke=MUTED,
            sw=1,
            arrow=True,
        )
    s.rect(22, 370 - 14, 916, 30, fill="#FBFCFA", stroke=LINE, rx=4)
    s.text(
        34,
        375,
        "Validador: una cita que no aparece literalmente en su fuente, un panel inexistente o una "
        "referencia rota marcan la explicación como «no fiable».",
        12,
        INK,
    )
    s.save("fig04-esquema-explicacion.svg")


# --- Figure 5: results, dot plot ----------------------------------------------------------


def results() -> None:
    # sfi48 runs: dev+validation (stage5-sfi48-baseline.md) and test
    # (evaluation/runs/20261008-082410-sfi48-0.3.1-a0a36922).
    rows = [
        ("F1 de cajas de figura", 0.990, 0.874, 0.90),
        ("Asociación figura–pie", 0.985, 0.946, 0.95),
        ("Contexto: Recall@5", 0.949, 0.934, 0.90),
        ("Etiquetas de figura (F1)", 0.996, 0.935, 0.90),
    ]
    s = Svg(
        960,
        340,
        "Resultados en SFI-48: desarrollo frente a test",
        "Gráfico de puntos. Para cada métrica, valor en dev + validation y en test, con el umbral "
        "del plan. Las cajas de figura, los pies y las pérdidas bajan en test por los escaneados.",
    )
    left, right, top = 250, 900, 84
    lo, hi = 0.80, 1.00

    def X(v):
        return left + (v - lo) / (hi - lo) * (right - left)

    s.text(22, 30, "Extracción y contexto en SFI-48", 14, INK, 600)
    # legend
    s.add(f'<circle cx="560" cy="25" r="5.5" fill="{SERIES_1}"/>')
    s.text(572, 30, "dev + validation (24 artículos, 150 figuras)", 12, INK)
    s.add(f'<circle cx="560" cy="45" r="5.5" fill="{SERIES_2}"/>')
    s.text(572, 50, "test (24 artículos, 142 figuras, evaluado una vez)", 12, INK)
    for t in [0.80, 0.85, 0.90, 0.95, 1.00]:
        s.line(X(t), top, X(t), top + len(rows) * 52, stroke=GRID, sw=1)
        s.text(X(t), top + len(rows) * 52 + 18, num(t), 11.5, MUTED, anchor="middle")
    for i, (name, dev, test, gate) in enumerate(rows):
        y = top + 26 + i * 52
        s.text(22, y + 4, name, 13, INK)
        s.line(X(min(dev, test)), y, X(max(dev, test)), y, stroke=LINE, sw=3)
        s.line(X(gate), y - 13, X(gate), y + 13, stroke=INK, sw=1.6)
        s.add(
            f'<circle cx="{X(dev)}" cy="{y}" r="6" fill="{SERIES_1}" stroke="#FFFFFF" stroke-width="2"/>'
        )
        s.add(
            f'<circle cx="{X(test)}" cy="{y}" r="6" fill="{SERIES_2}" stroke="#FFFFFF" stroke-width="2"/>'
        )
        s.text(X(test) - 10, y - 10, num(test, 3), 11.5, INK, anchor="end")
        s.text(
            X(dev) + 10 if dev < 0.985 else X(dev) - 2,
            y - 10,
            num(dev, 3),
            11.5,
            INK,
            anchor="start" if dev < 0.985 else "end",
        )
    s.line(560, 59, 560, 71, stroke=INK, sw=1.6)
    s.text(572, 69, "umbral del plan para esa métrica", 12, INK)
    s.save("fig06-resultados.svg")


# --- Figure 6: panels -------------------------------------------------------------------


def panels() -> None:
    # panel runs: 20261007-183816 (0.1) and 20261008-081320 (0.2), stage5-panels.md
    rows = [
        ("Cortes por huecos (base)", 0.54, "dev"),
        ("Anclas en letras 0.1", 0.66, "dev"),
        ("Anclas 0.2 · diseño (dev)", 0.83, "dev"),
        ("Anclas 0.2 · nuevas (validation)", 0.61, "val"),
    ]
    s = Svg(
        960,
        300,
        "Separación de paneles: AP50 frente a las cajas humanas",
        "Barras horizontales. El método mejora de 0,54 a 0,83 en las figuras usadas para "
        "diseñarlo, pero da 0,61 en las 34 figuras nuevas de validation. Umbral 0,85.",
    )
    left, right, top, bh = 250, 880, 72, 22

    def X(v):
        return left + v * (right - left)

    s.text(22, 30, "Paneles bien localizados (AP con IoU ≥ 0,5)", 14, INK, 600)
    s.add(f'<rect x="560" y="18" width="12" height="12" rx="2" fill="{SERIES_1}"/>')
    s.text(578, 29, "figuras usadas para diseñar el método", 12, INK)
    s.add(f'<rect x="560" y="38" width="12" height="12" rx="2" fill="{SERIES_2}"/>')
    s.text(578, 49, "figuras nuevas (34, validation)", 12, INK)
    for t in [0, 0.25, 0.5, 0.75, 1.0]:
        s.line(X(t), top - 6, X(t), top + 4 * 44, stroke=GRID, sw=1)
        s.text(X(t), top + 4 * 44 + 18, num(t), 11.5, MUTED, anchor="middle")
    for i, (name, v, split) in enumerate(rows):
        y = top + i * 44 + 6
        color = SERIES_1 if split == "dev" else SERIES_2
        s.text(22, y + 16, name, 13, INK)
        w = X(v) - left
        s.add(
            f'<path d="M{left} {y}H{left + w - 4}a4 4 0 0 1 4 4v{bh - 8}a4 4 0 0 1 -4 4H{left}z" fill="{color}"/>'
        )
        lx = left + w + 8
        if abs(v - 0.85) < 0.05:
            lx = X(0.85) + 8  # keep the value clear of the threshold line
        s.text(lx, y + 16, num(v), 12.5, INK, 600)
    s.line(X(0.85), top - 14, X(0.85), top + 4 * 44, stroke=INK, sw=1.6)
    s.text(X(0.85) + 6, top - 4, "umbral 0,85", 11.5, INK)
    s.save("fig07-paneles.svg")


# --- Figure 7: invented references ------------------------------------------------------


def references() -> None:
    # evaluation/runs/20261008-091722-references-test-ef02c460
    s = Svg(
        960,
        210,
        "Citas inventadas en test",
        "De 149 explicaciones con 1437 afirmaciones y 1716 citas, el modelo inventó 7 citas en "
        "5 explicaciones; el validador detectó las 7 y ninguna se muestra como fiable.",
    )
    steps = [
        ("149", "explicaciones de test", "1 437 afirmaciones, 1 716 citas"),
        (
            "7",
            "citas inventadas",
            "en 5 explicaciones: 4 de párrafo,",
            "1 del pie, 2 a afirmaciones",
        ),
        ("7 de 7", "detectadas", "por el validador, sin IA"),
        ("0", "mostradas como fiables", "las 5 aparecen como «no fiable»"),
    ]
    w, gap, x0, y = 205, 30, 22, 54
    s.text(22, 30, "Control de citas en test", 14, INK, 600)
    for i, (big, title, *sub) in enumerate(steps):
        x = x0 + i * (w + gap)
        s.rect(x, y, w, 128, fill=SOFT if i >= 2 else "#FFFFFF", sw=1.2)
        s.text(x + 16, y + 44, big, 30, BRAND if i >= 2 else INK, 600)
        s.text(x + 16, y + 70, title, 13, INK, 600)
        for j, ln in enumerate(sub):
            s.text(x + 16, y + 92 + j * 16, ln, 11.5, MUTED)
        if i < 3:
            s.line(x + w, y + 64, x + w + gap - 1, y + 64, arrow=True)
    s.save("fig08-citas.svg")


if __name__ == "__main__":
    architecture()
    explanation()
    results()
    panels()
    references()
    print(f"figures written to {OUT}")
