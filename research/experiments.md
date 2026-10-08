# Corpus y experimentos comparativos

**Fecha:** 2026-10-06  
**Estado:** protocolo propuesto; todavía no se han ejecutado benchmarks.

## Principios

- La evaluación empieza antes de seleccionar componentes.
- Un conjunto oculto no se usa para ajustar heurísticas, prompts ni thresholds.
- Cada ejecución registra input hash, versión/commit, configuración, hardware, seed, latencia, memoria, coste y outputs completos.
- Las métricas automáticas se acompañan de análisis de error estratificado y revisión humana.
- Los documentos y anotaciones se almacenan solo cuando su licencia lo permite.

## Corpus inicial SFI-48

### Piloto previo SFI-12

Antes de construir SFI-48 se seleccionarán 12 artículos de PMC Open Access con licencia CC BY verificada por artículo. Este piloto pequeño corresponde a la Etapa 0 y sirve para desarrollar el flujo PDF–figura–contexto–explicación sin esperar al benchmark completo.

- descarga únicamente mediante vías oficiales de PMC;
- mezcla de gráficos, multipaneles, microscopía/imagen biomédica, diagramas, texto pequeño y PDF difíciles;
- manifiesto con PMC ID, DOI, URL, licencia, atribución, excepciones por figura, fecha y SHA-256;
- PDF y artefactos en rutas ignoradas por Git;
- revisión de cualquier crédito de terceros que pueda excluir una figura concreta de la licencia general del artículo.

El manifiesto puede publicarse; los PDF no se incorporan al repositorio por defecto. SFI-12 no sustituye los conjuntos separados de desarrollo, validación y test de SFI-48.

### Tamaño y partición

Proponer 48 artículos completos y, como mínimo, 240 figuras anotadas:

- `dev`: 12 artículos para desarrollar esquemas y herramientas de anotación;
- `validation`: 12 artículos para ajustar configuraciones;
- `test`: 24 artículos congelados antes de elegir componentes.

El piloto E01 puede empezar con 24 artículos equilibrados (`dev` + `validation`); el test permanece oculto hasta cerrar el pipeline candidato.

### Matriz de selección

| Dimensión | Cuotas objetivo |
|---|---|
| Disciplina | biomedicina, química/materiales, física/astronomía, ciencias ambientales/geoespaciales, informática/ingeniería y ciencias sociales: 8 papers cada una |
| Tipo PDF | 32 born-digital limpios, 8 born-digital difíciles, 8 escaneados/degradados |
| Layout | una y dos columnas, landscape, suplementos, captions laterales y figuras a página completa |
| Figura | charts, diagramas, microscopía/imagen médica, mapas, estructuras moleculares, resultados experimentales, tablas-imagen y mixed/other |
| Paneles | al menos 45% figuras multipanel; incluir etiquetas A/a/i y paneles sin etiqueta |
| Idioma | primera versión principalmente inglés; reservar 8 papers para otros idiomas latinos si las licencias lo permiten |
| Fuente | preferencia por PMC OA con JATS y licencia CC BY/CC0; completar con arXiv solo tras verificar licencia por item |

### Selección legal

1. Consultar metadatos y licencia por artículo.
2. Aceptar para distribución interna/externa solo licencias compatibles con el uso previsto.
3. Guardar `license_id`, URL, atribución, fecha, fuente y hash SHA-256.
4. Si la licencia permite evaluación pero no redistribución, conservar solo ID, URL y anotaciones que no reproduzcan contenido protegido.
5. Descargar PMC mediante sus datasets/APIs autorizados, no scraping ad hoc.

### Gold standard por figura

```json
{
  "document_id": "sha256:...",
  "page_index": 4,
  "figure_id": "fig-3",
  "label": "Figure 3",
  "figure_bbox": [0.12, 0.24, 0.88, 0.67],
  "caption_bbox": [0.12, 0.68, 0.88, 0.76],
  "caption_text": "...",
  "section_path": ["Results", "Ablation study"],
  "panels": [
    {"panel_id": "fig-3-a", "label": "A", "bbox": [0.12, 0.24, 0.49, 0.67], "subcaption": "..."}
  ],
  "mentions": [
    {"text": "Fig. 3A", "page_index": 3, "char_span": [124, 131], "bbox": []}
  ],
  "visual_elements": {
    "axes": [], "units": [], "legend_entries": [], "scale_bars": [], "symbols": []
  },
  "qa": [],
  "ambiguities": [],
  "annotator_ids": ["ann-1", "ann-2"],
  "adjudicated_by": "ann-3"
}
```

Las coordenadas se normalizan a `[0,1]` sobre el CropBox, con origen arriba-izquierda. También se conserva la geometría original y la transformación usada para cada render.

## Protocolo de anotación humana

1. Escribir guía y ejemplos positivos/negativos antes de anotar `validation`.
2. Doble anotación ciega del 25% de figuras y 100% de preguntas/respuestas de `test`.
3. Medir IoU/acuerdo para cajas, Cohen's kappa o Krippendorff's alpha para etiquetas y acuerdo exacto/F1 para campos.
4. Adjudicar desacuerdos sin mostrar la salida del sistema.
5. Registrar `unclear` en lugar de forzar una respuesta.
6. Ejecutar una auditoría de fuga entre documentos, figuras casi duplicadas y versiones preprint/publicada.

Objetivos mínimos de acuerdo antes de usar el gold:

- kappa/alpha >= 0,80 para tipo de figura y contestabilidad;
- IoU mediana >= 0,90 para figura/caption y >= 0,85 para paneles;
- acuerdo >= 0,90 para vínculos figura-mención tras adjudicación.

## Experimentos

### E01 — Parsing, figuras y captions

**Pregunta:** ¿qué combinación recupera mejor estructura, figura, caption y procedencia?

**Candidatos:**

- Docling;
- GROBID;
- Docling + GROBID reconciliados;
- PDFFigures 2.0;
- pikepdf/pypdfium2 + baseline caption-anchored;
- Marker y MinerU, si las condiciones de pesos y ejecución se aprueban.

**Métricas:** precision/recall/F1 a IoU 0,5 y 0,75; mAP; caption association accuracy; normalized edit distance del caption; page/figure ID accuracy; reading-order edit distance; porcentaje de figuras con artefacto nativo y render completo; pérdida de contenido; fallos por paper; segundos/página, RAM/VRAM, coste/página.

**Gate provisional:** F1 de figura >= 0,90, asociación de caption >= 0,95 y cero pérdidas silenciosas en el test de integridad. Si ningún candidato llega, se elige el mejor ensemble verificable y se documenta el gap.

### E02 — Separación y etiquetado multipanel

**Baselines:** whitespace/connected components; detector genérico fine-tuned; modelo especializado disponible con licencia; MLLM con salida de regiones solo como challenger.

**Métricas:** panel mAP50/mAP50:95, exactitud del número de paneles, label accuracy, panel-subcaption linking F1, over/under-segmentation, rendimiento por modalidad y layout.

**Gate provisional:** mAP50 >= 0,85, label accuracy >= 0,90 y F1 panel-subcaption >= 0,85. Publicar siempre el recorte compuesto si la confianza de paneles no supera el threshold calibrado.

### E03 — OCR y elementos visuales

**Candidatos:** texto PDF nativo, PaddleOCR, Tesseract/OCRmyPDF y OCR multimodal del modelo final.

**Estratos:** fuente >=12 px, fuente pequeña, texto rotado, fórmulas, microscopía con scale bar, charts con ejes densos y fondos complejos.

**Métricas:** CER/WER, entity accuracy para números/unidades, box IoU, axis-title/tick/legend completeness, scale-bar value accuracy y calibration error de confianza.

**Gate provisional:** entity accuracy >= 0,95 en born-digital y >= 0,88 en raster; cualquier valor numérico usado en una respuesta debe vincularse a un token OCR o a un span textual.

### E04 — Recuperación de contexto

**Candidatos:** ventana alrededor de mención; BM25; dense text; late fusion de caption, mentions y section; índice visual+texto.

**Gold:** párrafos necesarios/suficientes por pregunta y etiquetas `methods`, `results`, `limitations`, `irrelevant`.

**Métricas:** Recall@1/3/5, MRR, nDCG, precision de contexto, tokens irrelevantes, latencia y coste. Evaluar consultas sobre una figura, un panel y varias figuras.

**Gate provisional:** Recall@5 >= 0,90 y precision de contexto >= 0,70. Favorecer late fusion si iguala calidad con menor complejidad que un índice multimodal único.

### E05 — Comprensión visual y QA

**Diseño factorial:** modelo x resolución x evidencia (`imagen`, `imagen+caption`, `imagen+caption+mentions`, `EvidenceBundle completo`). Incluir al menos un modelo local y dos APIs cuando sea viable.

**Tipos de pregunta:** observación, valor, comparación, tendencia, anomalía, método, relación entre figuras, afirmación del autor, inferencia y no contestable.

**Métricas:** exact match/F1 para respuestas cerradas; tolerancia numérica declarada; rúbrica humana 1–5; factual consistency; answerability accuracy; unsupported claim rate; coste y p50/p95.

**Gate provisional:** >= 0,90 answerability accuracy, <= 0,02 unsupported-claim rate en respuestas de alta confianza y mejora significativa frente a `caption only`.

### E06 — Grounding y citas

Dividir cada respuesta en afirmaciones atómicas. Para cada una verificar existencia de la fuente, entailment, granularidad y localización.

**Métricas:** citation precision/recall, claim support precision, page/region accuracy, citation completeness, contradicción y `abstention precision`.

**Gate provisional:** citation precision >= 0,95, citation completeness >= 0,90 y cero IDs inventados. Las afirmaciones sin evidencia se eliminan o se etiquetan como inferencia/incertidumbre.

### E07 — Seguridad y robustez

Casos: PDF corrupto, zip bomb embebida, objetos enormes, fuentes malformadas, páginas extremas, enlaces remotos, prompt injection dentro del texto/figura, instrucciones que piden ignorar políticas, datos privados y documentos duplicados.

**Métricas:** tasa de contención, falsos positivos, recursos máximos, escapes de red, ejecución de contenido activo y obediencia a instrucciones del documento.

**Gate:** ningún contenido del documento puede cambiar políticas, herramientas o destino de datos; procesamiento en sandbox sin red por defecto; límites de tamaño/páginas/tiempo aplicados.

### E08 — Sistema y experiencia de usuario

Medir tiempo a primera figura, tiempo a documento completo, p95 de consulta, reanudación, cache hit rate, consistencia de overlays, accesibilidad, y tiempo humano para verificar una afirmación.

**Objetivo de producto inicial:** el usuario puede llegar desde una afirmación a la región exacta del PDF en un máximo de dos interacciones.

## Métricas agregadas sin ocultar fallos

No crear un único score hasta estabilizar métricas por componente. Después, un dashboard puede mostrar:

```text
quality = geometric_mean(
  extraction_f1,
  panel_f1,
  context_recall_at_5,
  grounded_claim_rate,
  answer_correctness
)
```

El coste y la latencia se muestran en un eje separado; no se compensan errores de grounding con velocidad.

## Reproducibilidad

Estructura prevista de resultados:

```text
evaluation/
  corpus/manifest.jsonl
  annotations/schema.json
  annotations/{dev,validation,test}/
  runs/<run-id>/
    manifest.yaml
    predictions.jsonl
    metrics.json
    errors.jsonl
    report.md
```

Cada `run-id` incorpora fecha, componente, versión y hash corto de configuración. El conjunto `test` requiere un comando explícito y registra quién lo ejecutó para limitar tuning accidental.

