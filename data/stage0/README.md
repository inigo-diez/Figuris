# Piloto SFI-12 (etapa 0)

Muestra pequeña para comprobar el prototipo (etapas 1–3) con artículos reales. Corresponde al piloto SFI-12 de [research/experiments.md](../../research/experiments.md) y no sustituye a SFI-48.

## Contenido del repositorio

| Archivo | Uso |
|---|---|
| `selection.json` | PMCIDs elegidos y por qué (disciplina, tipo de PDF, tipos de figura), licencias admitidas y reservas |
| `manifest.json` | generado: DOI, cita, licencia y su URL, copyright, atribución, excepciones por figura, URL de descarga, SHA-256 y fecha |
| `expected_results.json` | resultados esperados: inventario por artículo y 13 figuras anotadas a mano |

Los PDF y XML **no se versionan**. Se descargan en `data/raw/stage0/` (ignorado por git):

```bash
python scripts/corpus/fetch_pmc_oa.py data/stage0/selection.json \
    --out-dir data/raw/stage0 --manifest data/stage0/manifest.json
```

El script usa el bucket oficial de PMC en AWS Open Data, rechaza licencias fuera de `allowed_licenses` (CC BY) y artículos retractados, y verifica el MD5 publicado por PMC. Es reanudable: no vuelve a descargar ficheros válidos.

## Licencias y atribución

Los 12 artículos están bajo CC BY 4.0. La atribución de cada uno está en `manifest.json`. Cualquier figura o fragmento que se muestre fuera del uso local (capturas, demo pública, documentación) debe incluir esa atribución.

`figure_license_exceptions` marca figuras con créditos propios, pendientes de revisión manual:

| Artículo | Figuras | Motivo | Decisión provisional |
|---|---|---|---|
| PMC8913360 | Fig. 1, Fig. 6 | créditos a Hans Sell y Michelle O’Reilly, que no son autores | uso local permitido; excluir de capturas y demos públicas hasta revisar |

## Cobertura

| PMCID | Disciplina | PDF | Figuras | Qué pone a prueba |
|---|---|---|---:|---|
| PMC10368530 | biomedicina | manuscrito de autor | 16 | figuras al final, pies que continúan en la página siguiente, banda lateral “Author Manuscript” |
| PMC8359101 | biomedicina | born-digital | 8 | multipanel denso: western blot, inmunofluorescencia, estructuras |
| PMC6291436 | biomedicina | born-digital | 5 | imagen médica (RM), pie lateral |
| PMC9608490 | química | born-digital | 7 | estructuras moleculares; figuras troceadas en ~1200 teselas |
| PMC7270115 | materiales | born-digital | 6 | SEM con barras de escala, XRD/FTIR, varias figuras por página |
| PMC6599010 | física | born-digital | 4 | STEM, curvas J-V, tabla pegada a la figura |
| PMC7280498 | medio ambiente | born-digital | 5 | mapas; figura recortada en el propio PDF |
| PMC8913360 | medio ambiente | born-digital | 11 | gráficos complejos sin letras de panel |
| PMC10290119 | informática | born-digital | 4 | diagramas vectoriales de arquitectura |
| PMC7786143 | ciencias sociales | born-digital | 1 | barras apiladas; 11 tablas que no son figuras |
| PMC1971560 | biomedicina | escaneado (1990) | 7 | microscopía escaneada; JATS incompleto; 4 figuras en una página |
| PMC1971548 | biomedicina | escaneado (1990) | 3 | gráficos escaneados no declarados en JATS; tabla en imagen |

Total esperado: 77 figuras. Los conteos proceden del JATS, corregidos a mano en los escaneados.

Reservas (en `selection.json`, no descargadas): PMC8448759, redundante con PMC10290119, y PMC4887260, que es CC0 y no CC BY.

## Limitaciones conocidas

- Siete disciplinas, pero sin astronomía ni ciencias sociales cuantitativas fuera de encuestas.
- Todo en inglés.
- Las 13 figuras anotadas son un borrador de una sola persona. Se revisarán antes de usarlas como gold standard.
