# Etapa 1 — Carga del PDF y extracción de figuras

**Fecha:** 2026-10-06 · **Extractor:** `pdfium-heuristic` 0.1.0 · **Corpus:** piloto SFI-12 (12 artículos, 173 páginas, 77 figuras)

## Resultado

El criterio de finalización de la etapa se cumple: en los artículos de prueba se recuperan todas las figuras con su pie, y cada resultado enlaza a su página de origen con la región resaltada.

| Métrica | Resultado | Fuente de verdad |
|---|---:|---|
| Etiquetas de figura encontradas | **77/77** | JATS de PMC; lista manual en los dos escaneados |
| Figuras con región asociada | **77/77** | ídem |
| Precisión (lo reportado que es una figura esperada) | **98,7 %** | 0 etiquetas espurias, 1 región sin pie |
| Pies con similitud ≥ 0,9 frente a JATS | **66/67** | media 0,987 |
| Página correcta en figuras anotadas a mano | **13/13** | `data/stage0/expected_results.json` |
| Tiempo de extracción | **~50 ms/página** | sin renderizar recortes; con recortes a 200 dpi, 1–6 s por artículo |

Las regiones no tienen todavía cajas de referencia (*gold boxes*); su calidad se ha comprobado visualmente figura a figura. Las cajas de referencia y las métricas por IoU llegan con SFI-48 y el experimento E01.

Detalle por artículo (`python scripts/eval/stage1_eval.py`):

| Artículo | Esperadas | Etiqueta encontrada | Con región | Etiquetas espurias | Regiones sin pie | Pies ≥ 0,9 | Similitud media |
|---|---:|---:|---:|---:|---:|---:|---:|
| PMC10368530 | 16 | 16 | 16 | 0 | 0 | 15/16 | 0,946 |
| PMC8359101 | 8 | 8 | 8 | 0 | 0 | 8/8 | 1,000 |
| PMC6291436 | 5 | 5 | 5 | 0 | 0 | 5/5 | 1,000 |
| PMC9608490 | 7 | 7 | 7 | 0 | 0 | 7/7 | 0,997 |
| PMC7270115 | 6 | 6 | 6 | 0 | 0 | 6/6 | 1,000 |
| PMC6599010 | 4 | 4 | 4 | 0 | 0 | 4/4 | 1,000 |
| PMC7280498 | 5 | 5 | 5 | 0 | 0 | 5/5 | 1,000 |
| PMC8913360 | 11 | 11 | 11 | 0 | 1 | 11/11 | 1,000 |
| PMC10290119 | 4 | 4 | 4 | 0 | 0 | 4/4 | 1,000 |
| PMC7786143 | 1 | 1 | 1 | 0 | 0 | 1/1 | 1,000 |
| PMC1971560 (escaneado) | 7 | 7 | 7 | 0 | 0 | n/d | n/d |
| PMC1971548 (escaneado) | 3 | 3 | 3 | 0 | 0 | n/d | n/d |

En los escaneados el JATS no trae pies, así que su texto no se puede comparar automáticamente.

## Qué hace el sistema

```text
PDF ─► validación (cabecera, tamaño, páginas, cifrado)
    ─► original guardado por SHA-256
    ─► por página: líneas de texto + objetos gráficos visibles (pdfium)
    ─► pies candidatos (Figure/Fig./Extended Data/Scheme/Table, romanos, OCR)
    ─► regiones gráficas agrupadas sin cruzar texto de cuerpo ni pies
    ─► asignación región ↔ pie (debajo, encima, al lado, dentro de un marco)
    ─► recorte PNG + coordenadas + avisos ─► SQLite + almacén de ficheros
    ─► galería HTML con enlace a la página y al PDF
```

Cada figura guarda la página, la caja en puntos PDF y la normalizada, el texto y la caja del pie, la confianza, los avisos y su procedencia: ejecución, extractor, versión y hash de configuración. Reprocesar con la misma configuración reutiliza el resultado; con otra configuración crea una ejecución nueva sin borrar la anterior.

Los errores no se ocultan, se muestran como avisos:

| Aviso | Cuándo |
|---|---|
| `caption_without_region` | hay pie pero no se pudo asociar ninguna región |
| `region_without_caption` | región gráfica plausible sin pie |
| `missing_in_sequence` | falta un número entre figuras detectadas (p. ej. Fig. 2 entre 1 y 3) |
| `caption_may_continue` | el pie llega al final de la página y no se encontró la continuación |
| `caption_on_other_page` | el pie está en otra página («See legend on previous page») |
| `duplicate_label` | la misma etiqueta aparece como pie en varias páginas |
| `scanned_page` | página escaneada: regiones obtenidas del análisis de imagen y del OCR |
| `low_confidence`, `rotated_page` | asociación dudosa; página rotada |

## Casos difíciles resueltos

Todos aparecieron en artículos reales del piloto:

- **Pies laterales** (Springer) y **pies a dos columnas**.
- **Pies que continúan en la página siguiente** (manuscritos de autor) y pies impresos en otra página (BMC).
- **Figuras troceadas** en ~1200 teselas y figuras **vectoriales** sin imagen incrustada.
- **Form XObjects:** pdfium da las coordenadas de sus hijos en el espacio del formulario; se aplican las matrices.
- **Rutas de recorte (clip):** una editorial inserta un esquema importando una página entera de otro PDF y recortándola. El texto y los gráficos ocultos por el clip se descartan.
- **Capas de texto duplicadas** y texto fuera de la página.
- **Cabeceras y bandas laterales** («Author Manuscript» leída letra a letra).
- **Tablas junto a figuras:** las tablas se detectan como tales y no se reportan como figuras.
- **Escaneados de 1990:** regiones por análisis de tinta, descontando el texto OCR; numeración OCR «Figure I» → 1.

## Limitaciones conocidas

1. **Texto del pie en escaneados:** procede de la capa OCR de PMC y contiene errores y finales de línea cortados («Delawa», «Hong K»). No se corrige en esta etapa.
2. **Glifos mal codificados en el PDF:** la prima de N′ se extrae como «0» (N0) en PMC9608490. Es un problema de la fuente del PDF, no de la extracción.
3. **Un pie truncado** (sigue abierto en el extractor 0.2.0; los pies que absorbían el párrafo siguiente se corrigieron en la etapa 5): en la Extended Data Fig. 9 de PMC10368530, la continuación en la página siguiente empieza con una frase en mayúscula y otro tamaño de letra, y no se distingue de un párrafo nuevo. La figura no lleva aviso porque el título del pie termina en punto y no se encontró continuación.
4. **Una región sin pie falsa:** la lista de comprobación del *Reporting Summary* de Nature (PMC8913360, p. 17).
5. **Bordes de recorte:** en algún escaneado se recorta ligeramente el borde de una leyenda; algún rótulo de eje puede quedar justo en el borde.
6. **Heurísticas calibradas en 12 artículos.** Los umbrales (hueco de agrupación 16 pt, unión de texto 10 pt, etc.) pueden no generalizar. Son configurables (`RegionConfig`) y forman parte del hash de configuración de cada ejecución.
7. **Páginas rotadas:** se avisan, pero las coordenadas no se corrigen.
8. **Sin segmentación de paneles:** las figuras multipanel se tratan como una sola región (etapa 5).

## Cómo reproducirlo

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"     # Windows; en Linux/macOS: .venv/bin/
python scripts/corpus/fetch_pmc_oa.py data/stage0/selection.json --out-dir data/raw/stage0 --manifest data/stage0/manifest.json
sfi process data/raw/stage0/*.pdf --report      # galería en data/local/reports/index.html
python scripts/eval/stage1_eval.py              # métricas de esta página
pytest                                          # 30 tests
```

## Siguiente paso

Etapa 2: enviar cada figura y su pie a `gpt-6-luna` con salida estructurada, siguiendo [EXPLANATION_SCHEMA.md](../EXPLANATION_SCHEMA.md). Completada: ver [stage2-explanation.md](stage2-explanation.md).
