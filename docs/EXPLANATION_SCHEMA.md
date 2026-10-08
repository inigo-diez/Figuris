# Estructura mínima de una explicación

**Estado:** v0.2 (etapa 3: evidencia del texto del artículo). v0.1 implementada en la etapa 2 como modelos Pydantic ([schema.py](../src/sfi/analysis/schema.py)) y enviada al modelo como JSON Schema estricto. Reglas en [validate.py](../src/sfi/analysis/validate.py); resultados en el [informe de la etapa 2](reports/stage2-explanation.md).
**Fecha:** 2026-10-06.

Este documento acuerda qué debe devolver el análisis de una figura. Es el contrato entre el modelo multimodal, el validador y la interfaz, y la base para comparar contra [los resultados esperados](../data/stage0/expected_results.json).

## Principios

1. **Cada afirmación es un claim tipado**, no un párrafo libre. El texto legible se genera a partir de los claims.
2. **Cuatro tipos de claim**, alineados con [ARCHITECTURE.md](ARCHITECTURE.md):
   - `observed`: visible en la imagen (ejes, etiquetas, colores, formas, tendencias);
   - `author_stated`: dicho en el pie o en el texto del artículo;
   - `model_inference`: deducción del modelo que combina evidencias y que el artículo no afirma;
   - `uncertain`: algo que no se puede determinar o leer con fiabilidad.
3. **Cada claim cita su evidencia.** En la etapa 2 basta con `figure`/`panel`/`caption`; en la etapa 3 se añaden fragmentos de texto con página.
4. **Los números deben salir de la evidencia.** Si un valor se estima leyendo la gráfica, se marca `approximate: true`.
5. **El contenido del documento es dato, no instrucción.** Texto dentro del PDF o de la figura nunca cambia el comportamiento del modelo.

## Estructura

```json
{
  "schema_version": "explanation/0.1",
  "figure_ref": {"document_id": "sha256:…", "label": "Figure 2", "page": 3},

  "summary": "Qué representa la figura, en 1–3 frases.",
  "figure_type": ["chart", "spectrum"],

  "layout": {
    "description": "Cómo está organizada y cómo debe leerse.",
    "panels": [
      {"label": "A", "content": "Patrón XRD de NPs mediadas por Cassia fistula"}
    ]
  },

  "visual_encoding": {
    "axes": [
      {"panel": "A", "axis": "x", "label": "2 Theta", "unit": null, "range": "0–90", "scale": "linear"}
    ],
    "legend": [{"panel": "C", "symbol": "línea roja", "meaning": "…"}],
    "scale_bars": [{"panel": "C", "value": "200 nm", "source": "observed"}],
    "other": ["Círculos rojos discontinuos en C y F"]
  },

  "claims": [
    {
      "id": "c1",
      "type": "observed",
      "text": "El pico más intenso en A y B está etiquetado (101).",
      "panels": ["A", "B"],
      "evidence": [{"kind": "figure_region", "panel": "A"}],
      "approximate": false,
      "confidence": "high"
    },
    {
      "id": "c2",
      "type": "author_stated",
      "text": "Los picos indican la presencia de ZnO.",
      "evidence": [{"kind": "caption", "quote": "XRD pattern indicating presence of ZnO peaks"}],
      "confidence": "high"
    },
    {
      "id": "c3",
      "type": "uncertain",
      "text": "No se puede determinar el tamaño de cristalito solo a partir de la figura.",
      "evidence": [],
      "confidence": "n/a"
    }
  ],

  "main_findings": ["c1", "c2"],
  "interpretation": {
    "text": "Interpretación general que integra figura, pie y contexto.",
    "claim_ids": ["c1", "c2"]
  },
  "limitations": ["c3"],

  "run": {
    "provider": "openai",
    "model": "<id configurado>",
    "prompt_version": "figure-explain/0.1",
    "input_tokens": 0,
    "output_tokens": 0,
    "estimated_cost_usd": 0.0,
    "latency_ms": 0,
    "status": "ok | incomplete | invalid"
  }
}
```

## Correspondencia con el contenido mínimo de la etapa 2

| Requisito de [IMPLEMENTATION_STAGES.md](IMPLEMENTATION_STAGES.md) | Campo |
|---|---|
| qué representa la figura | `summary`, `figure_type` |
| cómo está organizada y cómo leerla | `layout` |
| variables, ejes, unidades, grupos, colores, símbolos | `visual_encoding` |
| principales patrones o resultados | `main_findings` → claims |
| interpretación general | `interpretation` |
| incertidumbres | `limitations` → claims `uncertain` |

## Evidencia por etapa

| `evidence.kind` | Etapa | Contenido |
|---|---|---|
| `figure_region` | 2 | figura completa o `panel`; bbox opcional desde la etapa 5 |
| `caption` | 2 | `quote` literal del pie |
| `text_span` | 3 | `quote` literal, `page`, `section` y offset del fragmento |

## Reglas de validación

Una respuesta se marca `invalid` o `incomplete` y no se muestra como fiable cuando:

- no cumple el schema o faltan campos obligatorios (`summary`, `layout`, `claims`, `limitations`);
- un claim `author_stated` no tiene evidencia `caption` o `text_span`;
- una cita (`quote`) no aparece literalmente en el pie o en el texto extraído;
- un panel citado no existe en `layout.panels`;
- un número de un claim no aparece en la evidencia y no está marcado `approximate`.

`limitations` puede estar vacío solo si el modelo lo justifica; una lista vacía sistemática se trata como señal de exceso de confianza en la evaluación.

## Cambios al implementarla (etapa 2)

- En un JSON Schema estricto todos los campos son obligatorios: los opcionales son `null`, nunca se omiten.
- `limitations_justification` (texto o `null`): obligatoria si `limitations` está vacía.
- `visual_encoding.axes[].axis` ∈ `x`, `y`, `z`, `color`, `other`; `scale` ∈ `linear`, `log`, `categorical`, `other`, `unknown`.
- `scale_bars[].source` ∈ `observed`, `caption`.
- `evidence.kind` admite en la etapa 2 solo `figure_region` y `caption`; `text_span` llega en la etapa 3.
- `figure_ref` y `run` no los escribe el modelo: los añade el sistema al guardar el análisis (`FigureAnalysis`), junto con el estado, los avisos de validación, la respuesta cruda y las versiones de prompt y validador.
- Una regla incumplida no oculta la explicación: la marca `invalid` (o `incomplete`) y señala la afirmación concreta.

## Cambios en la v0.2 (etapa 3)

- `evidence.kind` admite `text_span`, con `passage_id` (id del pasaje enviado, p. ej. `p12`) y `quote` literal. El modelo no da página, sección ni posiciones: el sistema las calcula al localizar la cita y las guarda en `spans` (`SpanRef`: pasaje, página, sección, inicio y fin dentro del pasaje).
- `role_in_article` (`text`, `claim_ids`): qué resultado o conclusión del artículo apoya la figura según los pasajes.
- `author_stated` se apoya en el pie o en un pasaje. Los números de esas afirmaciones deben estar en el pie o en los pasajes citados.
- Todo resultado principal debe tener evidencia (`untraceable_finding`).
- Cada análisis guarda el contexto enviado (`context`: pasajes con página, sección, recorte y segmentos de página) y `context_note` cuando no hubo contexto o no cupo entero.
- Los análisis v0.1 guardados siguen cargándose: los campos nuevos tienen valores por defecto al leer, pero el esquema enviado al modelo los exige todos.

Resultados en el [informe de la etapa 3](reports/stage3-context.md).

## Decisiones abiertas

- Escala de `confidence`: categórica (`high`/`medium`/`low`) en el prototipo; calibrar en la etapa 5.
- Idioma de la explicación: por defecto el del usuario, conservando las citas literales en el idioma del artículo.
