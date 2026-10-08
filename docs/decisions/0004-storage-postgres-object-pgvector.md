# ADR 0004 — SQLite local primero; PostgreSQL + object storage + pgvector desde M3

- **Estado:** aceptada para implementación incremental
- **Fecha:** 2026-10-06

## Contexto

Se necesitan blobs grandes, relaciones auditables, filtros, jobs, JSON versionado y búsqueda vectorial. Operar una base documental, otra de grafos y otra vectorial desde el inicio aumentaría complejidad.

## Alternativas

- todo en filesystem/SQLite;
- PostgreSQL + S3/MinIO + pgvector;
- base vectorial dedicada + grafo + object storage.

## Decisión

Durante las etapas 0–2 se usarán SQLite y ficheros locales, siempre detrás de interfaces de persistencia y almacenamiento. No se levantará Docker Compose para el primer prototipo.

Desde M3 se migrará, si las métricas o el uso multiusuario lo justifican, a S3/MinIO para originales/derivados, PostgreSQL para entidades/relaciones/jobs y pgvector para embeddings. Redis será efímero y opcional. Se añadirán sistemas especializados solo cuando el volumen o E04 lo exijan.

## Consecuencias

- puesta en marcha y depuración más rápidas para el prototipo;
- la migración exige mantener contratos de repositorio y pruebas desde el inicio;
- operación transaccional y multiusuario disponible al avanzar a M3;
- posibilidad de migrar índices manteniendo el IR;
- pgvector puede no ser óptimo a gran escala, riesgo aceptado hasta medir volumen/latencia.

