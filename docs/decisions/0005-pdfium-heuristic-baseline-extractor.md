# ADR 0005 — Extractor de referencia propio sobre pdfium para el prototipo

**Estado:** aceptada para las etapas 1–4; se revisará con el resultado de E01.
**Fecha:** 2026-10-06.

## Contexto

La etapa 1 necesita extraer figuras y pies de PDFs reales con trazabilidad completa. El [ADR 0002](0002-parser-ensemble-benchmark.md) establece que el parser definitivo (Docling, GROBID, PDFFigures2 o un ensemble) se elige mediante el benchmark E01 sobre SFI-48, que aún no existe. Bloquear el prototipo hasta entonces retrasaría todas las etapas siguientes.

Restricciones:

- licencias compatibles con Apache-2.0 (PyMuPDF queda excluido por AGPL);
- sin servicios externos ni dependencias pesadas (Java, PyTorch) en el prototipo;
- soporte de PDFs escaneados;
- salida con coordenadas, procedencia y avisos explícitos.

## Alternativas consideradas

1. **Integrar ya Docling o GROBID.** Son más completos, pero añaden modelos o servicios pesados antes de saber si mejoran el resultado en nuestro corpus. Elegir uno ahora anticiparía la decisión de E01.
2. **Usar solo las imágenes incrustadas** (pikepdf). No sirve para figuras vectoriales, figuras troceadas en teselas ni escaneados, y no asocia pies.
3. **Extractor heurístico propio sobre pypdfium2** (Apache-2.0/BSD) detrás del contrato `FigureExtractor`.

## Decisión

Opción 3. `PdfiumFigureExtractor` (`src/sfi/extract/`) es el extractor del prototipo y la **línea base** que los candidatos de E01 deberán superar. Docling, GROBID y PDFFigures2 se integrarán como implementaciones del mismo protocolo `FigureExtractor` y se compararán sobre el mismo corpus con `scripts/eval/`.

## Evidencia

En el piloto SFI-12 (173 páginas, 77 figuras): 77/77 figuras con región y pie, 98,7 % de precisión y 66/67 pies con similitud ≥ 0,9 frente a JATS, a unos 50 ms por página ([informe](../reports/stage1-extraction.md)).

## Consecuencias y riesgos

- Las heurísticas se han calibrado sobre 12 artículos; pueden no generalizar a otras maquetaciones. Mitigación: umbrales en `RegionConfig`, incluidos en el hash de configuración de cada ejecución, y evaluación reproducible.
- Sin cajas de referencia todavía, la calidad geométrica solo se ha revisado visualmente.
- El texto de los escaneados depende de la capa OCR existente; un OCR propio se evaluará en E03.
- Cambiar de extractor no afecta al resto del sistema: el pipeline y la persistencia solo dependen del contrato.
