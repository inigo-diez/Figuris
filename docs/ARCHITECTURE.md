# Arquitectura inicial propuesta

**Estado:** propuesta para validar con E01–E06.  
**Fecha:** 2026-10-06.

## Decisión central

El sistema será orientado a artefactos y procedencia. Ningún parser, OCR o modelo será la fuente de verdad por sí solo. La fuente de verdad es un modelo documental normalizado que conserva el original, cada transformación, coordenadas, versión del componente y relación entre evidencia y afirmaciones.

```text
                            +------------------+
PDF / JATS / HTML --------->| Ingesta segura   |
                            +---------+--------+
                                      |
                         original + hash + licencia
                                      |
          +---------------------------+---------------------------+
          |                           |                           |
          v                           v                           v
  Parser de layout             Parser científico          Capa PDF nativa
     (Docling)                    (GROBID)              (pikepdf/pdfium)
          |                           |                           |
          +---------------------------+---------------------------+
                                      v
                    Reconciliación a Document IR versionado
                                      |
          +---------------------------+----------------------------+
          |             |             |             |              |
          v             v             v             v              v
      Figuras        Paneles          OCR        Menciones       Secciones
          |             |             |             |              |
          +---------------------------+----------------------------+
                                      v
                          Evidence Graph / Bundles
                                      |
                  +-------------------+-------------------+
                  v                                       v
          Índices texto/metadata                  Índice visual opcional
                  +-------------------+-------------------+
                                      v
                      Análisis multimodal estructurado
                                      |
                                      v
                     Validador de claims, citas y confianza
                                      |
                              +-------+-------+
                              v               v
                             API              UI
```

## Rutas de ingesta

1. **Fuente estructurada disponible:** JATS/XML o HTML editorial aporta jerarquía, captions y enlaces; el PDF sigue siendo la fuente visual y geométrica.
2. **PDF born-digital:** extraer texto/objetos nativos, ejecutar parsers y renderizar regiones a resolución controlada.
3. **PDF escaneado:** preservar original, crear derivado OCR explícito y procesar ambos; nunca sustituir silenciosamente el original.

Todos los inputs se validan por magic bytes, tamaño, páginas, cifrado y límites de recursos. El procesamiento ocurre en contenedores sin red por defecto.

## Document IR

Entidades mínimas:

- `Document`, `DocumentVersion`, `SourceFile`, `Page`;
- `Section`, `TextBlock`, `Sentence`, `Mention`;
- `Figure`, `Panel`, `Caption`, `Subcaption`, `VisualElement`;
- `Artifact` para imagen nativa, render, crop, OCR y preview;
- `Evidence`, `EvidenceBundle`, `Claim`, `Citation`;
- `ProcessorRun`, `ModelRun`, `EvaluationRun`.

Cada entidad derivada incluye:

```text
id, document_id, source_artifact_id
page_index, bbox_normalized, bbox_original, coordinate_space
content_hash, schema_version
producer, producer_version, config_hash, created_at
confidence, warnings, parent_ids
```

Las IDs son estables dentro de una versión del documento. Los resultados de procesadores nunca sobrescriben artefactos previos; crean una nueva revisión.

## Interfaces de componentes

Los adaptadores internos, no las clases de terceros, definen los contratos:

```python
class DocumentParser(Protocol):
    def parse(self, source: SourceArtifact, config: ParserConfig) -> ParsedDocument: ...

class FigureExtractor(Protocol):
    def extract(self, document: ParsedDocument) -> list[FigureCandidate]: ...

class PanelSegmenter(Protocol):
    def segment(self, figure: FigureArtifact) -> list[PanelCandidate]: ...

class OcrEngine(Protocol):
    def recognize(self, image: ImageArtifact, regions: list[Region]) -> OcrResult: ...

class MultimodalModel(Protocol):
    def generate(self, request: AnalysisRequest) -> AnalysisResponse: ...
```

Los contratos se materializarán con Pydantic/JSON Schema y tests de conformidad. Cada adaptador declara capacidades, coste, límites, datos que abandona el entorno y versión del modelo.

## Pipeline por etapas

| Etapa | Input | Output persistido | Condición de reejecución |
|---|---|---|---|
| ingest | archivo/URL autorizada | original, hash, metadata y licencia | cambia el contenido |
| parse | original | outputs crudos + IR por parser | cambia parser/config |
| reconcile | varios parses | IR canónico + conflictos | cambia regla/schema |
| figures | IR + PDF | regiones, nativos, renders, captions | cambia extractor/render |
| panels | figura | paneles, labels, subcaptions | cambia modelo/threshold |
| OCR | regiones | tokens, cajas, confianza | cambia motor/config |
| context | IR + menciones | evidence bundles | cambia retriever/config |
| analyze | bundle + modelo | respuesta estructurada | cambia prompt/model/schema |
| validate | claims + evidence | claims aceptados/rechazados | cambia política/validador |
| index | entidades aprobadas | índices versionados | cambia embedding/index |

El DAG es estático y explícito durante las primeras fases. Un framework de agentes no aporta valor al parsing determinista. Para ejecución local basta una cola de jobs con reintentos, idempotencia y estado; evaluar Temporal solo si aparecen workflows largos que requieren compensaciones y recuperación compleja.

## Extracción y reconciliación

### Hipótesis de baseline

- Docling: layout, reading order, tablas/pictures y representación general.
- GROBID: estructura científica, secciones, captions, referencias y mentions/callouts.
- pikepdf: imágenes incrustadas sin recodificación.
- pypdfium2: render completo de página/región.
- PDFFigures2: baseline externo de figura/caption.

El reconciliador alinea candidatos por página, solapamiento, caption normalizado y label. Los conflictos se conservan con scores; una selección canónica requiere reglas versionadas. La interfaz muestra advertencias en resultados ambiguos.

### Figuras multipanel

Ruta escalonada:

1. detectar si la figura es compuesta;
2. baseline geométrico de huecos/connected components;
3. detector de paneles entrenado o adaptado;
4. OCR de etiquetas y matching espacial;
5. separación de subcaptions y matching bipartito panel-subcaption;
6. fallback a figura completa si la confianza calibrada es insuficiente.

No se integrará FigEx mientras no exista una licencia explícita compatible.

## Evidence Graph

La relación clave es `Claim -> Evidence[]`, no solo `Answer -> Sources`.

Tipos de claim:

- `observed`: visible directamente en figura/panel;
- `author_stated`: contenido del caption o texto del paper;
- `model_inference`: deducción que combina evidencia;
- `uncertain`: incompleto, ambiguo o no legible.

Tipos de evidence:

- región de figura/panel;
- tokens OCR y cajas;
- caption/subcaption;
- sentence/span con página y bbox;
- sección o método relacionado;
- relación entre varias evidencias.

El validador comprueba que IDs y coordenadas existan, que los spans coincidan con el documento y que números/unidades usados por el modelo aparezcan en evidencia o estén marcados como cálculo derivado.

## Recuperación

Primera versión:

- filtros relacionales por documento, figura, panel, sección y tipo;
- búsqueda lexical/full-text para texto;
- embeddings textuales en pgvector;
- descripciones visuales y OCR enlazados a la figura;
- late fusion de resultados con boosts para menciones explícitas.

Un índice visual separado se incorpora solo si E04 demuestra mejora material. La evidencia de 2025–2026 favorece la fusión texto-imagen, pero no justifica añadir complejidad antes de medirla en el corpus propio.

## Persistencia

Para las etapas 0–2 se utilizarán SQLite y ficheros locales detrás de interfaces propias. La tabla siguiente describe el destino previsto desde M3, cuando la escala, la concurrencia o las métricas justifiquen la migración:

| Necesidad | Tecnología objetivo desde M3 | Razón |
|---|---|---|
| originales, renders, crops y outputs crudos | S3/MinIO | blobs inmutables y versionados |
| entidades, relaciones, jobs, costes | PostgreSQL | integridad, consultas, JSONB y auditoría |
| embeddings | pgvector | evita operar un vector DB adicional al inicio |
| cola/cache efímera | Redis + worker Python, si se necesita | jobs y rate limits; no fuente de verdad |
| métricas y trazas | OpenTelemetry + backend configurable | correlación por document/job/model run |

No se recomienda una base de grafos inicialmente: las relaciones caben en PostgreSQL y deben demostrar una necesidad real antes de añadir otro sistema.

## API e interfaz

**API:** Python tipado (FastAPI es candidato), endpoints asíncronos, OpenAPI, uploads directos a object storage, SSE/WebSocket solo para progreso, paginación y filtros estables.

**UI:** React/TypeScript; PDF.js para el paper; OpenSeadragon o canvas de alta resolución para figuras; overlays de bbox; panel de claims/evidence; comparación sincronizada; selección de regiones; historial de procesamiento y exportación JSON/CSV.

Una vista mínima de análisis contiene:

```text
[árbol paper/figuras] [PDF o figura con overlays] [claims tipados + evidencias]
```

## Modelos y orquestación

- Adaptadores propios para APIs comerciales y modelos locales/OpenAI-compatible.
- Primer adaptador: OpenAI, con `gpt-6-luna` como configuración principal y `gpt-6.1-sol` como respaldo desactivado por defecto.
- IDs inyectados por entorno y validados al arrancar; presupuesto inicial total de 5 USD.
- Salida estricta por JSON Schema, temperatura baja y presupuestos de tokens/imagen.
- Las instrucciones del documento se tratan como datos no confiables y nunca se interpolan como instrucciones del sistema.
- No LangChain/LangGraph en el núcleo inicial: contratos propios, menos superficie de dependencia y DAG conocido.
- Reevaluar LangGraph solo si E06/E08 muestran necesidad real de workflows dinámicos, checkpoints conversacionales o human-in-the-loop que no cubra la cola de jobs.

## Seguridad y privacidad

- antivirus y validación de tipo; límites de bytes, páginas, dimensiones, objetos y tiempo;
- contenedor no root, filesystem temporal, sin red por defecto y cuotas CPU/RAM/GPU;
- URLs remotas mediante fetcher con allow/deny rules contra SSRF;
- cifrado en tránsito y reposo; borrado y retención configurables;
- secretos fuera de prompts/logs; redacción de PII configurable;
- políticas de egress por proveedor y consentimiento explícito para APIs externas;
- prompt injection tests en texto, OCR, metadata, nombres de archivo y QR/imagen;
- SBOM, pinning, escaneo de imágenes y registro de licencias.

## Observabilidad y coste

Cada run registra trazas por etapa, errores tipados, queue time, compute time, bytes, páginas, pixels, tokens, llamadas, coste estimado y cache hit. El dashboard separa:

- calidad;
- fiabilidad/fallos;
- latencia p50/p95;
- coste por documento/figura/pregunta;
- uso de recursos;
- distribución por disciplina/tipo de figura.

## Despliegue incremental

1. Prototipo local con SQLite, ficheros locales y un único proceso cuando sea suficiente.
2. Desde M3, Docker Compose con API, worker, PostgreSQL/pgvector, MinIO y Redis opcional.
3. Un único host con GPU opcional cuando se implemente la ruta local en M6.
4. Servicios separados y autoscaling solo tras medir cargas.
5. Kubernetes/Temporal no forman parte de la primera implementación salvo evidencia operativa.

## Decisiones abiertas

- parser/ensemble final tras E01;
- estrategia de paneles tras E02;
- OCR por modalidad tras E03;
- índice visual tras E04;
- modelo definitivo y reglas de escalado tras E05; el prototipo empieza con OpenAI configurable;
- política de validación tras E06;
- nombre legal del titular y avisos de copyright antes de la primera publicación.

Véanse los ADR en [decisions](decisions/README.md).

