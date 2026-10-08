# Estado del arte y panorama competitivo

**Fecha de corte:** 2026-10-06  
**Estado:** investigación inicial; las selecciones de componentes críticos siguen sujetas a benchmark.  
**Alcance:** extracción, estructuración, comprensión, consulta y visualización de figuras de artículos científicos.

## Resumen ejecutivo

No hay una solución abierta y mantenida que resuelva de extremo a extremo, y con evidencia verificable, la extracción de figuras, la separación de paneles, la vinculación con captions y menciones, la lectura de elementos visuales y el razonamiento científico. El mercado se divide en cuatro grupos:

1. Parsers documentales generales, como [Docling](https://github.com/docling-project/docling), [MinerU](https://github.com/opendatalab/MinerU), [Marker](https://github.com/datalab-to/marker) y [Unstructured](https://github.com/Unstructured-IO/unstructured).
2. Parsers científicos, principalmente [GROBID](https://github.com/grobidOrg/grobid), [PDFFigures 2.0](https://github.com/allenai/pdffigures2) y el prototipo [PaperMage](https://github.com/allenai/papermage).
3. Modelos y datasets especializados en paneles, charts y scientific VQA, como FigEx/BioSci-Fig, SPIQA, SciVQA, ChartQAPro y ChartBench.
4. Productos de lectura o revisión de literatura, como SciSpace, Elicit, NotebookLM, Explainpaper y Semantic Scholar.

La recomendación es construir una capa propia de dominio y procedencia, no un parser propio desde cero. La primera hipótesis a validar es:

- usar JATS/XML o HTML editorial cuando exista y el PDF como representación visual canónica;
- comparar Docling y GROBID como fuentes estructurales complementarias;
- conservar imágenes incrustadas sin recodificar mediante pikepdf y producir también recortes renderizados trazables;
- mantener PDFFigures 2.0 como baseline especializado, no como dependencia principal por su inactividad desde 2022;
- evaluar Marker y MinerU como challengers, con revisión separada de licencias de código y pesos;
- desarrollar una capa específica de asociación, paneles y evidencia sobre un modelo documental normalizado;
- usar modelos multimodales detrás de adaptadores propios y exigir salidas estructuradas con citas por afirmación;
- no introducir LangChain o LangGraph durante el núcleo determinista del pipeline.

Esta recomendación es una inferencia de la evidencia disponible. No sustituye los experimentos definidos en [experiments.md](experiments.md).

## Método y límites

Se revisaron repositorios oficiales, documentación de los proyectos, papers originales y páginas oficiales de productos. La actividad se calificó mediante releases, changelogs o commits visibles a la fecha de corte; no se interpreta el número de estrellas como calidad. Las licencias de código, pesos, datasets y documentos fuente se tratan como activos distintos.

La investigación no incluye todavía una ejecución comparable sobre el corpus propio. Las cifras publicadas por cada proyecto no son directamente comparables si usan versiones, documentos, métricas o configuraciones diferentes. [OmniDocBench](https://github.com/opendatalab/OmniDocBench) es útil como benchmark externo de parsing, pero su dataset se declara solo para investigación y no debe convertirse en el corpus comercial del producto.

## Hallazgos por capa

### 1. Ingesta y parsing documental

**Docling** ofrece una representación documental unificada, extracción de imágenes con captions, layout y tablas. El proyecto es MIT y mantiene una cadencia alta; `docling-serve` publicó la versión 1.36.0 el 1 de octubre de 2026. Su arquitectura modular y su `DoclingDocument` lo convierten en el mejor candidato para parser general y baseline productivo. Sus modelos tienen licencias propias que deben fijarse y auditarse por versión.

**GROBID** sigue siendo la referencia para estructura específicamente científica: metadatos, secciones, referencias, figuras, tablas, párrafos y callouts. Puede emitir coordenadas de figuras, párrafos, secciones y referencias en TEI, una propiedad especialmente valiosa para trazabilidad. Está bajo Apache-2.0 y mantiene releases actuales. No debe asumirse que sus regiones de figura son el recorte visual óptimo.

**MinerU** tiene un pipeline activo y resultados competitivos en benchmarks de parsing, con OCR, fórmulas, tablas e interpretación de imágenes. Desde abril de 2026 usa una licencia propia basada en Apache-2.0: exige atribución visible para servicios online y licencia comercial por encima de determinados umbrales. Es un challenger técnico, no una dependencia por defecto.

**Marker** es activo y su código es Apache-2.0, pero los pesos principales tienen términos distintos y umbrales comerciales. Su tracker reciente contiene incidencias relevantes de pérdida o fabricación de contenido. Debe probarse en modo determinista y validar integridad página a página.

**Unstructured** es Apache-2.0 y útil como capa ETL multiformato. Su abstracción de elementos es cómoda, pero no está especializada en papers ni en figuras científicas; aporta más valor como conector/fallback que como núcleo.

**Nougat** convierte páginas científicas en markup y maneja bien fórmulas, pero sus pesos son CC BY-NC 4.0 y su foco no es recuperar figuras y coordenadas. Su código MIT no elimina la restricción de los pesos. No se recomienda para la ruta comercial.

**PyMuPDF** es rápido y funcional, pero el proyecto se distribuye bajo AGPLv3 o licencia comercial. No debe entrar accidentalmente en una distribución propietaria. [pikepdf](https://github.com/pikepdf/pikepdf), MPL-2.0, permite extracción lossless de imágenes incrustadas; [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) ofrece renderizado con licencias permisivas y es una alternativa más manejable para la capa PDF.

### 2. Extracción de figuras y captions

[PDFFigures 2.0](https://github.com/allenai/pdffigures2) sigue siendo el baseline abierto más específico: devuelve figura, caption, bounding boxes, identificador y texto interno, incluye datasets y scripts de evaluación y es Apache-2.0. Sus supuestos fueron ajustados sobre informática, no resuelve subfiguras y su último commit visible es de agosto de 2022. Se debe ejecutar como baseline aislado, no adoptar su arquitectura Scala como núcleo.

[DeepFigures](https://arxiv.org/abs/1804.02445) mostró el valor de etiquetas débilmente supervisadas a gran escala, pero su antigüedad y enfoque de detección no cubren el resto del pipeline. La idea reutilizable es generar etiquetas iniciales desde fuentes estructuradas y después auditar una muestra humana.

La mejor calidad visual requiere dos artefactos por figura cuando el PDF lo permita:

- imagen nativa extraída sin recodificación, que conserva resolución pero puede representar solo una parte del compuesto;
- recorte renderizado de la región completa, que conserva composición, texto vectorial y coordenadas.

Un reconciliador debe relacionar ambos, registrar transformaciones y elegir el artefacto de presentación sin perder el original.

### 3. Figuras multipanel

Este es el mayor vacío práctico. Los métodos clásicos basados en huecos y connected components siguen siendo útiles como baseline barato, pero fallan con paneles cosidos, solapados o sin separadores. ImageCLEF 2016 contiene 8.397 figuras multipanel anotadas y continúa apareciendo como referencia, aunque está sesgado a biomedicina.

[FigEx](https://github.com/Huang-AI4Medicine-Lab/FigEx) (EMNLP 2025) alinea subfiguras y subcaptions y publica BioSci-Fig y checkpoints. El repositorio no contiene una licencia explícita visible; por tanto, su código y pesos no se pueden integrar hasta aclarar términos. Sí puede orientar el diseño experimental.

[CompFigSep](https://github.com/GaetanLepage/compound-figure-separator) implementa segmentación, reconocimiento de etiquetas y separación de captions, pero es un proyecto académico pequeño de 2020 y no muestra una licencia reutilizable clara en la página principal. Es referencia, no dependencia.

Los trabajos más recientes, como FigEx2 y MaterialScope/MatSciFig en 2026, confirman que la combinación de detección visual, etiquetas de panel y subcaptions supera una separación puramente geométrica. Aun así, la generalización entre disciplinas debe medirse en un corpus propio.

### 4. Captions, menciones y contexto

GROBID puede enlazar marcadores y conservar coordenadas; JATS aporta identificadores explícitos cuando se dispone del XML editorial. Para PDF puro, la asociación fiable requiere:

1. normalizar variantes como `Fig. 2`, `Figure 2a`, `Figs. 2–4` y referencias suplementarias;
2. resolver cada mención al `figure_id` y, cuando sea posible, al `panel_id`;
3. recuperar el párrafo, encabezado de sección y vecindad documental;
4. puntuar contexto por mención explícita, distancia estructural, sección y similitud semántica;
5. conservar offsets, página, bounding boxes, parser y versión.

SciCap, SciCap+ y MetaSciCap muestran que captions, OCR y párrafos de mención aportan información distinta. No basta con usar el caption como consulta BM25 sobre chunks arbitrarios.

### 5. OCR y comprensión de charts

[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) es Apache-2.0, activo y cubre OCR, layout, tablas y fórmulas. Es el candidato open source principal para texto dentro de figuras y documentos escaneados. Tesseract/OCRmyPDF siguen siendo un baseline reproducible; OCRmyPDF es MPL-2.0.

Para charts, conviene separar percepción de razonamiento:

- OCR y localización de título, ejes, ticks, unidades, leyenda y etiquetas;
- estructura de series y relaciones color/forma;
- digitalización aproximada solo cuando la resolución lo permita;
- razonamiento multimodal condicionado por caption y contexto;
- verificación de cada valor contra evidencia visual o textual.

ChartQAPro incorpora preguntas no contestables y escenarios reales; ChartBench amplía tipos y razonamiento; SciVQA aporta 3.000 figuras científicas y 21.000 QA validadas; SPIQA incluye 270.000 preguntas intercalando texto, figuras y tablas. Ninguno sustituye un benchmark propio de grounding y procedencia.

### 6. Multimodal RAG y evidencia

La evidencia reciente favorece recuperar texto e imagen de forma coordinada. UniDoc-Bench reporta que la fusión texto-imagen supera rutas unimodales y embeddings conjuntos en su configuración. Un trabajo de 2026 sobre recuperación científica también encuentra que texto y representaciones intercaladas superan tratar todas las páginas solo como imágenes.

La unidad de recuperación recomendada no es la página ni un chunk ciego, sino un paquete de evidencia:

```text
EvidenceBundle
  question
  figure/panel image
  caption/subcaption
  explicit mentions
  section + selected paragraphs
  methods/results links
  provenance anchors
```

El generador debe devolver afirmaciones tipadas (`observed`, `author_stated`, `model_inference`, `uncertain`) con una o más evidencias. Un validador independiente rechaza referencias inexistentes, valores no observables y afirmaciones sin soporte.

### 7. Interfaces y productos

| Producto | Fortaleza visible | Carencia frente a la visión propuesta |
|---|---|---|
| [SciSpace Chat PDF](https://scispace.com/chat-pdf) | chat, resúmenes y respuestas enlazadas a secciones | no expone un modelo auditable de figuras/paneles ni evaluación reproducible |
| [Elicit](https://elicit.com/) | búsqueda, extracción estructurada, revisiones y citas a nivel de frase | optimiza síntesis de literatura, no inspección visual profunda de figuras |
| [NotebookLM](https://support.google.com/gemininotebook/answer/16215270?hl=en) | múltiples fuentes, chat fundamentado y artefactos de síntesis | no ofrece pipeline científico configurable ni métricas por componente |
| [Explainpaper](https://www.explainpaper.com/) | explicación directa de fragmentos seleccionados | foco textual y experiencia de lectura, no análisis estructurado de figuras |
| [Semantic Scholar](https://webflow.semanticscholar.org/product) | búsqueda, grafo de citas, figuras y Ask This Paper con supporting statements | cobertura limitada de QA y sin paneles/grounding visual fino para el usuario |

### Diferenciación defendible

La oportunidad no es otro chat con PDF. La diferenciación debe ser:

- figura y panel como objetos de primera clase;
- evidencia visible por afirmación, con overlay sobre PDF o figura;
- separación explícita entre observación, autor, inferencia e incertidumbre;
- comparación entre figuras y artículos con procedencia;
- benchmark reproducible y ficha de coste/latencia por configuración;
- ejecución local o privada para documentos sensibles;
- adaptadores de parser, OCR y modelos sin dependencia irreversible de un proveedor;
- exportación de resultados estructurados y auditables.

## Arquitectura recomendada en una frase

Un pipeline asíncrono, idempotente y orientado a artefactos que transforma cada fuente en un modelo documental normalizado con coordenadas y procedencia; deriva figuras, paneles, OCR y paquetes de evidencia; ejecuta análisis multimodal tipado; valida citas; y sirve los mismos objetos por API y UI.

El diseño detallado está en [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

## Decisiones que requieren validación experimental

| Decisión | Por qué no puede cerrarse solo con investigación | Experimento |
|---|---|---|
| Docling solo vs Docling + GROBID | la cobertura y errores pueden ser complementarios o redundantes | E01 |
| Mejor extractor visual | calidad varía con disciplina, PDF y composición | E01 |
| Marker/MinerU como fallback | coste GPU, integridad y términos de pesos/licencia | E01 + revisión legal |
| Estrategia multipanel | no existe un modelo general probado en todas las disciplinas | E02 |
| OCR por tipo de figura | el mejor motor depende de tamaño, idioma y modalidad | E03 |
| Índice textual, visual o híbrido | benchmarks recientes no garantizan resultado en nuestro corpus | E04 |
| Modelo multimodal y resolución | calidad, coste y privacidad cambian por proveedor | E05 |
| Validador basado en reglas o segundo modelo | trade-off entre coste y detección de alucinaciones | E06 |

## Fuentes primarias principales

- Docling: [repositorio](https://github.com/docling-project/docling), [arquitectura](https://docling-project.github.io/docling/concepts/architecture/), [paper](https://arxiv.org/abs/2501.17887), [changelog de servicio](https://github.com/docling-project/docling-serve/blob/main/CHANGELOG.md).
- GROBID: [repositorio](https://github.com/grobidOrg/grobid), [coordenadas PDF](https://github.com/grobidOrg/grobid/blob/master/doc/Coordinates-in-PDF.md).
- Extractores: [PDFFigures 2.0](https://github.com/allenai/pdffigures2), [Marker](https://github.com/datalab-to/marker), [MinerU](https://github.com/opendatalab/MinerU), [Unstructured](https://github.com/Unstructured-IO/unstructured), [Nougat](https://github.com/facebookresearch/nougat).
- Paneles: [FigEx](https://aclanthology.org/2025.findings-emnlp.899/), [SimCFS](https://pmc.ncbi.nlm.nih.gov/articles/PMC10112832/), [segmentación CCA](https://pmc.ncbi.nlm.nih.gov/articles/PMC6329596/).
- QA y charts: [SPIQA](https://proceedings.neurips.cc/paper_files/paper/2024/file/d74033a247989e8f6f3bf9e0c9629fb5-Paper-Datasets_and_Benchmarks_Track.pdf), [SciVQA](https://aclanthology.org/2025.sdp-1.18/), [ChartQA](https://aclanthology.org/2022.findings-acl.177/), [ChartQAPro](https://arxiv.org/abs/2504.05506), [ChartBench](https://chartbench.github.io/).
- Parsing y RAG: [OmniDocBench](https://github.com/opendatalab/OmniDocBench), [UNIDOC-BENCH](https://arxiv.org/abs/2510.03663), [MMDocRAG](https://proceedings.neurips.cc/paper_files/paper/2025/hash/1a93178950e92fd2e7b7448f7d68fd7d-Abstract-Datasets_and_Benchmarks_Track.html).
- Corpus: [PMC Open Access Subset](https://pmc.ncbi.nlm.nih.gov/about/userguide/), [copyright y descarga de PMC](https://pmc.ncbi.nlm.nih.gov/about/copyright/).

