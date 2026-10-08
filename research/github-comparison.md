# Comparativa de repositorios y herramientas

**Fecha de consulta:** 2026-10-06.  
**Criterio de actividad:** releases o commits recientes visibles en la fuente oficial; no se usa popularidad como sustituto de calidad.

## Matriz principal

| Proyecto | Propósito y arquitectura | Aprovechable | Actividad | Licencia relevante | Limitaciones y riesgo | Recomendación |
|---|---|---|---|---|---|---|
| [Docling](https://github.com/docling-project/docling) | Conversión multiformato a `DoclingDocument`; layout, tablas, OCR, pictures y pipelines extensibles | IR inicial, layout, reading order, imágenes/captions, servicio | Muy alta; `docling-serve` 1.36.0 el 2026-10-01 | Código MIT; modelos por separado | no está especializado en menciones científicas; gran superficie y versiones rápidas | **Candidato principal**, fijado por versión y comparado en E01 |
| [GROBID](https://github.com/grobidOrg/grobid) | Pipeline ML para papers a TEI: metadatos, secciones, referencias, figuras, tablas y callouts | estructura científica, TEI, coordenadas y enlaces | Alta; release 0.9.1 visible en 2026 | Apache-2.0; docs CC0; datos anotados CC BY | servicio Java; recortes visuales no siempre óptimos | **Complemento principal** de Docling, benchmark E01 |
| [PDFFigures 2.0](https://github.com/allenai/pdffigures2) | Heurísticas Scala/PDFBox ancladas en captions | figura/caption bbox, identificador, evaluación | Baja; último commit visible 2022-08-16 | Apache-2.0; revisar codecs opcionales | sesgo a informática, sin paneles, casos borde documentados | **Baseline**, no núcleo productivo |
| [Marker](https://github.com/datalab-to/marker) | Pipeline PDF a Markdown/JSON con Surya/VLM y postprocesado | parser challenger, OCR/layout, salida estructurada | Alta; cambios e incidencias en 2026 | Código Apache-2.0; pesos con licencia propia y umbrales | GPU/VRAM; issues recientes de pérdida/fabricación; pesos no equivalen a Apache | **Challenger E01**, no default hasta medir integridad |
| [MinerU](https://github.com/opendatalab/MinerU) | Pipelines híbridos y VLM para PDF/Office a Markdown/JSON | parsing complejo, OCR, fórmulas, tablas, charts | Muy alta; 3.4 en 2026-06 | Licencia propia basada en Apache-2.0; atribución online y umbrales comerciales | términos no OSI estándar; stack grande; benchmark propio | **Challenger E01** y revisión legal específica |
| [Unstructured](https://github.com/Unstructured-IO/unstructured) | ETL documental y particionado multiformato | conectores, fallback, ingestión general | Alta; release 0.27.8 visible en 2026-09 | Apache-2.0 | abstracción generalista, precisión de figuras no es su foco | Usar solo si conectores aportan valor |
| [Nougat](https://github.com/facebookresearch/nougat) | Transformer image-to-markup para páginas académicas | fórmulas y papers escaneados como referencia | Baja/moderada; repo estable, no evidencia de evolución rápida | Código MIT; pesos CC BY-NC 4.0 | no comercial, sin regiones de figura fiables, coste GPU | Solo experimento académico; **no ruta comercial** |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | binding de MuPDF para extracción/render | rendimiento, imágenes, texto y geometría | Alta | AGPLv3 o comercial | riesgo copyleft para producto propietario | No integrar sin decisión de licencia o contrato |
| [pikepdf](https://github.com/pikepdf/pikepdf) | acceso PDF/QPDF, extracción lossless de imágenes | originales incrustados, validación y normalización PDF | Alta | MPL-2.0; dependencias del wheel documentadas | una imagen PDF no equivale necesariamente a una figura completa | **Dependencia candidata** para artefactos nativos |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | binding de PDFium para renderizado | páginas/recortes reproducibles y permisivos | Alta | Apache-2.0/BSD-3-Clause; avisos de dependencias PDFium | API de bajo nivel para extracción semántica | **Candidato de renderizado** |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | OCR y document parsing con modelos especializados | texto, cajas, tablas, fórmulas y layouts | Muy alta; documentación 3.7+ en 2026 | Apache-2.0; comprobar pesos concretos | stack Paddle, tamaño y configuración por idioma | **Candidato OCR principal**, E03 |
| [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) | añade capa OCR a PDFs escaneados | preprocesado reproducible y baseline Tesseract | Alta; v17.12.1 visible en 2026-09 | MPL-2.0; dependencias externas | no comprende estructura; transforma el PDF | Fallback para escaneados, preservando original |
| [LayoutParser](https://github.com/Layout-Parser/layout-parser) | API y model zoo para document image analysis | estructuras bbox, visualización, baselines PubLayNet | Baja; sin releases visibles recientes | Apache-2.0; modelos/datasets aparte | dependencias antiguas/Detectron2, mantenimiento bajo | Referencia/API, no dependencia central |
| [PaperMage](https://github.com/allenai/papermage) | representación por capas para papers, sobre GROBID/VILA | ideas de entidades, capas y relaciones | Mantenimiento explícitamente limitado | Apache-2.0 | prototipo de investigación, dependencias fijadas antiguas | Adaptar ideas, no adoptar runtime |
| [FigEx](https://github.com/Huang-AI4Medicine-Lab/FigEx) | VLM + detector para subfigura/subcaption alineadas | diseño multipanel y dataset BioSci-Fig | Reciente; actualizado 2026-07 | **Sin licencia explícita visible** | 6 estrellas, 0 releases, dependencia de pesos LLaVA/YOLOS | Referencia y posible benchmark; **no copiar/integrar** |
| [CompFigSep](https://github.com/GaetanLepage/compound-figure-separator) | segmentación, labels y caption splitting | baseline especializado multipanel | Baja; proyecto académico 2020 | licencia no clara en la página oficial revisada | pequeño, antiguo y biomédico | Solo ideas/benchmark tras aclarar licencia |
| [SciVQA](https://github.com/esborisova/SciVQA) | dataset, baseline y evaluación de QA sobre figuras | 3.000 figuras/21.000 QA, preguntas no contestables | Dataset 2025, repo pequeño | Código MIT; verificar licencia de imágenes/dataset derivado | informática/CL; anotación inicial sintética validada | Benchmark externo, no único test |
| [SPIQA](https://github.com/google/spiqa) | QA multimodal sobre papers con imágenes, tablas y texto | 270k QA y evaluación contextual | Repo archivado 2026-03 | Código Apache-2.0; dataset CC BY 4.0 | sesgo a informática; archivado | Benchmark externo y fuente de rúbricas |

## Comparación para la decisión de parser

Escala cualitativa previa al benchmark: `++` fuerte, `+` útil, `0` parcial, `-` débil/no objetivo.

| Criterio | Docling | GROBID | PDFFigures2 | Marker | MinerU | Unstructured |
|---|---:|---:|---:|---:|---:|---:|
| Estructura científica | + | ++ | + | 0 | 0 | 0 |
| Figura + caption | + | + | ++ | + | + | 0 |
| Menciones/callouts | 0 | ++ | - | - | - | - |
| Coordenadas/procedencia | ++ | ++ | ++ | + | + | + |
| OCR/escaneados | + | - | - | ++ | ++ | + |
| Fórmulas/tablas | ++ | + | - | ++ | ++ | + |
| Calidad de mantenimiento | ++ | ++ | - | + | ++ | ++ |
| Licencia simple para producto | ++ | ++ | ++ | código sí/pesos no | no estándar | ++ |
| Coste operativo bajo | + | + | + | 0 | 0 | + |

**Hipótesis a probar:** Docling como parser de layout y artefactos + GROBID como parser científico ofrece más cobertura que cualquiera por separado. La fusión debe ocurrir en nuestro IR, no modificando sus modelos internos.

## Reutilización concreta

### Dependencias o servicios candidatos

- Docling, GROBID, pikepdf, pypdfium2, PaddleOCR y PDF.js, todos detrás de interfaces propias.
- SQLite y ficheros locales para el prototipo; PostgreSQL + pgvector y almacenamiento de objetos separados como objetivo desde M3.
- OCRmyPDF solo como job de normalización de escaneados, nunca reemplazando el original.

### Baselines aislados

- PDFFigures 2.0 para extracción.
- Tesseract/OCRmyPDF para OCR.
- heurísticas de huecos/connected components para paneles.
- BM25 y dense text retrieval para contexto.

### Solo ideas o evaluación

- PaperMage: modelo por capas y relaciones.
- FigEx: alineación conjunta panel-subcaption.
- CompFigSep y SimCFS: separación híbrida geométrica/detección.
- Marker/MinerU hasta cerrar benchmark y licencias de pesos.

## Riesgos de dependencia

1. **Cambio de licencia o pesos:** fijar hashes, conservar avisos y bloquear upgrades automáticos de componentes ML.
2. **Deriva de salida:** guardar versión/configuración y validar cada salida contra JSON Schema.
3. **Parser único:** mantener al menos un baseline alternativo y capacidad de reprocesado.
4. **GPU implícita:** medir CPU, GPU, memoria, cold start y throughput antes de adoptar VLM parsers.
5. **Repositorios académicos pequeños:** no incluir código sin licencia ni convertir un checkpoint experimental en dependencia crítica.
6. **Métricas del proveedor:** ejecutar todos los candidatos sobre el mismo corpus y configuración de renderizado.

