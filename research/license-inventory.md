# Inventario de licencias y reutilización

**Fecha de revisión:** 2026-10-06.  
**Aviso:** inventario técnico, no asesoramiento jurídico. Antes de distribución comercial se requiere revisión legal del conjunto exacto de versiones, wheels, pesos, datasets y documentos.

## Política de decisión

- Código, pesos, datos, documentos fuente y contenido generado se registran por separado.
- Sin licencia explícita no se copia, instala como dependencia distribuida ni incorpora un checkpoint.
- Una licencia permisiva del repositorio no se extiende automáticamente a modelos descargados.
- Los PDFs y figuras conservan la licencia del artículo; estar accesibles en internet no concede reutilización.
- Cada artefacto del corpus incluye `source_url`, `retrieved_at`, `license_id`, `license_url`, atribución y hash.

## Software y modelos

| Componente | Licencia verificada | Uso admisible propuesto | Obligaciones/riesgo | Decisión inicial |
|---|---|---|---|---|
| Docling | MIT para código; modelos individualmente licenciados | dependencia o servicio fijado | incluir licencia; inventariar cada peso | Apto condicionado |
| GROBID | Apache-2.0; docs CC0; datos anotados CC BY | contenedor/servicio | NOTICE/atribución; separar datos | Apto |
| PDFFigures 2.0 | Apache-2.0 | baseline o servicio aislado | codecs opcionales tienen licencias propias | Apto condicionado |
| Marker | Apache-2.0 para código; pesos bajo licencia Datalab/AI Pubs OpenRAIL modificada | benchmark; posible servicio | términos y umbrales de pesos, atribución | Condicionado; no redistribuir aún |
| MinerU | MinerU Open Source License, basada en Apache-2.0 | benchmark; posible servicio | atribución visible online; licencia separada >100M MAU o >USD20M ingresos mensuales consolidados | Condicionado/no OSI estándar |
| Unstructured | Apache-2.0 | dependencia para conectores/fallback | revisar extras y modelos transitivos | Apto condicionado |
| Nougat | código MIT; pesos CC BY-NC 4.0 | investigación no comercial | pesos excluyen uso comercial | No para ruta comercial |
| PyMuPDF | AGPLv3 o licencia comercial | herramienta separada solo si se acepta AGPL o se compra licencia | copyleft fuerte/contrato | Excluir por defecto |
| pikepdf | MPL-2.0; wheels incluyen licencias de terceros documentadas | dependencia para imágenes nativas | cambios a archivos MPL bajo MPL; distribuir avisos de wheel | Apto condicionado |
| pypdfium2 | Apache-2.0/BSD-3-Clause; PDFium y dependencias con avisos propios | renderizado | conservar licencias del build exacto | Apto condicionado |
| PaddleOCR | Apache-2.0; verificar cada modelo | OCR local/servicio | pesos y dependencias por versión | Apto condicionado |
| OCRmyPDF | MPL-2.0; contenido no código puede variar | job de OCR | conservar MPL y licencias externas | Apto condicionado |
| LayoutParser | Apache-2.0 | utilidades o baseline | modelos y datasets por separado | Apto condicionado |
| PaperMage | Apache-2.0 | ideas o prototipo | mantenimiento limitado y dependencias antiguas | No runtime principal |
| FigEx | sin licencia explícita visible en el repo revisado | leer paper/evaluar outputs si términos lo permiten | ausencia de permiso para reutilizar código; pesos base con términos propios | **No integrar/copiar** |
| CompFigSep | licencia no clara en la revisión inicial | solo referencia conceptual | pedir aclaración antes de ejecutar/distribuir | **No integrar/copiar** |
| PDF.js | Apache-2.0 | visor web adaptado | licencia y avisos; Mozilla pide personalizar el viewer embebido | Apto |
| OpenSeadragon | BSD-3-Clause | zoom de figuras de alta resolución | conservar avisos | Apto |
| PostgreSQL/pgvector | PostgreSQL License | persistencia e índice vectorial | conservar licencia | Apto |
| IBM Plex Sans | SIL OFL 1.1 | tipografía de la interfaz, incluida en `src/sfi/web/static/fonts/` | distribuir con su licencia (`OFL-ibm-plex-sans.txt`); no vender la fuente sola | Apto |
| Source Serif 4 | SIL OFL 1.1 | tipografía editorial de la interfaz, incluida en `static/fonts/` | distribuir con su licencia (`OFL-source-serif-4.txt`) | Apto |
| Lucide (lucide-static 1.53.0) | ISC | iconos de la interfaz, copiados en `static/icons.js` | conservar el aviso ISC, que va en la cabecera de `icons.js` | Apto |

## Datasets y benchmarks

| Dataset/fuente | Términos observados | Uso propuesto | Precaución |
|---|---|---|---|
| PMC Open Access Subset | cada artículo conserva una licencia de reutilización; filtrar por licencia | corpus propio CC BY/CC0 y JATS | descargar solo por canales autorizados de PMC; conservar licencia por artículo |
| arXiv | licencia por submission, no uniforme | papers adicionales cuando la licencia permita redistribución | no asumir que todos son CC BY; guardar solo URL/ID si no hay permiso |
| PDFFigures2 evaluation | código/anotaciones en repo Apache-2.0; distribuye URLs, no PDFs, por copyright | baseline reproducible | resolver URLs y respetar licencia de cada paper |
| PubLayNet | anotaciones CDLA-Permissive-1.0; imágenes sujetas a PMC OA | layout externo | preservar atribución y licencias de imágenes |
| DocLayNet | CDLA-Permissive-1.0 | layout externo | conservar atribución/avisos y cambios |
| OmniDocBench | declaración de uso solo para investigación/no comercial | evaluación interna de parsers | no redistribuir ni usar como corpus comercial |
| SPIQA | dataset CC BY 4.0; código Apache-2.0 | benchmark de QA | atribución; repo archivado desde 2026-03 |
| SciVQA | repo MIT; imágenes derivadas de ACL-Fig/SciGraphQA | benchmark de QA | verificar términos del dataset HF y de imágenes antes de redistribuir |
| SciGraphQA | research-only y sujeto además a acuerdos de Palm-2/LLaMA/GPT-4 según el repo | investigación comparativa | no incorporar a producto/corpus comercial |
| ChartQA/ChartQAPro | licencia del repo/dataset debe verificarse en el artefacto exacto | benchmark de charts | fuentes originales pueden tener derechos diferentes |
| BioSci-Fig/FigEx | no se localizó licencia explícita en el repo | solo evaluar después de aclaración | no descargar/incorporar a corpus distribuido sin términos |
| ImageCLEF compound figures | términos por edición/tarea | benchmark de paneles si se obtiene legalmente | normalmente investigación; comprobar acuerdo concreto |

## Registro de componentes

Antes de añadir una dependencia, crear una fila en el SBOM/registro con:

```yaml
name: docling
version: exact-version-or-commit
source: https://github.com/docling-project/docling
artifact_type: code | model | dataset | document
license_spdx: MIT
license_url: ...
usage: parser-service
distribution: container | linked-library | internal-only
modifications: none
notices: path/to/NOTICE
reviewed_at: 2026-10-06
reviewer: project-maintainer
```

## Fuentes de licencia

- [Docling](https://github.com/docling-project/docling), [GROBID](https://github.com/grobidOrg/grobid), [PDFFigures2](https://github.com/allenai/pdffigures2/blob/master/LICENSE.txt).
- [Marker code y términos de pesos](https://github.com/datalab-to/marker), [MinerU License](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md).
- [Nougat code/pesos](https://github.com/facebookresearch/nougat), [PyMuPDF](https://github.com/pymupdf), [pikepdf third-party notices](https://github.com/pikepdf/pikepdf/blob/main/third-party-licenses/README.md), [pypdfium2 licensing](https://github.com/pypdfium2-team/pypdfium2/blob/main/README.md#licensing).
- [DocLayNet](https://github.com/DS4SD/DocLayNet/blob/main/LICENSE), [PubLayNet](https://github.com/ibm-aur-nlp/PubLayNet/blob/master/LICENSE.md), [SPIQA dataset](https://huggingface.co/datasets/google/spiqa), [PMC copyright](https://pmc.ncbi.nlm.nih.gov/about/copyright/).

