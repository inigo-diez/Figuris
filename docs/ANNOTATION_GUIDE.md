# Guía de anotación (etapa 5)

Guía para la revisión humana que se hace en la aplicación (`sfi serve` → **Revisión**): cajas de figura, paneles y explicaciones. Cumple el paso 1 del protocolo de [experiments.md](../research/experiments.md): escribir la guía antes de anotar `validation`.

Cada anotación se guarda con el nombre del revisor en `data/sfi48/reviews/` (versionado). `scripts/eval/review_summary.py` resume el avance y las métricas; `scripts/eval/sfi48_eval.py` usa las cajas revisadas.

## 1. Cajas de referencia

**Qué se revisa:** las figuras de SFI-48 cuya posición no se pudo fijar automáticamente (`needs_manual`): imágenes de PMC localizadas con coincidencia baja y figuras de artículos escaneados. La pantalla muestra la página del PDF, la imagen que publica PMC, el pie del JATS y las páginas donde aparece la etiqueta. **Nunca muestra lo que detecta el sistema**, para que la referencia no se contamine con su salida.

**Cómo dibujar la caja:**

- Rodea solo la figura: todos sus paneles, ejes, leyendas, barras de escala y rótulos de panel.
- No incluyas el pie, el título de la figura ni el texto del artículo.
- Si la figura tiene un marco, la caja va por el borde exterior del marco.
- Si ocupa dos páginas, marca la caja de la página principal y explícalo en la nota.

**Decisiones:**

| Decisión | Cuándo |
|---|---|
| **Guardar caja** | la figura está en el PDF y la caja la rodea según las reglas anteriores |
| **No está en el PDF** | la figura no existe en este PDF (solo en la versión web) o la etiqueta del borrador OCR es errónea |
| **Dudosa** | no se puede decidir; la nota es obligatoria. Mejor «dudosa» que forzar una respuesta (paso 5 del protocolo) |

**Propuesta automática:** es la posición donde se localizó la imagen de PMC, no la salida del sistema. Se puede partir de ella y ajustarla. Para la doble anotación ciega, desactiva «Mostrarla»; la revisión registra si estaba visible (`proposal_shown`).

**Figuras que faltan:** en los escaneados, la lista de figuras es un borrador del texto OCR. Si encuentras una figura que no está en la lista, añádela con su etiqueta.

**Acuerdo:** dos revisiones de la misma figura concuerdan si toman la misma decisión y, si es una caja, están en la misma página con IoU ≥ 0,75. Si no concuerdan, la figura queda `disputed` y no se usa para medir hasta adjudicarla. Objetivo del protocolo: IoU mediana ≥ 0,90.

## 2. Paneles

**Qué se revisa:** las figuras cuyo pie nombra dos o más paneles (a, b, c… o A, B, C…). Primero las de `dev` y `validation`. La pantalla muestra la página con la figura recuadrada en gris y la lista de letras con su parte del pie. **No muestra los paneles que propone el sistema.**

**Cómo dibujar:**

- Elige una letra y arrastra sobre la página. Al soltar se pasa sola a la siguiente letra sin caja.
- La caja de un panel incluye su gráfico o imagen, sus ejes, su leyenda propia y su letra.
- Una leyenda común a varios paneles no pertenece a ninguno.
- Si un panel no se puede delimitar (está dentro de otro o no se distingue), déjalo sin caja y explícalo en la nota.
- Si la letra se refiere a varias imágenes, la caja las rodea todas.

**Decisiones:** **Guardar** (al menos un panel dibujado) o **Dudosa** (con nota).

**Medidas** (`sfi48_eval.py`): AP con IoU ≥ 0,5, precisión de letras, F1 panel–sub-pie y exactitud del número de paneles. Umbrales del plan: mAP50 ≥ 0,85, precisión de letras ≥ 0,90 y F1 panel–sub-pie ≥ 0,85.

## 3. Explicaciones (rúbrica)

Cada afirmación se puntúa de 0 a 2 en los seis criterios del [plan de evaluación](EVALUATION_PLAN.md). Hay que compararla con la figura, el pie y los fragmentos del artículo que recibió el modelo, que la pantalla muestra a la izquierda.

| Criterio | 0 | 1 | 2 |
|---|---|---|---|
| **Corrección**: ¿es verdad según la figura y el artículo? | falsa | en parte | correcta |
| **Respaldo**: ¿la evidencia que la acompaña basta para hacerla? | sin respaldo | parcial | respaldada |
| **Cita**: ¿la cita existe, está donde se indica y dice lo que se afirma? | errónea | imprecisa | exacta |
| **Tipo**: ¿es correcto marcarla como observado, según los autores, inferencia o incierto? | equivocado | discutible | correcto |
| **Calibración**: ¿la seguridad corresponde a la evidencia? | mal calibrada | algo | bien calibrada |
| **Utilidad**: ¿ayuda a entender la figura? | no aporta | algo | útil |

- **Cita = N/A** cuando la afirmación solo se apoya en la imagen. Si cita algo, se puntúa aunque sea la imagen lo que la respalda.
- «Todo bien» pone todo a 2 (y N/A en la cita si no cita texto ni pie); después se corrige solo lo que falle.
- **Errores críticos:** ID, cita o referencia inventada; valor inventado; contradicción clara con la figura o el artículo; falsa certeza (por ejemplo, clínica). Uno basta para invalidar la explicación aunque el resto esté bien.
- Las puntuaciones pertenecen al contenido de la explicación: si al reprocesar se reutiliza la misma explicación, se conservan; si se genera una nueva, hay que puntuarla de nuevo.

**Métricas que salen de la rúbrica** (`review_summary.py`): tasa de afirmaciones sin respaldo (respaldo = 0), también solo en las de confianza alta (umbral ≤ 0,02); precisión de citas (cita = 2 entre las que citan; umbral ≥ 0,95); medias por criterio y errores críticos. La **completitud de citas** y la **contestabilidad** necesitan otras anotaciones (fuentes que debería citar cada afirmación; preguntas y respuestas) y siguen pendientes.

### Revisión con otra IA

Cuando no hay un revisor experto en el tema, se puede pedir la primera revisión a otro modelo:

1. `python scripts/eval/export_judge_packet.py` genera lotes en PDF en `data/local/revision_ia/<fecha>/`. Cada lote incluye la figura, el pie, los fragmentos del artículo, las afirmaciones y las instrucciones con el formato de respuesta. Junto a ellos se genera `claves.json`.
2. Cada lote se entrega a la otra IA y su respuesta JSON se guarda en un archivo.
3. `python scripts/eval/import_judge_scores.py respuesta.json --keys claves.json` comprueba la respuesta (todas las afirmaciones, valores válidos, nota cuando algo falla) y la guarda con `annotator_kind: llm`.

Estas puntuaciones son el juicio de un modelo, no una referencia humana: `review_summary.py` las informa aparte (`claims_llm_judge`). Antes de usarlas se comprueban sus objeciones contra el artículo, sobre todo los errores críticos y las puntuaciones de 0.
