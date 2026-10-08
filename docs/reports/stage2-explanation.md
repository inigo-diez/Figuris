# Etapa 2 — Análisis y explicación de las figuras

**Fecha:** 2026-10-06 · **Modelo:** `gpt-6-luna` (OpenAI, Responses API) · **Prompt:** `figure-explain/0.1` · **Validador:** `validate/0.2` · **Corpus:** piloto SFI-12 (78 regiones: 77 figuras y una región sin pie)

## Resultado

Se cumple el criterio de finalización de la etapa. Con `sfi process articulo.pdf --report` se extraen las figuras y se obtiene una explicación estructurada debajo de cada una, sin pasos manuales intermedios.

| Métrica | Resultado |
|---|---:|
| Explicaciones válidas (`ok`) | **77/78** |
| Marcadas como no fiables | 1 (`invalid`, ver más abajo) |
| Respuestas truncadas o mal formadas en la ejecución final | 0 |
| Afirmaciones por figura | 8,9 de media (5–14) |
| Tipos de afirmación | 357 observadas · 215 del pie · 23 inferencias · 100 inciertas |
| Figuras con al menos una incertidumbre declarada | 78/78 |
| Coste del piloto completo | **0,10 USD** (0,0013 USD por figura) |
| Latencia por figura | mediana 13,2 s · p90 19,1 s · máx. 22,8 s |
| Tiempo total del piloto | ~6 min con 4 llamadas concurrentes |
| Tokens por figura | 3154 de entrada (55 % servidos desde la caché de prompts de OpenAI) · 1957 de salida (138 de razonamiento) |

Gasto total registrado en la etapa, pruebas incluidas: **0,10 USD de los 5 USD de presupuesto** (`sfi costs`).

## Calidad frente a los resultados esperados

Las 13 figuras anotadas a mano en [expected_results.json](../../data/stage0/expected_results.json) se revisaron con la hoja que genera `scripts/eval/stage2_eval.py`. Cuando había dudas se contrastaron con el recorte de la figura. **La revisión la hizo el asistente (Claude) y está pendiente de revisión humana.** No sustituye a la evaluación con jueces y anotadores prevista en el [plan de evaluación](../EVALUATION_PLAN.md).

| Figura | Debe observar | Según el pie | Marca como incierto | Afirmaciones prohibidas |
|---|---:|---:|---:|---:|
| PMC7270115 Fig. 2 (XRD/FTIR) | 4/4 | 3/3 | 1/2 | 0 |
| PMC7270115 Fig. 4 (SEM) | 3/3 | 3/3 | 1/1 | 0 |
| PMC6599010 Fig. 3 (dispositivo solar) | 4/4 | 2/2 | 1/1 | 0 |
| PMC7280498 Fig. 2 (mapas) | 3 + 1 parcial /4 | 1/1 | 1/2 | 0 |
| PMC8913360 Fig. 4 (forest plots) | 3/3 | 3/3 | 1/1 | 0 |
| PMC8359101 Fig. 4 (blots, IF, docking) | 3 + 2 parciales /5 | 2/2 | 1/2 | 0 |
| PMC6291436 Fig. 3 (RM) | 3/3 | 1/1 | 0/1 | 0 |
| PMC9608490 Fig. 1 (estructura molecular) | 2/3 | — | — | 0 |
| PMC10290119 Fig. 4 (arquitectura) | 3/3 | 1/1 | — | 0 |
| PMC7786143 Fig. 1 (barras apiladas) | 2 + 1 parcial /3 | 1/1 | 1/1 | 0 |
| PMC1971560 Fig. 2 (escaneado, farmacocinética) | 2/2 | 2/2 | 1/1 | 0 |
| PMC1971560 Fig. 3 (escaneado, histología) | 1/1 | 1 + 1 parcial /2 | 1/1 | 0 |
| PMC1971548 Fig. 1 (escaneado, barras) | 3/3 ¹ | 2/2 | 1/1 | 0 |
| **Total** | **36 + 4 parciales /41** | **22 + 1 parcial /23** | **10/14** | **0/15** |

Seis afirmaciones esperadas proceden del cuerpo del artículo o de tablas, no del pie: el índice Dice, la fórmula empírica, el grupo espacial, la arquitectura CNN, la forma de las partículas y el mejor dispositivo de la tabla 1. Quedan fuera de esta etapa porque el modelo solo recibe la figura y su pie. Son el objetivo de la etapa 3.

¹ Hay un error de lectura: atribuye a «Nigeria, Ibadan» una tasa combinada de 10,3, pero ese es el valor del segmento Wilms. El total queda fuera del recorte (ver limitaciones).

Observaciones:

- **Lo visual se lee bien.** Las seis barras de escala de las micrografías SEM (30 µm … 300 nm), los rangos y títulos de los ejes FTIR/XRD, las leyendas de color y los rótulos de las capas del dispositivo coinciden exactamente con la anotación.
- **Las citas del pie son literales en el 100 % de los casos.** El validador comprueba cada cita y no hubo ninguna inventada.
- **El modelo es prudente.** No aparece ninguna afirmación prohibida: ni valores numéricos inventados, ni diagnósticos, ni cuantificación de bandas. Separa lo que dice el pie de lo que se ve. Por ejemplo, en el mapa truncado declara que no puede asignar 2004/2013 a los mapas inferiores.
- **Detecta problemas de la extracción:** el pie contaminado por el OCR en PMC1971560 Fig. 2, la leyenda cortada en PMC1971548 Fig. 1 y los pies posiblemente truncados.
- **Lo más débil son las incertidumbres esperadas (10/14).** Omite, por ejemplo, que no puede saberse la orientación izquierda/derecha en la RM ni el tamaño de cristalito en el XRD. No afirma lo contrario, pero tampoco lo señala.
- **Una anotación por revisar:** el resultado esperado de PMC8913360 Fig. 4 menciona un eje «Mean difference», pero el recorte no muestra ese título y el modelo dice, con razón, que no lo ve. Hay que comprobar en la página si el título existe fuera del recorte.

## Fiabilidad: qué se marca y qué no

Cada respuesta se valida antes de mostrarse. Sus estados posibles son:

| Estado | Significado | Se muestra |
|---|---|---|
| `ok` | cumple el esquema y las reglas | sí |
| `incomplete` | truncada o le falta contenido obligatorio | sí, con aviso «no fiable» |
| `invalid` | JSON mal formado, rechazo del modelo o regla incumplida | sí, con aviso «no fiable» y la afirmación señalada |
| `failed` | la llamada falló; se reintenta en la siguiente ejecución | no |
| `skipped` | sin región, límite o presupuesto alcanzado; siempre con el motivo | no |

Reglas implementadas ([validate.py](../../src/sfi/analysis/validate.py)), según [EXPLANATION_SCHEMA.md](../EXPLANATION_SCHEMA.md):

- el esquema es estricto, con todos los campos obligatorios y sin campos extra;
- `summary`, `layout` y al menos una afirmación son obligatorios;
- una afirmación `author_stated` debe citar el pie, y cada cita debe aparecer literalmente en él. Se toleran espacios, comillas tipográficas, guiones, ligaduras, guiones de fin de línea y fragmentos unidos por «…» en orden;
- los paneles citados deben existir en `layout.panels`, y las referencias a afirmaciones deben existir;
- cada número de una afirmación `author_stated` debe estar en el pie, también si allí aparece escrito en letra («Fifty-six» = 56), o la afirmación debe estar marcada `approximate`. En las inferencias del modelo, un número no respaldado es un aviso;
- si la lista de limitaciones está vacía y no se justifica, se emite un aviso.

Casos reales de esta etapa:

1. **Respuesta truncada.** En la primera prueba, con el límite de 2000 tokens de salida, la respuesta se cortó y quedó como `incomplete`, no como válida. El límite se subió a 6000: la respuesta más larga del piloto tuvo 3793 tokens.
2. **Afirmación mal tipada, detectada.** En PMC10368530 Fig. 4, el modelo atribuye al pie (`author_stated`) unos valores de HR y p que en realidad lee del gráfico. El validador la marca como `invalid`. Es el único resultado no fiable del piloto.
3. **Falso positivo del validador, corregido.** En PMC6291436 Fig. 1, el pie escribe «Fifty-six» y la versión 0.1 de la regla solo reconocía números en letra hasta doce. Al cambiar las reglas, los resultados guardados se revalidan en local sin volver a llamar al modelo y sin coste. La versión del validador se registra en cada análisis.

## Qué hace el sistema

```text
figura (recorte PNG) + pie + avisos de extracción
    ─► imagen aplanada y reducida a 1536 px de lado mayor
    ─► clave de caché = recorte + etiqueta + pie + modelo + prompt + límites
    ─► ¿resultado guardado? → se reutiliza (y se revalida si cambió el validador)
    ─► comprobación de presupuesto con el peor caso (entrada estimada + salida máxima)
    ─► gpt-6-luna, salida JSON con esquema estricto, store=false
    ─► parseo → validación → estado
    ─► SQLite: explicación, respuesta cruda, avisos, modelo, prompt, tokens, coste, latencia
    ─► galería HTML: explicación debajo de cada figura
```

- **Adaptador propio** ([providers.py](../../src/sfi/analysis/providers.py)), según la [ADR 0003](../decisions/0003-provider-neutral-models-no-agent-framework.md). El pipeline solo conoce `MultimodalModel`. El adaptador de OpenAI devuelve el texto crudo y el estado, y el parseo y la validación se hacen fuera, así que una respuesta mal formada se conserva y se marca en lugar de perderse.
- **Contrato** ([schema.py](../../src/sfi/analysis/schema.py)): `explanation/0.1`, implementado en Pydantic y enviado al modelo como JSON Schema estricto.
- **Prompt** ([prompt.py](../../src/sfi/analysis/prompt.py)): el pie y el texto de la imagen se tratan como datos, no como instrucciones. Las explicaciones se escriben en español y las citas se mantienen en el idioma del artículo. Cambiar el texto obliga a cambiar `PROMPT_VERSION`, que forma parte de la clave de caché.
- **Procedencia:** cada análisis guarda el modelo pedido y el devuelto, la versión del prompt y del validador, el id de respuesta, los tokens (entrada, entrada cacheada, salida, razonamiento), el coste estimado, la latencia y el estado del proveedor. Los análisis solo se añaden: `--force` crea un intento nuevo y no sobrescribe el anterior.

## Coste y límites

| Límite (`.env`) | Valor | Efecto |
|---|---:|---|
| `SFI_TOTAL_BUDGET_USD` | 5,00 | antes de cada llamada se comprueba el peor caso frente al gasto registrado; si no cabe, el resto se omite con el motivo |
| `SFI_MAX_COST_PER_DOCUMENT_USD` | 0,25 | ídem, para cada documento en cada ejecución |
| `SFI_MAX_FIGURES_PER_DOCUMENT` | 25 | las figuras sobrantes se omiten y se avisa (`--max-figures` lo baja para probar) |
| `SFI_MAX_OUTPUT_TOKENS_PER_FIGURE` | 6000 | antes 2000, que truncaba; peor caso 0,003 USD por figura |
| `SFI_MAX_IMAGE_LONG_SIDE_PX` | 1536 | tamaño de la imagen enviada |

- Con los precios configurados (0,10 / 0,50 USD por millón de tokens), un artículo de 16 figuras cuesta unos 0,03 USD. SFI-48 costaría alrededor de 0,40 USD.
- El coste es una estimación: se calcula con los tokens de cada respuesta y los precios de `.env`. La entrada servida desde caché se cobra a precio completo, así que la cifra es una cota superior.
- El respaldo `gpt-6.1-sol` sigue desactivado (`SFI_ENABLE_AUTOMATIC_FALLBACK=true` da error al arrancar, según la ADR 0003). Se puede elegir explícitamente con `--model gpt-6.1-sol` (unas 20 veces más caro).
- Los errores que se repetirían en cada llamada (clave rechazada, cuota agotada, modelo inexistente) detienen el análisis. Los demás errores marcan la figura como `failed` y se reintentan en la siguiente ejecución.

## Limitaciones conocidas

1. **Los números de las afirmaciones `observed` no se verifican automáticamente:** salen de la imagen, que solo ve el modelo. Se detectó un error de este tipo (Nigeria, 10,3) en la revisión manual.
2. **Los recortes condicionan la explicación.** En PMC1971548 Fig. 1 el recorte de la etapa 1 corta el borde derecho (leyenda y algunos totales). El modelo lo declara, pero no puede leer lo que falta.
3. **La evaluación semántica es manual** y cubre 13 figuras. Falta un juez automático y una segunda anotación humana.
4. **Solo figura y pie.** Las afirmaciones que dependen del texto del artículo quedan como incertidumbres o no aparecen. Se resuelve en la etapa 3.
5. **Variabilidad sin medir:** hubo una sola ejecución por figura y no se ha medido cuánto cambia la explicación entre llamadas.
6. **El presupuesto se cuenta en la base de datos local.** Si se borra `data/local/sfi.sqlite3`, el contador vuelve a cero. El límite real lo pone el saldo de la cuenta de OpenAI.
7. **Precios configurados a mano** (verificados el 2026-10-06). Si OpenAI los cambia, hay que actualizar `.env`.

## Cómo reproducirlo

```bash
.venv/Scripts/pip install -e ".[dev]"            # Windows; en Linux/macOS: .venv/bin/
# OPENAI_API_KEY en .env (ver .env.example)
sfi process data/raw/stage0/*.pdf --report        # extrae, explica y genera la galería
sfi analyze --report                              # explica lo ya extraído (usa la caché)
sfi costs                                         # gasto frente al presupuesto
python scripts/eval/stage2_eval.py                # métricas y hoja de revisión (no llama al modelo)
pytest                                            # 63 tests, sin red
```

## Siguiente paso

Etapa 3: añadir el texto del artículo. Habrá que detectar las menciones a cada figura («Fig. 2b»), recuperar los párrafos cercanos, añadir evidencia `text_span` con página y validar que las citas del texto también sean literales. Completada: ver [stage3-context.md](stage3-context.md).
