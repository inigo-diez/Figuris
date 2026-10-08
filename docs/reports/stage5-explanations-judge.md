# Etapa 5 — Primera revisión de explicaciones con otra IA

**Fecha:** 2026-10-07 · **Revisor:** GPT-5 Codex (juicio de un modelo, no referencia humana) · **Verificación:** cada objeción comprobada contra la figura, el pie y el PDF · **Muestra:** 13 explicaciones (una por documento, semilla 20261007), 135 afirmaciones

## Método

`scripts/eval/export_judge_packet.py` generó para cada explicación:

- la imagen de la figura;
- el pie;
- los fragmentos del artículo que recibió el modelo;
- las afirmaciones con su evidencia.

Otro modelo las puntuó con la rúbrica de [ANNOTATION_GUIDE.md](../ANNOTATION_GUIDE.md) sin ejecutar nada y sin acceso a otros archivos. Su respuesta se importó con `import_judge_scores.py` en `data/sfi48/reviews/claims.json` (`annotator_kind: llm`).

Después se comprobó una a una cada objeción, es decir, cada puntuación menor que 2 o error crítico. El resultado está en `data/sfi48/reviews/judge_checks.json`.

## Resultado

| | Revisor sin depurar | Tras comprobar sus objeciones |
|---|---:|---:|
| Afirmaciones con objeción | 18 | 5 confirmadas, 4 en parte, 9 rechazadas |
| Errores graves en afirmaciones de confianza alta | 5 de 123 | **4 de 123 (0,033)**; umbral del plan ≤ 0,02 |
| Explicaciones con un error grave | 5 de 13 | **4 de 13** |
| Precisión de citas (cita exacta entre las que citan) | 0,84 | **≈ 0,97**; umbral ≥ 0,95 |

**Dónde falla el sistema:** los cuatro errores confirmados son **lecturas de la imagen** en afirmaciones «observado» de confianza alta:

- **Barras apiladas:** toma por total el valor que rotula el segmento de Wilms (PMC1971548 Fig. 1). Contribuye un fallo de extracción: el recorte corta el borde derecho, donde están los totales.
- **Comparación de segmentos:** dice que el verde es menor que el gris en recursos donde es mayor (PMC7786143 Fig. 1).
- **Izquierda y derecha:** sitúa la lesión a la izquierda de la imagen cuando está a la derecha (PMC6291436 Fig. 5). Probablemente confunde la convención radiológica.
- **Generalización:** «cada compuesto con su IC₅₀» cuando el compuesto 3 no lo tiene (PMC9608490 Fig. 5).

Hay además un error menor (líneas grises que se describen como rojas).

**Dónde no falla:** el revisor no objetó ninguna de las 60 afirmaciones atribuidas a los autores, salvo dos objeciones de página que resultaron erróneas. No es una verificación humana exhaustiva de las 60.

**Errores del revisor**, que se deben al paquete y ya están corregidos:

- penalizó las afirmaciones «incierto» por no tener evidencia, que por diseño no llevan;
- tomó la página de inicio del fragmento por la página de la cita;
- no vio la nota «el pie puede estar truncado» que sí recibió el modelo, y la llamó referencia inventada.

## Hallazgos para el sistema

1. **Lectura de gráficos:** reglas en el prompt para barras apiladas (segmento frente a total), comparaciones entre segmentos, orientación de la imagen y generalizaciones con «cada». Lo confirmaría la **comprobación de números** pendiente de la etapa 5.
2. **Nota de pie truncado:** se envía aunque la continuación ya se haya recuperado, y provoca dudas innecesarias. Hay que distinguir «continuación recuperada» de «puede estar truncado».
3. Cambiar el prompt invalida la caché, así que habrá que volver a explicar las figuras (≈ 0,15–0,30 USD por las 81 actuales). Conviene hacerlo de una vez con las tres mejoras.

## Limitaciones

- Es una muestra pequeña (13 explicaciones): 12 de documentos `dev`, con los que se desarrolló el prompt, y una de PMC8448759, que no pertenece a SFI-48.
- El revisor es otro modelo y la verificación la hizo el asistente de desarrollo. No sustituye a la rúbrica humana ni a la doble anotación.
- La siguiente ronda debería hacerse sobre `validation`.

## Aplicado: prompt 0.4 y extractor 0.3.1 (2026-10-07)

Cambios:

- **Prompt 0.4:** regla 11 de lectura de gráficos. Un número sobre un segmento rotula ese segmento; solo se comparan diferencias claras y se comprueba cada elemento nombrado; izquierda y derecha se refieren a la imagen; no se generaliza con «cada» o «todos» sin comprobarlo.
- **Extractor 0.3.1:** el pie que continúa en la página siguiente y ya se ha unido lleva el aviso nuevo `caption_continued`, que no se envía al modelo. `caption_may_continue` queda solo para pies que pueden estar truncados de verdad.

Se volvieron a explicar las 81 figuras de los 13 documentos locales, por **0,129 USD** (total acumulado 0,48 de 5 USD).

Comprobación de los errores confirmados en las nuevas explicaciones:

| Figura | Antes | Ahora |
|---|---|---|
| PMC1971548 Fig. 1 | «tasa total de 10.9» | «10.9 para el componente blanco; el segmento tramado se prolonga más allá del borde» ✓ |
| PMC7786143 Fig. 1 | verde menor que gris en tres recursos (dos falsos) | solo comparaciones claras con el 50 %, todas correctas ✓ |
| PMC9608490 Fig. 5 | todos los compuestos con IC₅₀ | «el compuesto 3 … no muestra un valor de IC₅₀» ✓ |
| PMC6291436 Fig. 5 | lesión «a la izquierda de la imagen» | no afirma la posición; el lado sale del pie, citado ✓ |
| PMC10368530 Fig. 3 | duda por un pie «truncado» que estaba completo | sin esa duda ✓; pero queda marcada no fiable por otro motivo (limitations cita una afirmación c13 que no existe) |
| PMC8448759 Fig. 2 (menor) | líneas de la región causal «rojas» | sigue igual ✗ |

Las explicaciones marcadas como no fiables por el validador pasan de 3 a 4 de 81. Tres tienen citas o números que no aparecen tal cual en la fuente; una de ellas es del artículo escaneado, con errores de OCR. La cuarta cita una afirmación que no existe. Se muestran como «no fiable», no como buenas.

Esta comprobación cubre solo las figuras donde se encontraron los errores. Para medir el efecto en general hace falta otra ronda de revisión, mejor sobre `validation`.

## Segunda ronda: artículos nuevos (`validation`, prompt 0.4)

Se procesaron y explicaron los 12 artículos de `validation`, que el sistema no había visto, por 0,109 USD (total acumulado 0,59 de 5 USD). De 76 figuras, el validador marcó 3 como no fiables. Se revisaron 24 explicaciones, 2 por artículo y elegidas al azar, con 233 afirmaciones. Lo hizo el mismo revisor externo en dos lotes, y cada objeción se comprobó contra la imagen (`data/sfi48/reviews/judge_checks_validation.json`).

| | Primera ronda (`dev`, prompt 0.3) | Segunda ronda (`validation`, prompt 0.4) |
|---|---:|---:|
| Afirmaciones revisadas | 135 | 233 |
| Objeciones del revisor | 18 | 4 |
| Errores confirmados en afirmaciones de confianza alta | 4 de 123 (0,033) | **3 de 207 (0,0145; IC 95 % 0,005–0,042)** |
| Explicaciones con algún error confirmado | 4 de 13 | 2 de 24 |
| Errores en lo atribuido a los autores | 0 de 60 | 0 de 92 |

**Errores confirmados:**

- **PMC11720905 Fig. 3:** dos afirmaciones confunden la concentración con la barra más alta. Las tres concentraciones se dibujan en grises parecidos.
- **PMC10397266 Fig. 3:** una duda falsa. Dice que la figura no indica qué componente empieza alto, pero la leyenda lo identifica y la propia explicación lo dice en otra afirmación.

No aparece ninguno de los tipos de error corregidos en el prompt 0.4.

**Lo que se le escapa al revisor:** se revisaron de forma independiente dos explicaciones que el revisor dio por perfectas (PMC11315888 Fig. 4 y PMC11211412 Fig. 7, 23 afirmaciones). No tenían errores ocultos. Es una muestra pequeña, pero indica que el revisor no pasa por alto errores evidentes.

**Lectura:** la tasa queda por debajo del umbral de 0,02, pero el intervalo de confianza lo incluye. Para afirmar que se cumple hace falta una muestra mayor, idealmente el conjunto `test` al cerrar la etapa. El punto débil que queda es **distinguir colores o tonos parecidos** entre series. Ni las reglas del prompt ni la comprobación de números lo resuelven. Podría ayudar una regla que pida no asignar una serie a un tono cuando la leyenda usa tonos casi iguales, o enviar la imagen a más resolución.
