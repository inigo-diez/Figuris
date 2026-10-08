# ADR 0006 — Aplicación web local: FastAPI y frontend sin compilación

**Estado:** aceptada para la etapa 4; se revisará al empezar M3 (interfaz de producto).
**Fecha:** 2026-10-06.

## Contexto

La etapa 4 pide una aplicación web local que una persona ajena al desarrollo pueda usar para cargar un PDF, seguir el progreso y entender las explicaciones. [ARCHITECTURE.md](../ARCHITECTURE.md) propone para el producto una API Python tipada (FastAPI como candidata) y una interfaz React/TypeScript con PDF.js y OpenSeadragon.

Restricciones del prototipo:

- quien lo ejecuta solo debería necesitar Python. La máquina de desarrollo no tiene Node, y exigirlo añade una cadena de compilación;
- debe funcionar sin conexión, salvo las llamadas al modelo;
- el texto de los PDF no es de fiar: la interfaz no puede interpretarlo como HTML;
- los análisis cuestan dinero: un reinicio no puede perder trabajo ni repetir gasto.

## Alternativas consideradas

1. **React/TypeScript con Vite ya en la etapa 4.** Es el destino previsto, pero obliga a instalar Node y a compilar el frontend, y fija decisiones de UI antes de validar el flujo con usuarios.
2. **Plantillas en el servidor (Jinja + htmx).** No necesita compilación, pero mezcla presentación y API; un cliente React posterior tendría que rehacer los endpoints.
3. **API JSON con FastAPI y un cliente estático sin compilación** (HTML, CSS y JavaScript modernos, sin dependencias externas).

## Decisión

Opción 3.

- **API** (`src/sfi/web/app.py`): FastAPI, JSON tipado y OpenAPI en `/docs`. Es el contrato estable que un cliente React podrá consumir sin cambios en el backend.
- **Cliente** (`src/sfi/web/static/`): un único archivo JS sin librerías. El texto procedente de PDF se inserta siempre con `textContent`, y la cabecera `Content-Security-Policy` limita los scripts y estilos al propio origen.
- **Visor:** las páginas se renderizan con pdfium en el servidor (150 ppp, en caché) y se muestran con zoom y desplazamiento propios, con capas para la región de la figura, el pie y los pasajes citados. PDF.js no es necesario para ver una página y resaltar cajas; el PDF original sigue accesible en el visor del navegador (`#page=N`).
- **Trabajos:** cola persistente en SQLite con un solo trabajador en segundo plano. Los trabajos que estaban en curso al reiniciar se vuelven a encolar; son idempotentes porque la extracción y las explicaciones están en caché por contenido. SQLite usa WAL, y cada petición abre su propia conexión.
- **Despliegue:** `sfi serve`, escuchando solo en `127.0.0.1` por defecto.

## Consecuencias

- La instalación sigue siendo `pip install -e .`; no hace falta Node.
- El cliente es pequeño (~600 líneas) y sin compilación. Si crece (comparación de versiones, edición de anotaciones), conviene migrarlo a React/TypeScript manteniendo la API.
- Un solo trabajador procesa los documentos de uno en uno; dentro de cada documento las figuras se explican en paralelo (`SFI_ANALYSIS_CONCURRENCY`). La cola con Redis o los workers separados quedan para M3, según la [ADR 0004](0004-storage-postgres-object-pgvector.md).
- Sin autenticación: la aplicación es local y monousuario. Exponerla en red requiere autenticación, límites por usuario y almacenamiento de objetos.

## Revisión del 2026-10-08: interfaz Figuris

La interfaz se rediseñó con la identidad **Figuris** (logo en [docs/brand/](../brand/)). Se mantiene **sin compilación**: el encargo proponía React, TypeScript y Tailwind, pero la máquina sigue sin Node y la API ya cubre lo necesario. Pasar a React costaría una cadena de compilación sin añadir nada que el usuario vea.

- **Estructura:** barra lateral, barra superior con ruta, buscador y estado, y un espacio de trabajo por documento con tres paneles redimensionables: miniaturas de página, la página con las regiones detectadas y los detalles de la figura seleccionada. Hay además una galería en cuadrícula o lista con selección múltiple.
- **Archivos:** `app.js` (utilidades, armazón y visor), `pages.js` (inicio, documentos, procesamiento y configuración), `workspace.js` (espacio de trabajo), `figure.js` (explicación) y `review.js` (revisión, sin cambios funcionales).
- **Recursos locales, sin CDN:** IBM Plex Sans y Source Serif 4 (OFL) e iconos Lucide (ISC), copiados en `static/`. La política CSP sigue permitiendo solo el propio origen.
- **API nueva:** miniaturas de página (`?thumb=1`), descarga de la imagen de una figura (`?download=1`) y exportación JSON de un documento o de las figuras elegidas (`/api/documents/{id}/export`).
- **Lo que el encargo pedía y no se ha hecho, porque el sistema no lo tiene:** proyectos, historial de exportaciones, perfil de usuario, detección de tablas y corrección de regiones fuera de la pestaña Revisión. Los filtros por tipo usan la clasificación de la explicación (gráficos, imágenes, diagramas), no un detector de tablas.
