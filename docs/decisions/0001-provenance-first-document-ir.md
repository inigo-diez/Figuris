# ADR 0001 — Modelo documental orientado a procedencia

- **Estado:** aceptada (2026-10-07). Implementada desde la etapa 1: documentos, ejecuciones, figuras, pasajes y análisis versionados, con coordenadas y procedencia; la capa de evidencia (tokens de texto de las figuras) sigue el mismo modelo.
- **Fecha:** 2026-10-06
- **Responsable:** proyecto Scientific Figure Intelligence

## Contexto

El sistema combinará parsers, OCR y modelos con errores distintos. La interfaz debe llevar cada afirmación a una región verificable del documento y permitir reprocesar con nuevas versiones.

## Alternativas

1. Adoptar directamente el modelo de Docling.
2. Adoptar TEI de GROBID como modelo interno.
3. Guardar solo Markdown + imágenes.
4. Definir un IR propio y conservar outputs nativos de cada herramienta.

## Decisión propuesta

Usar un IR propio y tipado con entidades, coordenadas, hashes, productor/versión/configuración y relaciones `Claim -> Evidence`. Conservar en object storage todos los outputs crudos de parsers.

## Evidencia

Docling ofrece un modelo general rico; GROBID ofrece estructura científica y coordenadas/callouts. Ninguno cubre por sí solo claims, paneles, múltiples candidatos y auditoría de modelos.

## Consecuencias

- mayor trabajo inicial de schemas y reconciliación;
- independencia de proveedor y reprocesado seguro;
- trazabilidad y evaluación por componente;
- necesidad de migraciones de schema versionadas.

## Validación

M2/M3: demostrar que una figura, panel, caption, mention y claim pueden volver al PDF y al output de productor sin pérdida.

