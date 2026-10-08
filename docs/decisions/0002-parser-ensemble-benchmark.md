# ADR 0002 — Seleccionar parser mediante benchmark y permitir ensemble

- **Estado:** aceptada como método (2026-10-07). E01 solo ha medido la línea base propia ([ADR 0005](0005-pdfium-heuristic-baseline-extractor.md)); comparar al menos un candidato (Docling o GROBID) sigue pendiente antes de consolidar el extractor.
- **Fecha:** 2026-10-06

## Contexto

Docling sobresale como parser general mantenido; GROBID ofrece estructura específicamente científica; PDFFigures2 es un baseline especializado pero inactivo. La calidad real depende del corpus.

## Alternativas

- Docling solo.
- GROBID solo.
- PDFFigures2 como extractor principal.
- Docling + GROBID reconciliados, con capa PDF nativa.

## Decisión propuesta

Ejecutar E01 antes de aceptar la selección. La hipótesis preferida es Docling + GROBID + pikepdf/pypdfium2, con PDFFigures2 como baseline. Marker y MinerU entran como challengers condicionados por licencias y recursos.

## Consecuencias

- evita dependencia prematura;
- aumenta coste de operación si el ensemble se confirma;
- requiere reconciliación explícita y contract tests;
- permite usar solo un parser en modo económico si los datos muestran poca pérdida.

## Criterio de aceptación

Métricas y gates de E01 en `research/experiments.md`, incluido cero pérdida silenciosa.

