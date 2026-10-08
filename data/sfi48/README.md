# SFI-48 — corpus de evaluación

Corpus de 48 artículos de PMC Open Access para medir extracción, contexto y explicaciones ([research/experiments.md](../../research/experiments.md), [EVALUATION_PLAN.md](../../docs/EVALUATION_PLAN.md)). Este directorio versiona solo metadatos y anotaciones; los PDF y JATS se descargan a `data/raw/sfi48/`, que no se versiona.

## Composición

| Split | Artículos | Figuras | Uso |
|---|---:|---:|---|
| `dev` | 12 | 77 | el piloto SFI-12, usado para desarrollar el sistema |
| `validation` | 12 | 73 | ajuste y comparación de configuraciones |
| `test` | 24 | 142 | **congelado**: no se usa para ajustar; cada evaluación se registra en `test_runs.log` |
| **Total** | **48** | **292** | |

- **Disciplinas:** 6 artículos nuevos por disciplina (2 de validación y 4 de test): biomedicina, química y materiales, física y astronomía, medio ambiente y geociencias, informática e ingeniería, y ciencias sociales. Se añaden los 12 del piloto en `dev`.
- **Licencias:** las 48 son CC BY, comprobadas artículo por artículo con los metadatos de PMC (`manifest.json`). Hay 5 figuras con créditos de terceros pendientes de revisar (`figure_license_exceptions`).
- **Escaneados:** 6 (2 del piloto y 4 nuevos de *Br J Cancer* 1990–1995).

## Selección reproducible

`scripts/corpus/select_sfi48.py` lanza una búsqueda fija en PMC por estrato (E-utilities, filtro `cc by license`), baraja los resultados con la semilla `20261006` y acepta candidatos en ese orden si:

- tienen licencia CC BY o CC0, no están retractados y tienen PDF y JATS;
- tienen entre 3 y 10 figuras;
- tienen al menos una figura multipanel según el pie;
- si son escaneados, PMC los marca como OCR histórico y su texto cita al menos 3 figuras.

Los splits se asignaron dentro de cada estrato **antes** de ejecutar el sistema sobre estos artículos. Las consultas y los recuentos están en `selection.json` (`search_log`).

```bash
python scripts/corpus/select_sfi48.py                     # selection.json
python scripts/corpus/fetch_pmc_oa.py data/sfi48/selection.json \
    --out-dir data/raw/sfi48 --manifest data/sfi48/manifest.json
pip install -e ".[eval]"
python scripts/corpus/build_reference.py                  # expected_figures.json
python scripts/eval/sfi48_eval.py                         # dev + validation (con las cajas revisadas)
python scripts/eval/review_summary.py                      # avance y métricas de la revisión humana
```

## Referencia (`expected_figures.json`)

Se construye a partir de datos de PMC, no de la salida del sistema:

- **etiquetas, pies y menciones en el texto:** del JATS (`<fig>`, `<xref ref-type="fig">`);
- **página y caja:** se localiza en el PDF la imagen de cada figura publicada por PMC, mediante correlación normalizada multiescala. Se acepta con una puntuación ≥ 0,6. En el piloto coincide con las 11 páginas anotadas a mano que se pudieron localizar;
- **paneles:** borrador a partir de los marcadores del pie;
- **escaneados:** el JATS no enumera sus figuras. Las etiquetas salen del texto OCR (borrador) o de la revisión manual del piloto.

| Estado | Figuras | Significado |
|---|---:|---|
| `auto` | 249 | caja localizada con buena coincidencia; se usa para medir IoU |
| `needs_manual` | 43 | coincidencia baja o figura de escaneado; **pendiente de revisión humana** |

### Revisión humana (`reviews/`)

Las figuras `needs_manual` se revisan en la aplicación (`sfi serve` → **Revisión**), siguiendo [ANNOTATION_GUIDE.md](../../docs/ANNOTATION_GUIDE.md). La pantalla no muestra la salida del sistema.

- `reviews/boxes.json`: una revisión por figura y revisor (caja, «no está en el PDF» o «dudosa», con nota). `expected_figures.json` no se edita: `sfi.review.load_reference` aplica las revisiones encima, y el evaluador mide el IoU contra las cajas `auto` y `reviewed`.
- `reviews/panels.json`: la caja de cada panel (a, b, c…) de las figuras multipanel, dibujada sin ver la propuesta del sistema. Es la referencia de paneles de E02.
- `reviews/claims.json`: puntuaciones de la rúbrica por afirmación, con el modelo, la versión del prompt y el texto de cada afirmación.

Si dos revisores discrepan, la figura queda `disputed` hasta adjudicarla. La doble anotación del 25 % sigue pendiente.

## Desviaciones respecto a la matriz objetivo

| Objetivo | Real | Comentario |
|---|---|---|
| 8 escaneados | 6 | en PMC OA casi solo hay escaneados biomédicos con licencia CC BY |
| ≥ 45 % de figuras multipanel | ≥ 41 % (121/292, estimado por el pie) | la estimación por el pie es un mínimo; se confirmará al anotar los paneles |
| 8 artículos en otros idiomas | 0 | primera versión en inglés |
| Variedad de revistas y años | 17 de *Sci Rep*; 30 de 48 de 2023–2024 | la búsqueda prioriza resultados recientes; ampliar en SFI-48 v2 |
| Disciplinas bien asignadas | alguna discutible | PMC10397266 (planta de para-xileno) quedó en ciencias sociales por la búsqueda del estrato |
| 8 PDF born-digital «difíciles» | sin etiquetar | se clasificarán al revisar la referencia |
