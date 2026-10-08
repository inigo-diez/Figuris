# Plan de investigación

**Estado 2026-10-06:** revisión inicial completada. Entregables: [landscape](../research/landscape.md), [comparativa](../research/github-comparison.md), [licencias](../research/license-inventory.md), [experimentos](../research/experiments.md) y [fuentes](../research/sources.md). La ejecución experimental sigue pendiente.

## Preguntas principales

1. ¿Qué herramienta recupera mejor layout, figuras, captions y referencias cruzadas en PDFs científicos?
2. ¿Cómo segmentar de forma fiable figuras multipanel?
3. ¿Qué combinación de OCR y modelo multimodal reconoce mejor ejes, unidades, leyendas y tendencias?
4. ¿Cómo asociar una figura con todos los fragmentos relevantes sin introducir contexto irrelevante?
5. ¿Qué representación permite buscar y comparar figuras textual y visualmente?
6. ¿Cómo producir citas verificables y detectar afirmaciones no sustentadas?

## Búsqueda obligatoria

Investigar repositorios, documentación oficial y papers sobre:

- extracción de figuras y parsing científico;
- detección de layout y segmentación multipanel;
- chart understanding y chart question answering;
- scientific figure understanding;
- document intelligence y multimodal RAG;
- OCR científico;
- interfaces de exploración de papers;
- datasets y benchmarks relevantes.

Incluir herramientas como GROBID, Docling, Marker, Nougat, PyMuPDF, PDFFigures 2.0, LayoutParser y Unstructured, además de alternativas actuales encontradas durante la búsqueda.

## Ficha por alternativa

- Nombre, enlace y propósito.
- Arquitectura y tecnologías.
- Actividad y mantenimiento reciente.
- Calidad observable y cobertura funcional.
- Licencia y obligaciones.
- Posible modalidad de uso: dependencia, servicio, fork, módulo o inspiración.
- Limitaciones, riesgo de dependencia y coste operacional.
- Experimento necesario para validarla.

## Entregables

- `research/landscape.md`: estado del arte y productos comparables.
- `research/github-comparison.md`: tabla comparativa de repositorios.
- `research/license-inventory.md`: inventario de licencias.
- `research/experiments.md`: pruebas comparativas propuestas y resultados.
- ADRs con las decisiones finales.

## Regla de decisión

No elegir componentes críticos solo por popularidad o facilidad de integración. Compararlos sobre el mismo corpus representativo y conservar resultados, versiones, configuración, latencia y coste.

