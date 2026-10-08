# Roadmap por hitos verificables

> Este documento describe el camino completo hacia una versión rigurosa y robusta. Para el prototipo centrado en insertar un artículo y explicar sus figuras, véase [Etapas de implementación](IMPLEMENTATION_STAGES.md).

**Base de planificación:** una persona senior a tiempo completo y apoyo parcial de una persona experta/anotadora. Las duraciones son rangos orientativos, no compromisos. Una alpha rigurosa requiere aproximadamente 22–30 semanas; ampliar disciplinas, idiomas o escala cambia materialmente esa estimación.

## M0 — Cerrar descubrimiento y gobierno (1–2 semanas)

**Trabajo**

- Revisar con el propietario la prioridad de usuarios y la política de privacidad.
- Avisos de Apache-2.0 completados en `NOTICE` (titular: The Scientific Figure Intelligence Authors).
- Aprobar esquema inicial de Document IR, claims y evidence.
- Crear SBOM/registro de licencias y plantillas de experimentos.
- Congelar criterios y gates de E01.

**Salida:** ADR 0001–0004 revisados, schemas propuestos y checklist legal/seguridad.  
**Gate:** ninguna dependencia crítica sin licencia y versión registradas.

## M1 — Corpus y harness de evaluación (2–3 semanas)

**Trabajo**

- Seleccionar SFI-48 con manifiesto y licencias por item.
- Anotar `dev` y doble-anotar la muestra de acuerdo.
- Implementar validación del schema de anotaciones.
- Preparar runner común, métricas, manifests y reportes.
- Congelar `validation` y `test`.

**Tests:** schema, hashes, detección de duplicados/leakage y golden metric cases.  
**Salida:** corpus piloto legalmente trazable y benchmark reproducible.  
**Gate:** acuerdo humano mínimo definido en `research/experiments.md`.

## M2 — Benchmark de parsing/extracción E01 (2–3 semanas)

**Trabajo**

- Contenerizar Docling, GROBID y PDFFigures2.
- Añadir baseline pikepdf/pypdfium2.
- Ejecutar Marker/MinerU solo si la revisión de términos lo permite.
- Medir geometría, captions, integridad, velocidad, memoria y fallos.
- Publicar análisis de error por disciplina y tipo PDF.

**Tests:** contract tests por adaptador, corpus smoke tests y detección de pérdida silenciosa.  
**Salida:** reporte E01 y ADR de parser/extractor aceptado.  
**Gate:** alcanzar los umbrales o documentar por qué se necesita un ensemble.

## M3 — Núcleo documental y persistencia (2–3 semanas)

**Trabajo**

- Implementar Document IR y migraciones.
- Ingesta segura, hashing, object storage y provenance.
- Jobs idempotentes, reintentos, cache por config hash y estado observable.
- Reconciliador de parsers y extracción dual nativa/render.
- API interna para documentos, páginas, figuras y evidence anchors.

**Tests:** unitarios de geometría/IDs; integración con PostgreSQL/MinIO; reanudación; archivos corruptos.  
**Salida:** paper procesado a IR auditable.  
**Gate:** reprocesar el mismo input no duplica entidades y todas las figuras vuelven a su región fuente.

## M4 — Paneles y OCR, E02–E03 (3–4 semanas)

**Trabajo**

- Clasificador single/multipanel.
- Baseline geométrico y detector de paneles candidato.
- OCR de etiquetas, ejes, unidades, leyendas y scale bars.
- Matching panel-subcaption con confianza y fallback.
- Evaluar por modalidad y calibrar thresholds.

**Tests:** casos geométricos sintéticos, etiquetas rotadas, paneles cosidos y figuras sin etiquetas.  
**Salida:** figuras/paneles/elementos visuales versionados.  
**Gate:** E02/E03 y fallback seguro cuando la confianza es baja.

## M5 — Contexto e índices, E04 (2–3 semanas)

**Trabajo**

- Resolver menciones, rangos y referencias a paneles.
- Construir EvidenceBundle por pregunta/figura.
- Implementar lexical + dense text + late fusion.
- Comparar índice visual solo como challenger.
- Añadir filtros por sección, disciplina y tipo de figura.

**Tests:** variantes lingüísticas de `Fig.`, referencias múltiples, suplementos y secciones cruzadas.  
**Salida:** recuperación evaluada y explicable.  
**Gate:** Recall@5 y context precision mínimos; cada resultado incluye anchors.

## M6 — Análisis multimodal y grounding, E05–E06 (3–4 semanas)

**Trabajo**

- Adaptadores de al menos un modelo local y dos proveedores API, si presupuesto/privacidad lo permiten.
- Schemas de respuesta y claims tipados.
- Presupuestos, cache, rate limits y coste por run.
- Validador determinista de IDs/números y validador semántico challenger.
- QA sobre una y varias figuras, incluyendo no contestables.

**Tests:** contract/provider mocks, respuestas malformadas, evidencia ausente, citas inventadas e inyección en documentos.  
**Salida:** pipeline end-to-end con claims y citas.  
**Gate:** métricas de answerability, citation precision y unsupported claims.

## M7 — Experiencia de usuario y API pública (3–4 semanas)

**Trabajo**

- Upload/progreso/error recovery.
- Navegación paper–figura–panel.
- PDF.js con overlays y visor de figura con zoom/regiones.
- Panel de claims/evidence e inspección de la fuente.
- Comparación de figuras y exportación estructurada.
- Accesibilidad y pruebas con usuarios objetivo.

**Tests:** componentes, API, Playwright end-to-end, PDFs grandes y navegadores soportados.  
**Salida:** alpha utilizable.  
**Gate:** llegar de claim a evidencia en <=2 interacciones y completar tareas críticas sin asistencia.

## M8 — Hardening y despliegue demostrable (2–3 semanas)

**Trabajo**

- E07 seguridad: sandbox, SSRF, prompt injection, límites y malware.
- OpenTelemetry, dashboards, alertas y budgets.
- Docker Compose reproducible y entorno de demo.
- Backups, retención, borrado y recuperación.
- SBOM final, escaneo de dependencias y documentación de operación.

**Tests:** carga, chaos/failure recovery, backup restore y security regression suite.  
**Salida:** release candidate desplegable.  
**Gate:** cero vulnerabilidades críticas conocidas, restore probado y SLOs documentados.

## M9 — Validación externa e informe final (2–4 semanas)

**Trabajo**

- Evaluación ciega sobre `test`.
- Estudio con investigadores/analistas.
- Análisis de errores y sesgos por disciplina.
- Comparación calidad/coste/latencia.
- Informe de limitaciones, amenazas a validez y siguientes experimentos.

**Salida:** resultados reproducibles, demo, documentación técnica/usuario y backlog priorizado.  
**Gate:** no declarar terminado ningún componente que no haya pasado su prueba y revisión.

## Dependencias entre hitos

```text
M0 -> M1 -> M2 -> M3 -> M4 -> M5 -> M6 -> M7 -> M8 -> M9
             \-------- decisiones experimentales --------/
```

M3 puede preparar infraestructura en paralelo a E01, pero no debe fijar el parser antes del reporte. La UI puede prototiparse con fixtures del corpus desde M3, sin acoplarla a un output de proveedor.

## Backlog que no entra en la primera alpha

- entrenamiento fundacional propio;
- soporte universal de idiomas y tipos documentales;
- extracción automática de datos exactos de cualquier chart;
- grafo de conocimiento global de literatura;
- colaboración multiusuario avanzada;
- Kubernetes, multi-región y autoscaling complejo;
- conclusiones clínicas o decisiones automatizadas de alto riesgo.

## Registro de progreso

Cada hito debe cerrar con:

1. versión y cambios;
2. tests ejecutados;
3. métricas frente al baseline;
4. costes y latencia;
5. errores conocidos;
6. licencias/componentes nuevos;
7. ADR creado o actualizado;
8. decisión de avanzar, repetir o recortar alcance.

