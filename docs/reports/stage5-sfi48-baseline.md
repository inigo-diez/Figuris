# Etapa 5 (en curso) — SFI-48 y primera medición

**Fecha:** 2026-10-07 · **Extractor:** `pdfium-heuristic` 0.2.0 · **Referencia:** `reference/0.1` · **Evaluado:** `dev` + `validation` (24 artículos, 150 figuras); `test` congelado y sin evaluar

## Qué se ha hecho

1. **Protocolo de la prueba de usabilidad** de la etapa 4 ([USABILITY_TEST.md](../USABILITY_TEST.md)), listo para cuando haya participantes.
2. **SFI-48:** 48 artículos CC BY de seis disciplinas, seleccionados con búsquedas fijas y una semilla, y divididos en 12 `dev`, 12 `validation` y 24 `test` antes de procesarlos ([data/sfi48](../../data/sfi48/README.md)).
3. **Referencia automática** construida con datos de PMC y no con la salida del sistema: etiquetas, pies y menciones del JATS, más página y caja obtenidas localizando en el PDF la imagen publicada de cada figura. 249 de 292 figuras quedan localizadas con buena coincidencia; el resto está pendiente de revisión humana.
4. **Evaluación** (`scripts/eval/sfi48_eval.py`) con las métricas del plan que ya se pueden medir: intervalos de confianza por bootstrap sobre artículos, desglose por estrato y registro obligatorio si se evalúa `test`.
5. **Primera mejora:** la continuación de pies entre páginas.

## Resultados frente a los umbrales del plan

| Métrica | Primera medición | Tras la mejora (IC 95 %) | Umbral |
|---|---:|---:|---:|
| F1 de figuras (etiqueta) | 0,996 | **0,996** | ≥ 0,90 ✓ |
| F1 de cajas a IoU ≥ 0,5 | 0,996 | **0,996** (0,98–1,0) | ≥ 0,90 ✓ |
| IoU mediana | 0,985 | 0,985 | |
| Página correcta | 1,00 | 1,00 | |
| Asociación de pies (similitud ≥ 0,9 frente a JATS) | 0,904 | **0,985** (0,97–1,0) | ≥ 0,95 ✓ |
| Pérdidas silenciosas | 0 | **0** | 0 ✓ |
| Recall@5 del contexto | 0,933 | **0,949** (0,92–0,98) | ≥ 0,90 ✓ |
| Tiempo de extracción | 43 ms/pág. | 38 ms/pág. | |

Por estrato, tras la mejora, todas las disciplinas tenían F1 de cajas de 1,0 frente a las cajas `auto`. Con las 43 cajas revisadas aplicadas, el F1 de cajas baja a 0,990 ([paneles](stage5-panels.md#cajas-de-figura-revisadas)). Los pies están entre 0,92 (informática) y 1,0; el contexto, entre 0,83 (química) y 1,0.

La primera medición mostraba un 0,90 en pies y un 0,82 en contexto. **Parte de esa diferencia era un error del propio evaluador, no del sistema**, y se corrigió antes de tocar el sistema:

- se medía el IoU contra cajas de referencia dudosas;
- no se emparejaban las figuras del JATS sin etiqueta;
- los pies con ecuaciones incluían el código LaTeX del JATS;
- el recall de contexto comprobaba el inicio del párrafo en lugar de la frase con la mención, y penalizaba los pasajes recortados correctamente.

## La mejora: continuación de pies

En las plantillas donde el pie y el cuerpo tienen el mismo tamaño de letra (*Scientific Reports* desde 2023), un pie situado al final de la página «absorbía» el primer párrafo de la página siguiente: 2178 caracteres frente a los 340 reales.

Regla nueva: si la última línea del pie termina una frase claramente antes del margen derecho de la columna, el pie está completo. Se exceptúa el caso en que la página siguiente empiece con un marcador de panel («a, Left panel: …»), habitual en las *Extended Data* de Nature.

La primera versión de la regla rompía ese caso y los pies de una sola línea; ambos se detectaron en el piloto y están cubiertos por tests. El extractor pasa a la versión 0.2.0, así que reprocesar crea una ejecución nueva y no mezcla resultados.

## Qué falta para cerrar la etapa 5

| Umbral del plan | Estado |
|---|---|
| mAP50 de paneles ≥ 0,85 y F1 panel–subpie ≥ 0,85 | medido frente a 185 cajas humanas: AP50 0,50 y F1 0,50, **no cumple**; las cajas no se muestran ([informe](stage5-panels.md)) |
| Precisión de citas ≥ 0,95 y completitud ≥ 0,90 | la precisión literal se mide (268/270 en el piloto); la precisión según la rúbrica ya se puede puntuar en la aplicación; la completitud necesita anotar qué fuentes debería citar cada afirmación |
| Afirmaciones sin respaldo ≤ 0,02 | herramienta lista (pantalla de revisión); faltan las puntuaciones |
| Contestabilidad ≥ 0,90 | necesita preguntas y respuestas anotadas |
| Revisión humana de la referencia | 43 de 43 figuras `needs_manual` revisadas; doble anotación del 25 % pendiente |
| Evaluación en `test` | solo al cerrar el pipeline candidato |

## Próximos pasos propuestos

1. **Paneles:** detectar y etiquetar paneles en cada figura y añadir cajas de panel a la referencia (borrador automático y revisión).
2. **Comprobación de números visibles:** contrastar los valores que el modelo dice leer en la figura con el texto que el PDF contiene dentro de la región.
3. ~~**Revisión humana:** herramienta de revisión en la aplicación~~ — hecha (ver abajo); falta hacer la revisión.
4. **Explicaciones sobre `validation`:** generarlas (≈ 0,15 USD) y medir la precisión de citas y los errores de forma comparable al piloto.

## Actualización: pantalla de revisión (2026-10-07)

La aplicación tiene una sección **Revisión** con dos colas, guiadas por [ANNOTATION_GUIDE.md](../ANNOTATION_GUIDE.md):

- **Cajas de referencia:** para cada figura `needs_manual` se muestra la página del PDF, la imagen publicada por PMC, el pie del JATS y las páginas donde aparece la etiqueta. Se dibuja o ajusta la caja arrastrando, o se marca «no está en el PDF» o «dudosa». Al guardar se pasa a la siguiente pendiente. **No se muestra la salida del sistema.**
- **Explicaciones:** cada afirmación se puntúa de 0 a 2 en los seis criterios de la rúbrica, con un botón «Todo bien» y un selector de error crítico. Se guarda automáticamente.

Las anotaciones van a `data/sfi48/reviews/*.json` (versionado), con el nombre del revisor. El evaluador SFI-48 ya aplica las cajas revisadas: sin revisiones da exactamente los mismos números que arriba. `scripts/eval/review_summary.py` calcula el avance, el acuerdo entre revisores, la tasa de afirmaciones sin respaldo, la precisión de citas y los errores críticos. Lo cubren 8 tests nuevos (108 en total), y se probó en el navegador en escritorio y móvil.
