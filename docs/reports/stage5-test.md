# Etapa 5 — Evaluación final en `test`

**Fecha:** 2026-10-08 · **Sistema:** extractor 0.3.1, evidencia 0.2 (RapidOCR 3.9.2), anclas de panel 0.2, prompt `figure-explain/0.4`, modelo `gpt-6-luna` · **Conjunto:** `test` (24 artículos, 142 figuras de referencia)

`test` estuvo congelado hasta hoy y se evaluó una sola vez, con el sistema ya cerrado. No se ha ajustado nada después de ver los resultados. Cada lectura de `test` queda registrada en `data/sfi48/test_runs.log`.

## Ejecuciones

| Qué | Script | Ejecución |
|---|---|---|
| Figuras, pies, pérdidas silenciosas, contexto | `sfi48_eval.py --splits test --include-test` | `evaluation/runs/20261008-082410-sfi48-0.3.1-a0a36922` |
| Paneles frente a cajas humanas | `panel_eval.py --include-test` | `evaluation/runs/20261008-083925-panels-anchors-0.2-4c7ca5c8` |
| Referencias inventadas en las explicaciones | `reference_check.py --split test --include-test` | `evaluation/runs/20261008-091722-references-test-ef02c460` |

Generar las 149 explicaciones de `test` costó 0,23 USD. El gasto total del proyecto es de 0,82 USD sobre un presupuesto de 5 USD.

## Resultados

| Umbral | `dev` + `validation` | **`test`** | ¿Cumple en `test`? |
|---|---:|---:|---|
| F1 de figuras ≥ 0,90 (cajas, IoU 0,5) | 0,990 | **0,874** | No |
| … solo etiquetas de figura | 0,996 | 0,935 | Sí |
| Asociación de pies ≥ 0,95 | 0,985 | **0,946** (IC 0,90–0,99) | No, por poco |
| Cero pérdidas silenciosas | 0 | **1** | No |
| Recall@5 del contexto ≥ 0,90 | 0,949 | **0,934** (IC 0,90–0,96) | Sí |
| Cero referencias inventadas | 2 detectadas, 0 mostradas como fiables (`validation`) | **7 detectadas, 0 mostradas como fiables** | Sí, en lo que ve el lector |
| Paneles (AP50 / letras / F1) | 0,61 / 0,897 / 0,65 (`validation`) | 0,40 / 1,00 / 0,53 | No medible: solo 6 figuras |

### Lo que baja en `test`

- **Biomedicina:** 3 de sus 4 artículos son escaneados. En esa disciplina, el F1 de cajas es 0,73 y la asociación de pies 0,50.
- **Una pérdida silenciosa:** la Figura 3 de PMC2033889 (escaneado). No se encuentra y no se avisa. Es justo lo que el plan quiere evitar.
- **PMC11544223** (química): 5 de 6 figuras encontradas, pero solo 1 de esas 5 cajas coincide con la referencia, y en 3 la página no cuadra. Puede ser un problema de la referencia: la figura 5 de ese artículo se anotó sobre otra figura de la misma página. No se ha corregido, para no tocar `test` a la vista de los resultados.

### Referencias inventadas

En las 149 explicaciones (1 437 afirmaciones, 1 716 citas de evidencia), el modelo inventó **7 referencias en 5 explicaciones**: 4 citas que no están en el párrafo indicado, 1 que no está en el pie y 2 referencias a afirmaciones inexistentes. El validador detectó las 7 y esas 5 explicaciones aparecen como «no fiable». **Ninguna llega al lector como fiable.** Es lo que el diseño pretendía: el modelo se equivoca, pero el sistema lo detecta.

Este control no detecta una afirmación falsa que cite un texto real. Eso lo mide la tasa de afirmaciones sin respaldo, que necesita un juez y en `test` está **sin medir**.

### Paneles

En `test` solo hay 8 figuras con cajas de panel humanas. Se puntúan 6 y dos de ellas tienen anotaciones defectuosas, detectadas antes de ejecutar la evaluación (PMC11544223 Fig. 1 y 5). Con esa muestra no se puede concluir nada. La conclusión de paneles es la de `validation`: no alcanzan el umbral y no se muestran.

## Conclusión

El sistema generaliza peor de lo que indicaban `dev` y `validation`, sobre todo en artículos escaneados. Los umbrales de extracción que se cumplían allí (F1 de figuras, pies, cero pérdidas silenciosas) **no se cumplen en `test`**. Sí se mantienen las etiquetas de figura, el contexto y la garantía principal del diseño: ninguna referencia inventada se muestra como fiable.
