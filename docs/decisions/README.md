# Architecture Decision Records

Crear un archivo por decisión con el formato `NNNN-titulo.md`.

Cada ADR debe contener:

- Estado: propuesta, aceptada, sustituida o rechazada.
- Contexto y requisitos.
- Alternativas consideradas.
- Evidencia experimental.
- Decisión.
- Consecuencias y riesgos.
- Fecha y responsables.

Decisiones iniciales previstas:

- parser documental;
- extractor de figuras;
- segmentación multipanel;
- OCR;
- proveedor o estrategia multimodal;
- almacenamiento e índices;
- orquestación;
- interfaz y despliegue.

## ADR actuales

- [0001 — Modelo documental orientado a procedencia](0001-provenance-first-document-ir.md)
- [0002 — Seleccionar parser mediante benchmark y permitir ensemble](0002-parser-ensemble-benchmark.md)
- [0003 — Adaptadores propios y sin framework agente inicial](0003-provider-neutral-models-no-agent-framework.md)
- [0004 — SQLite local primero; PostgreSQL + object storage + pgvector desde M3](0004-storage-postgres-object-pgvector.md)
- [0005 — Extractor de referencia propio sobre pdfium para el prototipo](0005-pdfium-heuristic-baseline-extractor.md)
- [0006 — Aplicación web local: FastAPI y frontend sin compilación](0006-local-web-app-fastapi-buildless-frontend.md)
- [0007 — Capa de evidencia: texto de las figuras con RapidOCR](0007-ocr-evidence-layer.md)

