# Etapa 5 — Separación de paneles (E02, línea base)

**Fecha:** 2026-10-07 · **Extractor:** `pdfium-heuristic` 0.3.0 · **Evaluado:** `dev` + `validation` (69 figuras multipanel, 299 paneles); `test` congelado

## Qué se ha hecho

1. **Pies divididos por panel** (`sfi.extract.panels.parse_subcaptions`): reconoce marcadores «a …», «(b) …», «A. …», «c–e …» y grupos como «(A–C) Micrografías de X. (A) 500×. (B) 2000×…». Las letras deben seguir la secuencia a, b, c… en orden, para que las referencias posteriores («como en (a)») no se confundan con marcadores.
2. **Cajas de panel** por la línea base del plan: corte recursivo por huecos en blanco (XY-cut) sobre la figura renderizada a 100 ppp. El número de paneles que anuncia el pie guía el corte:
   - se prueban varias anchuras mínimas de hueco y, además del fondo blanco, el fondo oscuro de algunas micrografías;
   - las franjas finas (títulos de eje, una letra de panel en su propia fila) se unen a su vecino;
   - si sobran trozos, porque un panel contiene varias imágenes, se fusionan los vecinos que menos área vacía crean.
3. **Letras por orden de lectura.** Casi todas las figuras publicadas son una única imagen, con las letras pintadas en píxeles (≈ 140 de 148 en `dev` + `validation`). Leerlas necesita OCR (E03). Por eso:
   - las letras se asignan en orden de lectura (filas y, dentro de cada fila, de izquierda a derecha);
   - **las cajas solo se publican si el número de paneles coincide con el del pie**. Si no coincide, la figura queda entera y cada panel conserva solo su letra y su parte del pie, como pide el plan («publicar siempre el recorte compuesto si la confianza no supera el umbral»).
4. **Confianza:** 0,8 si el corte da directamente el número del pie y 0,6 si hubo que fusionar trozos.
5. **Integración:** cada `Figure` guarda `panels` (letra, caja, sub-pie, confianza, método) y `panel_layout` (`single`, `split` o `unmatched`). En la vista de figura se ven los contornos de los paneles y la lista de sub-pies. Las etiquetas de panel de cada afirmación («a», «panel B») llevan al panel ampliado.
6. **Revisión humana de paneles:** nueva cola en **Revisión → Paneles**. Una persona dibuja la caja de cada letra sin ver la propuesta del sistema. Las cajas se guardan en `data/sfi48/reviews/panels.json`.
7. **Evaluación** (`scripts/eval/sfi48_eval.py`): métricas automáticas ya disponibles y, en cuanto haya cajas humanas, AP50, precisión de letras, F1 panel–sub-pie y exactitud del número de paneles.

## Resultados

| Métrica | `dev` | `validation` |
|---|---:|---:|
| Figuras multipanel (≥ 2 letras en el pie JATS) | 35 | 34 |
| Letras del pie encontradas en el pie del PDF | 168/168 | 131/131 |
| Sub-pie de cada panel igual al del JATS (similitud ≥ 0,9; mismo parser en ambos lados) | 1,00 | 1,00 |
| Figuras separadas en cajas (número igual al del pie) | **0,94** | **0,77** |
| … de ellas, tras fusionar trozos (confianza 0,6) | 0,42 | 0,31 |
| Tiempo de extracción | 41 ms/pág. | 34 ms/pág. |

Por disciplina (`validation`), la proporción separada va de 0,71 (física) a 0,86 (química). La única figura multipanel biomédica de `validation` (PMC10663543 Fig. 1, micrografías sobre fondo negro) no se separa.

### Frente a cajas de panel hechas por una persona

Inigo dibujó 185 cajas de panel en 41 figuras (las 35 de `dev` y 6 de `validation`), sin ver la propuesta del sistema (`data/sfi48/reviews/panels.json`).

| Métrica | Resultado | Umbral del plan |
|---|---:|---:|
| AP con IoU ≥ 0,5 | **0,50** (`dev` 0,51; `validation` 0,41) | ≥ 0,85 ✗ |
| Precisión de letras (de las cajas bien colocadas) | 0,77 | ≥ 0,90 ✗ |
| F1 panel–sub-pie (caja, letra y sub-pie correctos) | 0,50 | ≥ 0,85 ✗ |
| Número de paneles igual al de la persona | 0,80 | |

Por confianza:

| Confianza | Figuras | Paneles con caja y letra correctas |
|---|---:|---:|
| 0,8 (corte directo) | 21 | 67 de 92 (**0,73**) |
| 0,6 (tras fusionar trozos) | 16 | 21 de 73 (0,29) |
| sin cajas (no cuadra con el pie) | 4 | 0 de 24 |

Que el número de trozos coincida con el del pie **no garantiza** que el corte sea bueno. En varias figuras de confianza 0,8 el número cuadra, pero los paneles están mal agrupados. Por ejemplo, en PMC10368530 Extended Data Fig. 1 los paneles a, b y c de arriba quedan en una misma caja y otro panel se parte en dos. Además, `dev` sirvió para ajustar el método, así que esta medida es optimista.

**Decisión** (la que prevé el plan): ninguna confianza alcanza la precisión necesaria, de modo que **las cajas de panel no se muestran** (`PUBLISH_MIN_CONFIDENCE = 0.9`). Siguen guardándose para poder medirlas. La aplicación muestra la figura completa con la lista de letras y sus sub-pies. Estos coinciden con el pie JATS dividido por el mismo parser; no hay una referencia independiente de sub-pies.

En una revisión visual de `dev`, cuando el corte da directamente el número del pie, las cajas suelen ser correctas. Ejemplo: en PMC7270115 Fig. 4 separa A–F exactamente. Cuando hay que fusionar trozos, a veces se unen paneles distintos: en PMC10368530 Fig. 4, «a» y «b» quedan juntos y otro panel se parte. Por eso la confianza es menor en ese caso.

Los ajustes se hicieron mirando solo `dev`. `validation` se usó para medir.

## Cajas de figura revisadas

Las 43 cajas `needs_manual` están revisadas (Inigo; `dev` 7/7, `validation` 11/11, `test` 25/25), todas con caja. Con ellas el evaluador mide también las figuras de escaneados y las de coincidencia baja:

| | Antes (solo cajas `auto`) | Con las revisadas |
|---|---:|---:|
| F1 de cajas a IoU ≥ 0,5 (`dev` + `validation`) | 0,996 | 0,990 |
| `dev` | 0,993 | 0,993 |
| `validation` | 1,00 | 0,986 |

El único fallo nuevo es PMC1968582 Fig. 4 (`validation`, escaneado): un esquema muy claro sobre papel escaneado. El extractor encuentra el pie pero no la región y lo avisa, así que no es una pérdida silenciosa. La caja revisada es correcta.

## Limitaciones conocidas

- **Letras sin leer:** se asignan por orden de lectura. Fallan en maquetaciones que no siguen filas, como un panel alto a la izquierda con otros dos apilados a su derecha. La solución es OCR de las letras (E03).
- **Pies sin letras:** no se separan, aunque la figura tenga varios paneles.
- **Marcadores pospuestos** («resultados del modelo (a) y los residuos (b)»): la letra va detrás de su descripción y el sub-pie asignado no es el correcto.
- **Paneles sin hueco blanco** entre ellos (imágenes pegadas): no se cortan.
- Las letras de panel que existen como texto del PDF, en figuras vectoriales, todavía no se usan.

## Coste y compatibilidad

- No se ha llamado a ningún modelo.
- El extractor pasa a 0.3.0: reprocesar un documento crea una ejecución nueva con paneles. Las explicaciones se reutilizan, porque el recorte y el pie no cambian, así que no cuesta nada.
- La aplicación necesita reiniciarse (`sfi serve`) para activar la revisión de paneles y los paneles en la vista de figura.

## Próximos pasos

1. **Usar las letras impresas como anclas**: localizar «a», «b», «c»… en la imagen (OCR, E03) y cortar alrededor de cada letra, en vez de por huecos. Es el fallo principal que muestran las cajas humanas.
2. Comparar con un detector entrenado o con las cajas de un modelo multimodal como competidor, sobre las mismas 185 cajas.
3. Completar las cajas de `validation` (quedan 26 figuras) para que la medida no dependa de `dev`.
3. **OCR de letras de panel** (E03) para dejar de depender del orden de lectura.
4. Comprobación de números visibles y rúbrica de explicaciones (resto de la etapa 5).

## Paneles anclados en sus letras (2026-10-07)

Con la capa de evidencia ([ADR 0007](../decisions/0007-ocr-evidence-layer.md)), las letras «a», «b», «c»… impresas en la figura se usan como anclas:

- **Letra arriba a la izquierda:** un panel llega hasta la siguiente letra de su fila y baja hasta la siguiente letra cuyo panel comparte columnas.
- **Letra debajo del gráfico** («(a)» centrada): cada panel va entre los puntos medios de sus vecinas de fila, desde la fila de letras anterior.
- **Una sola letra sin leer:** su posición se deduce de la rejilla que forman las demás.
- **Si faltan más letras:** se mantiene el corte por huecos (método combinado).

Medido contra las 185 cajas humanas (`scripts/eval/panel_eval.py`, ejecución `evaluation/runs/20261007-183816-panels-anchors-0.1-5d4a06d9`):

| Método | AP50 | Precisión de letras | F1 panel–sub-pie |
|---|---:|---:|---:|
| Huecos (antes) | 0,54 | 0,77 | 0,50 |
| **Combinado (ahora)** | **0,66** | **0,85** | **0,64** |
| Solo figuras con anclas (73 %): huecos → anclas | 0,50 → 0,68 | 0,83 → 0,91 | 0,52 → 0,71 |

Mejora clara, pero sigue por debajo del plan (0,85 / 0,90 / 0,85). Por eso las cajas siguen **sin mostrarse**, aunque se guardan las del método combinado (`letter-anchors/0.1`). `dev` sirvió para construir el método, así que la medida es optimista; en `validation` solo hay 6 figuras anotadas.

**Pendiente:**

- reprocesar los documentos locales para guardar los paneles anclados (sin coste, unos 10 min de OCR);
- anotar más figuras de `validation`;
- revisar los fallos restantes de las anclas.

## Revisión de los fallos y anclas 0.2 (2026-10-08)

Se revisaron una a una las 23 figuras en las que fallaba el método combinado, dibujando las cajas humanas, las del sistema y las letras encontradas. Los fallos eran de tres tipos y cada cambio responde a uno, con una regla general y no un ajuste por figura:

| Fallo observado | Ejemplo | Cambio (`letter-anchors/0.2`) |
|---|---|---|
| Se elegía una letra de un texto o de una foto | «Subclade **C** and **D**» en PMC10067821 Fig. 4; «Time (**d**)» en PMC8359101 Fig. 5 | Una letra con otra palabra pegada a su izquierda (o letras apiladas de un texto vertical) no puede ser letra de panel. Entre las demás, gana la que está sobre fondo limpio |
| Paneles irregulares | Un panel alto que ocupa dos filas (PMC8359101 Fig. 4); letras debajo de cada fila de fotos que se tocan (PMC10663543 Fig. 1) | Primero se corta por los huecos en blanco, pero solo por huecos con letras a ambos lados, con una letra pegada al hueco y con regiones de tamaño de panel. Lo que no separa ningún hueco se reparte por la rejilla de letras, que ahora elige entre «letra arriba» y «letra abajo» según cuál deja menos contenido fuera de los paneles |
| El OCR no leía letras sueltas | 30 letras en 20 figuras | Las manchas de tinta aisladas del tamaño de una letra se leen una a una, ampliadas, solo con el reconocedor. Recupera la mayoría, unos 15 ms por mancha |

Al integrarlo apareció un fallo que también afectaba al OCR general: RapidOCR conserva las opciones de cada llamada, de modo que tras leer una letra suelta (sin detección) las lecturas siguientes también se hacían sin detección. Ahora cada llamada fija todas sus opciones, y hay un test que lo comprueba.

La evaluación usa ahora exactamente el mismo camino que la aplicación (`evidence.anchor_panels`).

### Resultados

Ejecución `evaluation/runs/20261008-072717-panels-anchors-0.2-5d4a06d9`, mismas 185 cajas humanas:

| Método | AP50 | Precisión de letras | F1 panel–sub-pie |
|---|---:|---:|---:|
| Huecos | 0,54 | 0,77 | 0,50 |
| Combinado 0.1 | 0,66 | 0,85 | 0,64 |
| **Combinado 0.2** | **0,84** | **0,93** | **0,80** |
| … `dev` (35 figuras) | 0,83 | 0,93 | 0,80 |
| … `validation` (6 figuras) | 0,94 | 0,90 | 0,84 |
| Umbral del plan | 0,85 | 0,90 | 0,85 |

Ahora las letras determinan los paneles en el 83 % de las figuras (antes, el 73 %). En esas figuras, las anclas dan 0,88 / 0,97 / 0,87.

Ninguna figura empeora respecto al método 0.1. La precisión de letras supera el umbral; AP50 y F1 se quedan cerca. **No es todavía un resultado fiable**:

- `dev` sirvió para diseñar las reglas y solo hay 6 figuras anotadas en `validation`.
- **Cuatro anotaciones parecen tener las letras desplazadas:** PMC8359101 Fig. 2, 3, 6 y 7. En cada una queda una letra sin caja y sin nota, y a partir de cierto punto las cajas llevan la letra del panel anterior. Por ejemplo, en la Fig. 6 la caja «f» está sobre el panel impreso «g», y la «g» sobre el «h». No se han tocado: son la referencia humana y corregirlas a la vista del sistema sería circular. Si se excluyen, el resultado sería 0,91 / 0,96 / 0,88, pero esa cifra no cuenta hasta que la persona que anotó las revise.

**Decisión:** las cajas siguen **sin mostrarse** (`PUBLISH_MIN_CONFIDENCE = 0.9`) hasta medirlas en más figuras de `validation`.

### Fallos que quedan

- **Letras que tampoco se leen sueltas** (PMC6599010 Fig. 1 y 4, PMC10067821 Fig. 7): se usa el corte por huecos.
- **Letras impresas como marcas de una foto** (PMC8359101 Fig. 3: unas «I» de un gel ocupan el lugar de la «i»).
- **Esquemas de reacción** (PMC9608490 Scheme 1): las letras van sobre las flechas, no junto a un panel.

**Pendiente:** revisar las 4 anotaciones dudosas, anotar más figuras de `validation` y reprocesar los documentos locales para guardar los paneles 0.2.

## Medición en `validation` completa (2026-10-08)

Inigo anotó las 34 figuras multipanel de `validation` (130 paneles) y revisó las 4 anotaciones dudosas de `dev`. La Fig. 2 de PMC8359101 estaba bien: la figura no tiene letra «i», así que el error era del análisis. Las Fig. 3, 6 y 7 siguen con paneles juntados y letras desplazadas; no se han tocado. También anotó 8 figuras de `test`, que no se usan hasta la evaluación final.

Ejecución `evaluation/runs/20261008-081320-panels-anchors-0.2-5d4a06d9`; el método es el mismo, sin ningún ajuste a la vista de `validation`:

| | Figuras | AP50 | Precisión de letras | F1 panel–sub-pie |
|---|---:|---:|---:|---:|
| `dev` (usado para diseñar) | 35 | 0,83 | 0,93 | 0,80 |
| **`validation`** | **34** | **0,61** | **0,897** | **0,65** |
| … sin las 5 figuras con dos letras en un mismo gráfico | 29 | 0,67 | 0,897 | 0,71 |
| Umbral del plan | | 0,85 | 0,90 | 0,85 |

**Conclusión:** con figuras que no se usaron para diseñarlo, el método se queda lejos en la localización de paneles. La diferencia con `dev` (0,83 frente a 0,61) muestra que las reglas se ajustaron a las figuras de `dev`, como se temía. Las letras se quedan justo por debajo (0,897). Las cajas de panel **siguen sin mostrarse**.

En `validation`, los fallos principales son:

- **4 figuras sin ninguna caja:** no se leen las letras y el corte por huecos no da el número de paneles.
- **5 figuras con dos letras dentro de un mismo gráfico** (PMC11432874, PMC11332950): ahí no hay paneles que recortar.
- **Paneles mal agrupados** en figuras densas (PMC10918091 Fig. 2, PMC11720905 Fig. 1).

Mejorar a partir de estos fallos convertiría `validation` en conjunto de desarrollo. Una nueva medida limpia necesitaría entonces las figuras de `test`.
