# Plan de evaluación

El protocolo operativo completo está en [../research/experiments.md](../research/experiments.md). Este documento resume la política del producto.

## Objetivo

Medir cada componente de forma aislada y el sistema completo sin ocultar fallos detrás de una puntuación agregada. Toda selección de parser, OCR, modelo o índice debe producir un `EvaluationRun` reproducible.

## Corpus

SFI-48: 48 artículos, al menos 240 figuras, seis disciplinas, PDFs limpios/difíciles/escaneados y una cuota mínima del 45% de figuras multipanel. División 12 `dev`, 12 `validation` y 24 `test` congelados.

La primera fuente será PMC OA con JATS y licencias CC BY/CC0 verificadas por artículo. ArXiv se usa solo cuando la licencia del submission permita el uso previsto. No se redistribuirá un PDF por el mero hecho de ser públicamente accesible.

## Capas y métricas

| Capa | Métricas principales |
|---|---|
| Parsing/layout | reading-order edit distance, block mAP, text completeness, silent-loss rate |
| Figura/caption | P/R/F1 a IoU, mAP, caption association, NED, label/page accuracy |
| Paneles | mAP50:95, count accuracy, label accuracy, panel-subcaption F1 |
| OCR | CER/WER, entity accuracy, box IoU, calibration |
| Elementos visuales | axes/units/legend/scale-bar field accuracy y completeness |
| Contexto | Recall@k, MRR, nDCG, context precision, tokens irrelevantes |
| QA | exact/F1, tolerancia numérica, answerability, rúbrica humana |
| Grounding | citation precision/recall, claim support, region accuracy, unsupported claims |
| Sistema | p50/p95, throughput, coste, RAM/VRAM, fallos, cache hit, reanudación |
| Seguridad | containment rate, egress no autorizado, resource-limit enforcement |

## Rúbrica humana de claims

Cada afirmación se puntúa de 0 a 2 en:

- corrección;
- soporte de evidencia;
- precisión de la cita;
- distinción observación/autor/inferencia;
- calibración de incertidumbre;
- utilidad para la pregunta.

Un error crítico —ID inventado, valor fabricado, contradicción clara o falsa certeza clínica— invalida la respuesta aunque la media sea alta.

## Gates provisionales

- figura F1 >= 0,90 y caption association >= 0,95;
- panel mAP50 >= 0,85 y panel-subcaption F1 >= 0,85;
- context Recall@5 >= 0,90;
- answerability >= 0,90;
- citation precision >= 0,95 y completeness >= 0,90;
- unsupported-claim rate <= 0,02 en respuestas de alta confianza;
- cero pérdidas silenciosas y cero referencias inventadas en el conjunto test.

Estos umbrales son objetivos iniciales, no resultados. Se revisarán una vez obtenida la distribución de dificultad del piloto, sin reducirlos para maquillar una regresión.

## Reproducibilidad

Cada run conserva versiones, config, prompts, hardware, seed, hashes de inputs/outputs, métricas por estrato y errores. `test` no se usa para tuning y su ejecución se registra. Los resultados se comparan con intervalos de confianza y, cuando aplique, tests pareados por documento.

## Benchmarks externos

- OmniDocBench para parsing interno de investigación;
- PDFFigures2 evaluation para figura/caption;
- DocLayNet/PubLayNet para layout;
- SPIQA y SciVQA para QA científica;
- ChartQAPro y ChartBench para chart reasoning;
- ImageCLEF/alternativas recientes para paneles, sujetos a licencia.

Los benchmarks externos complementan, pero no sustituyen, SFI-48 ni el análisis por disciplina.

