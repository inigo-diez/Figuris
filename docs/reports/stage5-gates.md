# Etapa 5 — Matriz de umbrales

**Actualizada:** 2026-10-08 · **Sistema:** extractor 0.3.1, evidencia 0.2 (RapidOCR 3.9.2), anclas de panel 0.2, prompt `figure-explain/0.4` · **Conjuntos:** `dev` + `validation`; `test` evaluado una vez el 2026-10-08 ([informe](stage5-test.md))

Los umbrales son los de [EVALUATION_PLAN.md](../EVALUATION_PLAN.md) y [research/experiments.md](../../research/experiments.md).

- **Cumple:** medido y por encima del umbral.
- **Falla:** medido y por debajo.
- **Indicio:** medido con un método que no es el del plan, por ejemplo un juez LLM en lugar de anotación humana, o con un intervalo que incluye el umbral.
- **Sin medir.**

La etapa se cierra el 2026-10-08 con `test` evaluado una sola vez y **sin cumplir todos los umbrales**; ver [Cierre](#cierre). Los que fallan quedan documentados, no exentos.

| Umbral | Estado | Valor | Fuente y notas |
|---|---|---|---|
| F1 de figuras ≥ 0,90 | **Cumple** en `dev` + `validation`; **falla** en `test` | 0,990 en cajas a IoU 0,5 (etiquetas 0,996); `test` 0,874 (etiquetas 0,935) | [baseline](stage5-sfi48-baseline.md), con las 43 cajas revisadas aplicadas; [test](stage5-test.md): biomedicina escaneada 0,73 |
| Asociación de pies ≥ 0,95 | **Cumple** en `dev` + `validation`; **falla** por poco en `test` | 0,985 (IC 0,97–1,0); `test` 0,946 (IC 0,90–0,99) | Informática 0,92. Los escaneados sin pie JATS no entran en la métrica. En `test`, biomedicina 0,50 |
| Cero pérdidas silenciosas | **Cumple** en `dev` + `validation`; **falla** en `test` | 0; `test` 1 | En escaneados, el inventario de figuras sale del texto OCR; una figura ausente del borrador no cuenta. En `test` se pierde sin aviso la Figura 3 de PMC2033889 (escaneado) |
| Recall@5 del contexto ≥ 0,90 | **Cumple** | 0,949 (IC 0,92–0,98); `test` 0,934 (IC 0,90–0,96) | Química 0,83 en `dev` + `validation` |
| Precisión del contexto ≥ 0,70 | Sin medir | — | Necesita párrafos anotados como relevantes o no |
| mAP50 de paneles ≥ 0,85 | **Falla** | 0,61 en `validation` (`dev` 0,83) | [paneles](stage5-panels.md), anclas 0.2; 34 figuras de `validation` (130 paneles) que no se usaron para diseñar el método |
| Precisión de letras de panel ≥ 0,90 | **Falla** por poco | 0,897 en `validation` (`dev` 0,93) | Ídem |
| F1 panel–sub-pie ≥ 0,85 | **Falla** | 0,65 en `validation` (`dev` 0,80) | Ídem. Además, la referencia de sub-pies usa el mismo parser que el sistema |
| Exactitud de entidades OCR ≥ 0,95 digitales (E03) | **Falla** | 0,897 en números (200 ppp) | [ADR 0007](../decisions/0007-ocr-evidence-layer.md): 953 números de 17 figuras vectoriales renderizadas, con el texto PDF como referencia. Por eso el OCR solo enlaza valores y no invalida |
| Exactitud de entidades OCR ≥ 0,88 rasterizadas (E03) | Sin medir | — | Falta una referencia para figuras rasterizadas |
| Letras de panel localizadas por OCR | Medido (sin umbral) | 0,87 (185 paneles) | Base para usar las letras como anclas al separar paneles |
| Afirmaciones sin respaldo ≤ 0,02 (confianza alta) | **Indicio** | 0,0145 (IC 0,005–0,042) | [explicaciones](stage5-explanations-judge.md), `validation`, prompt 0.4: juez LLM, cada objeción verificada y 2 explicaciones revisadas a ciegas. El intervalo incluye el umbral |
| Precisión de citas ≥ 0,95 | **Indicio** | 98 de 98 citas exactas según el juez | Mismo origen. No es anotación humana |
| Completitud de citas ≥ 0,90 | Sin medir | — | Necesita anotar qué fuentes debería citar cada afirmación |
| Contestabilidad ≥ 0,90 | Sin medir | — | Necesita preguntas y respuestas anotadas |
| Cero referencias inventadas en `test` | **Cumple** en lo que ve el lector | 7 inventadas en 5 de 149 explicaciones, todas detectadas; 0 mostradas como fiables | [test](stage5-test.md), `reference_check.py`. No detecta una afirmación falsa que cite un texto real |
| Acuerdo entre anotadores (IoU mediana ≥ 0,90; kappa ≥ 0,80) | Sin medir | — | Una sola anotadora; falta la doble anotación del 25 % |
| Prueba de usabilidad (etapa 4) | Pendiente | — | Protocolo en [USABILITY_TEST.md](../USABILITY_TEST.md) |

## Lo que no es un umbral pero condiciona los resultados

- **Corpus:** 6 escaneados en lugar de 8 y ningún artículo en otro idioma. 17 artículos son de *Scientific Reports* y la mayoría son de 2023–2024. Hay alguna clasificación discutible: PMC10397266, una planta de para-xileno, figura en «ciencias sociales». Ver [data/sfi48/README.md](../../data/sfi48/README.md).
- **`test` no es ciego:** sus identificadores y 25 cajas revisadas están versionados. Se usó como conjunto reservado: nada se ajustó con él. Lo evaluó el mismo equipo que construyó el sistema, no otra persona.
- **Confianza:** la de cada afirmación la declara el modelo y no está calibrada.


## Cierre

La etapa 5 se cierra el 2026-10-08 por decisión de Inigo: el objetivo del proyecto es construir el sistema completo y medirlo con honestidad, no perseguir cada umbral. Al cierre:

- **Se cumplen:** etiquetas de figura y contexto, también en `test`; ninguna referencia inventada se muestra como fiable.
- **Fallan:** en `test`, las cajas de figura, los pies y las pérdidas silenciosas, sobre todo por los artículos escaneados. También fallan los paneles y el OCR de números.
- **Indicios o sin medir:** la tasa de afirmaciones sin respaldo y la precisión de citas se midieron con un juez LLM y solo en `validation`. Siguen sin medir la completitud de citas, la contestabilidad, el acuerdo entre anotadores y la prueba de usabilidad.

Las cajas de panel siguen ocultas en la aplicación y el OCR solo enlaza valores, sin invalidar nada.
