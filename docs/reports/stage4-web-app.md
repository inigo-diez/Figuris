# Etapa 4 — Aplicación utilizable

**Fecha:** 2026-10-06 · **Decisión de arquitectura:** [ADR 0006](../decisions/0006-local-web-app-fastapi-buildless-frontend.md)

## Resultado

La aplicación web local funciona de principio a fin. Se suben uno o varios PDF, se sigue el progreso, se navega entre las figuras y cada explicación se ve junto a la imagen, su pie y la evidencia que la respalda, con un clic para llegar al párrafo citado resaltado en su página.

```bash
pip install -e .
sfi serve --open        # http://127.0.0.1:8000
```

El criterio de finalización («una persona ajena al desarrollo puede cargar un artículo, localizar una figura y entender la explicación sin ayuda») **queda pendiente de una prueba con alguien ajeno al proyecto**. Lo verificado hasta ahora es técnico: la prueba automática en navegador y la revisión de las pantallas.

| Requisito de la etapa | Cómo se cumple |
|---|---|
| Pantalla para cargar el artículo | arrastrar y soltar o elegir archivos (varios a la vez). Los PDF no válidos se rechazan antes de encolarlos, con el motivo en español (vacío, no es PDF, dañado, protegido con contraseña, demasiado grande o con demasiadas páginas) |
| Progreso y errores recuperables | estado del trabajo (en cola, extrayendo, explicando *n/N* figuras, completado o error) con barra de progreso. Los avisos indican qué falta y cómo resolverlo: sin clave de OpenAI, presupuesto agotado, figuras con error o explicaciones no fiables. Con «Reprocesar» solo se paga lo que falte |
| Navegar entre figuras | cuadrícula con miniatura, página, estado y resumen. En la vista de figura, «Anterior/Siguiente» y las flechas del teclado; `Esc` vuelve al documento |
| Imagen, pie, explicación y evidencia en una vista | dos columnas: visor y pie a la izquierda, explicación a la derecha. Cada afirmación lleva su tipo (observado, según los autores, inferencia, incierto) con una leyenda para no especialistas, y botones de fuente: «Figura», «Pie» o «Texto · p. 5 · Results» |
| Zoom y enlace a la página original | zoom con rueda, botones o doble clic, arrastre para desplazarse y ajuste a la ventana. La pestaña «Página N» muestra la página con la figura, el pie y los pasajes citados resaltados; al pulsar una cita se salta a su página y se encuadra el párrafo. El PDF original se abre en la página exacta |
| No repetir análisis costosos | la caché por contenido de las etapas 2 y 3: volver a subir el mismo PDF, o uno con las mismas figuras, cuesta 0 USD |

## Verificación

- **96 tests** (10 de la aplicación web), sin red. Cubren subida, validación, trabajo completo con un modelo simulado, imágenes de figura y página, PDF original, reprocesado sin coste nuevo, que no se pueda encolar dos veces el mismo documento, el funcionamiento sin clave de OpenAI, la reanudación tras un reinicio y que se conserve el nombre del archivo subido.
- **Prueba en navegador** (Chrome sin interfaz, guion fuera del repositorio) sobre los datos reales del piloto:
  - subida con progreso;
  - cuadrícula de figuras;
  - vista de figura;
  - clic en «Texto · p. 5 · Results», que lleva a la página 5 con el párrafo resaltado;
  - zoom, navegación con teclado y aviso «no fiable»;
  - sin errores de consola ni peticiones fallidas;
  - sin desplazamiento horizontal a 390 px de ancho;
  - modo oscuro.
- **Prueba real con un artículo nuevo** (PMC8448759, CC BY, reserva del piloto): subido desde la interfaz, extraído y explicado con `gpt-6-luna` por 0,0042 USD sus 3 figuras. Una segunda subida del mismo PDF se completó en 2 s desde la caché.

La prueba en navegador encontró tres errores, ya corregidos con su test:

1. Al reprocesar se podía encolar dos veces el mismo documento, porque el trabajo aún no tenía documento asociado.
2. El documento mostraba el nombre del archivo temporal en lugar del nombre subido.
3. Aparecía el texto «null» en documentos procesados desde la línea de comandos, porque no tenían trabajo web asociado.

## Diseño

```text
navegador ──► FastAPI (127.0.0.1)
                ├─ POST /api/documents        validar → guardar → encolar (202)
                ├─ GET  /api/jobs/{id}        estado y progreso (el cliente consulta cada 1,5 s)
                ├─ GET  /api/documents[/{id}] documentos, figuras, estado del análisis
                ├─ GET  /api/documents/{id}/figures/{fid}   explicación, citas localizadas, pasajes
                ├─ GET  /api/figures/{fid}/image · /api/documents/{id}/pages/{n} · /pdf
                └─ POST /api/documents/{id}/reprocess
              trabajador (hilo) ──► cola en SQLite ──► extracción (etapas 1 y 3) ──► análisis (etapas 2 y 3)
```

- **Seguridad:** solo escucha en localhost. El texto de los PDF se inserta con `textContent`, nunca como HTML. La política de contenido limita los scripts y estilos al propio origen, y se valida el PDF antes de procesarlo.
- **Robustez:** cola persistente; los trabajos interrumpidos se reanudan al arrancar y un error en un trabajo no detiene al trabajador. SQLite usa WAL y una conexión por petición.
- **Sin dependencias de frontend:** HTML, CSS y JS sin compilación (~800 líneas). Funciona sin conexión, salvo las llamadas al modelo.

## Limitaciones conocidas

1. **Falta la prueba de usabilidad con usuarios reales**, que es el criterio de la etapa.
2. **Un documento a la vez.** Dentro de cada documento las figuras se explican en paralelo; varios PDF esperan en la cola.
3. **Progreso por consulta periódica**, sin SSE ni WebSocket. Suficiente en local.
4. **Sin autenticación ni varios usuarios.** No debe exponerse en red tal cual.
5. **Visor de páginas como imagen** (150 ppp). El texto de la página no se puede seleccionar; para eso está el PDF original.
6. **Paneles sin coordenadas.** «Figura · panel A» lleva a la figura completa, no al panel (etapa 5).
7. **No se puede borrar documentos** desde la interfaz.

## Siguiente paso

Probar la aplicación con dos o tres personas ajenas al proyecto, con una tarea concreta: cargar un artículo, encontrar una figura y explicar qué muestra. Después, etapa 5: precisión y trazabilidad (paneles, OCR de ejes, confianza calibrada, evaluación frente a anotaciones humanas).
