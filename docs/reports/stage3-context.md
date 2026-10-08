# Etapa 3 — Contexto del artículo y evidencia

**Fecha:** 2026-10-06 · **Modelo:** `gpt-6-luna` · **Prompt:** `figure-explain/0.3` · **Esquema:** `explanation/0.2` · **Validador:** `validate/0.4` · **Texto:** `text/0.1`, `mentions/0.1`, `context/0.1` · **Corpus:** piloto SFI-12 (78 regiones)

## Resultado

El criterio de finalización de la etapa se cumple: las afirmaciones principales de cada explicación pueden rastrearse hasta la figura, el pie o un fragmento concreto del artículo, con su página. Hay **309 resultados principales y todos son rastreables**.

| Métrica | Resultado | Referencia |
|---|---:|---|
| Figuras mencionadas en el texto y detectadas | **67/67** | `<xref>` del JATS de PMC |
| Menciones detectadas | ≥ 216/227 (95 %) | ídem; JATS cuenta cada panel por separado, así que la cifra real es más alta |
| Figuras que reciben contexto del artículo | **77/78** | la que falta es una región sin etiqueta |
| Pasajes enviados por figura | 1,7 de media (~1700 caracteres) | límite: 6000 caracteres |
| Citas del texto (`text_span`) | 270, de las que **268** se localizan con página y sección | las 2 restantes están en explicaciones marcadas `invalid` |
| Figuras que citan el texto del artículo | 77/78 | |
| Resultados principales rastreables | **309/309** | |
| Explicaciones válidas (`ok`) | **75/78** | 3 marcadas como no fiables por citas no literales |
| Coste del piloto | **0,12 USD** (0,0016 USD por figura) | 3982 tokens de entrada y 2368 de salida de media |
| Latencia por figura | mediana 16,5 s · p90 22,5 s | |

Gasto total acumulado del proyecto: **0,35 USD de 5 USD**. Incluye las etapas 2 y 3, las pruebas y la ejecución con el prompt 0.2, que se repitió (ver más abajo).

## Qué aporta el contexto

La hoja de revisión de las 13 figuras anotadas a mano (`scripts/eval/stage3_eval.py`) la revisó el asistente (Claude) y está **pendiente de revisión humana**:

- **Datos que solo están en el texto.** De los cuatro datos esperados que vienen de párrafos, no de tablas, se recuperan dos completos y uno parcial:
  - los coeficientes Dice 0,92/0,95 de la RM (p. 5);
  - las partículas «more or less spherical» y agrupadas (p. 5);
  - la unidad asimétrica del compuesto 5, pero no su grupo espacial.

  El cuarto (las capas de la red CNN de Spec2Mol) está en un párrafo de Métodos que no menciona «Fig. 4», así que no se envía. Los dos datos que viven en tablas (PCE del 17,39 % y fórmula empírica) quedan fuera del alcance de esta etapa.
- **Lo que antes era incierto ahora se atribuye a los autores, con cita y página:** el tamaño de cristalito (2,72 nm), la asignación de bandas FTIR, qué fragmentos de PARP1 se unen y la interpretación demográfica de la Peste Negra. Las afirmaciones `uncertain` bajan de 100 a 75 y las `author_stated` suben de 215 a 336.
- **Detecta incoherencias del propio artículo.** En PMC7280498, el texto valida los años «1995, 2002, 2004 y 2013», pero la figura y su pie dicen 2001. El modelo lo señala citando ambas fuentes.
- **Relaciona la figura con el artículo.** El nuevo campo `role_in_article`, el papel de la figura en el artículo, está relleno en las 78 explicaciones y apoyado en afirmaciones con cita.
- **Lo visual no cambia.** Persiste el error de lectura de PMC1971548 Fig. 1 (toma el segmento de Wilms por la tasa total de Nigeria) y sigue sin mencionarse que O4 es un átomo aparte. La parte visual no se ha vuelto a puntuar elemento por elemento; una comprobación por muestreo da el mismo panorama que en la etapa 2, con pequeñas variaciones entre ejecuciones.

## Cómo funciona

```text
extracción (etapa 1)
    ─► líneas de cuerpo (sin pies, texto de figuras ni márgenes)
    ─► párrafos: espacio vertical, sangría tras frase terminada, última línea corta,
       encabezados de sección; un párrafo que sigue en otra columna o página es un solo pasaje
    ─► secciones (Results, Methods…) y bibliografía/declaraciones marcadas como back matter
    ─► menciones: «Fig. 2C,D», «Figs. 2–4», «Extended Data Figs. 1 and 2», «Figure I», paneles
    ─► SQLite: pasajes con página, caja por columna y menciones (misma ejecución que las figuras)

análisis (etapa 2 + contexto)
    ─► pasajes que mencionan la figura, sin back matter; los largos se recortan a las frases
       que rodean la mención; si no caben, se descartan primero los de Métodos y se avisa
    ─► <passage id="p12" page="4" section="Results"> … </passage> como dato, no instrucción
    ─► evidencia text_span con passage_id y cita literal
    ─► validación de cada cita; página, sección y posición de cada cita en el pasaje
    ─► galería: cada cita enlaza a su pasaje, resaltado en la página
```

- **Texto** ([text.py](../../src/sfi/extract/text.py)): se reutiliza la clasificación de líneas de la etapa 1, sin volver a leer el PDF. En páginas con mucha letra pequeña (tablas, rótulos), la etapa 1 subestimaba el tamaño del cuerpo del texto y algunos párrafos reales quedaban como texto de figura; ahora se recuperan usando el tamaño de cuerpo del documento. Los caracteres fuera del plano básico de Unicode, que pdfium devuelve como pares sustitutos UTF-16, se recomponen. Resultado: 1060 pasajes en el piloto, 1050 con sección.
- **Menciones** ([mentions.py](../../src/sfi/context/mentions.py)): las figuras suplementarias conservan su prefijo, así que nunca se confunden con las principales. Una «Figure 10.5 mm» no se toma por mención.
- **Contexto** ([select.py](../../src/sfi/context/select.py)): solo pasajes con mención explícita. Lo enviado forma parte de la clave de caché: si cambia el texto, el análisis es nuevo.
- **Contrato** `explanation/0.2` ([EXPLANATION_SCHEMA.md](../EXPLANATION_SCHEMA.md)): añade la evidencia `text_span` con `passage_id` y `role_in_article`. Cada análisis guarda los pasajes enviados (con sus segmentos de página) y las citas localizadas (`SpanRef`: pasaje, página, sección y posiciones de inicio y fin).

## Validación de la evidencia

Reglas nuevas o ampliadas ([validate.py](../../src/sfi/analysis/validate.py)):

| Regla | Gravedad |
|---|---|
| la cita `text_span` debe aparecer literalmente en el pasaje citado | error (`quote_not_in_text`) |
| la cita está en otro pasaje del contexto | aviso (`wrong_passage`); se localiza en el correcto |
| el pasaje citado no se envió y la cita no está en ninguno | error (`unknown_passage`) |
| cita formada por frases literales, en orden, pero no contiguas | aviso (`quote_with_gaps`) |
| una afirmación `author_stated` debe citar el pie o un pasaje | error |
| los números de una afirmación de los autores deben estar en el pie o en los pasajes que cita | error |
| todo resultado principal debe tener evidencia | error (`untraceable_finding`) |
| falta el papel de la figura en el artículo | aviso |

Los cambios de reglas revalidan en local los análisis guardados, sin coste, y los de prompt generan análisis nuevos.

### Lo que se encontró y cómo se corrigió

La primera ejecución completa, con el prompt 0.2, dejó **12 explicaciones `invalid` de 78**. Se revisaron una a una:

| Causa | Casos | Decisión |
|---|---:|---|
| el modelo junta frases literales del pie saltándose texto, sin «…» | 3 | se aceptan con aviso: no se inventa nada |
| número que está en el pie, pero no en el pasaje citado (señalaba la discrepancia 2001/2002) | 1 | regla corregida: el pie siempre cuenta como fuente de los autores |
| referencias a afirmaciones que no existen | 3 | prompt 0.3: cada id debe corresponder a una afirmación escrita |
| cita con una palabra cambiada («and» → «it», «and» añadido, una errata del artículo «corregida») | 3 | se mantiene como error; prompt 0.3: no corregir nada al citar |
| reconstruye una frase que el OCR intercala entre dos columnas | 1 | se mantiene como error; prompt 0.3: citar solo lo que aparece |

Con el prompt 0.3 quedan **3 `invalid`**, y las tres son errores reales que el validador detecta: una cita con una palabra cambiada, una nota de extracción de nuestro propio prompt citada como si fuera el pie, frases citadas en otro orden e intentos de citar el texto intercalado del escaneado.

## Limitaciones conocidas

1. **Solo menciones explícitas.** Los párrafos que hablan de la figura sin nombrarla, como suele pasar en Métodos, no se envían. Sí se envían los que dicen «Fig. 4».
2. **Las tablas no se leen.** Sus valores no entran en el contexto aunque el texto remita a ellas.
3. **Escaneados a dos columnas.** En PMC1971548 la capa OCR de PMC mezcla las líneas de las dos columnas en algunas páginas. El texto resultante no es citable y el validador lo rechaza; no se intenta reparar.
4. **Párrafos a través de tablas.** Un párrafo interrumpido por una página de tablas puede partirse en dos pasajes. Cada mitad se envía solo si menciona la figura.
5. **Encabezados imperfectos.** Algunas líneas en negrita de la portada (títulos, afiliaciones) pueden tomarse como sección; solo afecta a la etiqueta de sección mostrada.
6. **Variabilidad.** Al repetir con otro prompt cambian detalles visuales menores. No se ha medido la variabilidad entre llamadas con el mismo prompt.
7. **Revisión manual de 13 figuras** hecha por el asistente; falta la revisión humana y un juez automático.

## Cómo reproducirlo

```bash
sfi process data/raw/stage0/*.pdf --report     # extrae figuras y texto, explica y genera la galería
python scripts/eval/stage3_eval.py             # menciones vs JATS, trazabilidad, hoja de revisión
pytest                                         # 86 tests, sin red
```

## Siguiente paso

Etapa 4: aplicación utilizable. Subir un PDF desde una interfaz web, ver el progreso y navegar entre figura, explicación y página de origen. Completada: ver [stage4-web-app.md](stage4-web-app.md).
