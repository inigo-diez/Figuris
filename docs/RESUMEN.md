# Resumen del proyecto

**Fecha:** 2026-10-08, al cerrar la etapa 5.

## Qué es

Una aplicación local que lee un artículo científico en PDF, localiza cada figura con su pie y sus paneles, encuentra los párrafos que hablan de ella y pide a un modelo multimodal una explicación. Cada afirmación de la explicación cita su fuente (el pie, un párrafo o un número impreso en la figura), y el sistema comprueba esas citas antes de mostrarla. Lo que no pasa la comprobación aparece como «no fiable».

## Qué se construyó (etapas 0–5)

1. **Corpus con licencias verificadas:** un piloto de 12 artículos y SFI-48, con 48 artículos de seis disciplinas divididos en `dev`, `validation` y `test`.
2. **Extracción de figuras y pies** sin IA, incluidos PDF escaneados.
3. **Explicación estructurada** con afirmaciones tipadas: observado, dicho por los autores, inferencia o incierto.
4. **Contexto del artículo:** párrafos que mencionan cada figura, con citas literales y su página.
5. **Aplicación web local** para subir artículos, ver las figuras y su evidencia y revisar a mano.
6. **Evaluación:** referencia humana (cajas de figura y de panel), juez LLM para las explicaciones, capa de OCR y un examen final en `test`.

## Qué funciona (medido)

- Encuentra las figuras y sus pies: 0,99 en `dev` + `validation` y 0,87–0,94 en `test`.
- Encuentra los párrafos que hablan de cada figura: Recall@5 de 0,93–0,95.
- **Ninguna cita inventada llega al lector como fiable:** en `test`, el modelo inventó 7 citas en 149 explicaciones y el sistema detectó las 7.
- Según un juez LLM, sin anotación humana, 3 de 207 afirmaciones de `validation` no tenían respaldo.
- Coste total: **0,82 USD** para unas 300 explicaciones.

## Qué no funciona

- **Artículos escaneados:** concentran los fallos de `test` y una figura se pierde sin aviso.
- **Separar paneles:** 0,61 en figuras nuevas, frente al 0,85 que pedía el plan. Las cajas de panel no se muestran.
- **OCR de números:** lee bien el 90 % y el plan pedía el 95 %. Solo sirve para enlazar valores.
- **Sin medir:** la corrección de las explicaciones por un experto humano, la prueba con usuarios y el acuerdo entre dos anotadores.

## Lo que aprendí

- **Lo que se ajusta con unos datos parece mejor en esos datos:** los paneles daban 0,83 en `dev` y 0,61 en figuras nuevas. Por eso existe `test`, y por eso no se toca.
- **La IA se equivoca, pero se puede vigilar:** encerrarla entre una preparación y una comprobación hechas sin IA es lo que hace fiable el resultado, no el modelo.
- **Medir cuesta más que construir:** anotar cajas, revisar explicaciones y separar `dev`, `validation` y `test` llevó más esfuerzo que el código, y es lo que permite decir con honestidad qué funciona.
- **Sin ser experto en las disciplinas** se puede construir y medir casi todo, pero juzgar si una explicación es correcta necesita un experto o, como aquí, un juez LLM verificado a mano.

Detalle de cada umbral: [stage5-gates.md](reports/stage5-gates.md). Examen final: [stage5-test.md](reports/stage5-test.md).
