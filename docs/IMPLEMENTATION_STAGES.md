# Etapas de implementación

Este documento divide el proyecto en entregas pequeñas y comprobables. La prioridad es construir primero el flujo esencial:

```text
Insertar PDF
    -> extraer figuras y pies
    -> localizar el contexto relacionado
    -> analizar cada figura
    -> mostrar una explicación con evidencia
```

Las estimaciones son orientativas para una persona desarrolladora a tiempo completo. Las etapas 1–3 forman el primer prototipo funcional; las posteriores mejoran la experiencia, la precisión y la capacidad de operar el sistema como producto.

## Etapa 0 — Preparación y artículos de prueba (medio día)

**Estado (2026-10-06):** completada; resultados esperados pendientes de revisión humana. Ver [data/stage0](../data/stage0/README.md).

### Objetivo

Definir un caso de uso concreto y reunir una muestra pequeña con la que comprobar el funcionamiento real del sistema.

### Trabajo

- Seleccionar 12 artículos de PMC Open Access con licencia CC BY comprobada individualmente.
- Incluir documentos sencillos y casos difíciles: figuras multipanel, gráficos, microscopía, tablas convertidas en imagen y PDF escaneado.
- Crear un manifiesto con PMC ID, DOI, URL oficial, licencia, atribución, excepciones, fecha y hash SHA-256.
- Guardar la credencial de OpenAI solo en `.env` y usar `.env.example` sin secretos como plantilla.
- Configurar un presupuesto inicial total de 5 USD y límites de coste por documento.
- Acordar la estructura mínima de una explicación.

### Entregable

Una carpeta local de prueba no versionada, un manifiesto legalmente trazable y una lista de resultados esperados para varias figuras.

### Criterio de finalización

Los artículos se pueden utilizar legalmente para las pruebas y cubren los tipos de figuras prioritarios.

## Etapa 1 — Carga del PDF y extracción de figuras (1–2 días)

**Estado (2026-10-06):** completada. Resultados y limitaciones en [reports/stage1-extraction.md](reports/stage1-extraction.md).

### Objetivo

Permitir que el usuario inserte un artículo y obtener las figuras presentes junto con sus pies.

### Trabajo

- Aceptar un archivo PDF y validar que sea legible.
- Extraer las imágenes o recortar las regiones de figura de cada página.
- Asociar cada figura con su número, página y pie de figura.
- Conservar las coordenadas y la página de origen para poder verificar el resultado.
- Mostrar los errores cuando una figura no pueda extraerse correctamente.

### Entregable

Para cada artículo, una colección navegable de figuras con su imagen, número, pie y página de procedencia.

### Criterio de finalización

En los artículos de prueba, la mayoría de las figuras y sus pies se recuperan correctamente y se puede volver desde cada resultado a la página original.

## Etapa 2 — Análisis y explicación de las figuras (1–2 días)

**Estado (2026-10-06):** completada. 77/78 explicaciones válidas en SFI-12 por 0,10 USD. Resultados, revisión frente a los resultados esperados y limitaciones en [reports/stage2-explanation.md](reports/stage2-explanation.md).

### Objetivo

Enviar cada figura y su pie a un modelo multimodal para generar una explicación científica comprensible.

### Trabajo

- Conectar OpenAI mediante un adaptador propio y sustituible.
- Usar `gpt-6-luna` como modelo principal configurable y reservar `gpt-6.1-sol` como respaldo desactivado por defecto.
- Solicitar una respuesta estructurada y no solamente texto libre.
- Separar claramente lo que se observa en la imagen de lo que el modelo infiere.
- Registrar el modelo, la versión del prompt, el tiempo y el coste de cada análisis.
- Aplicar caché y límites configurables para no repetir gasto.
- Rechazar o marcar las respuestas incompletas y mal formadas.

### Contenido mínimo de la explicación

- qué representa la figura;
- cómo está organizada y cómo debe leerse;
- variables, ejes, unidades, grupos, colores o símbolos importantes;
- principales patrones o resultados visibles;
- interpretación general;
- incertidumbres o elementos que no se pueden determinar.

### Entregable

Una explicación estructurada debajo de cada figura extraída.

### Criterio de finalización

El usuario puede insertar un PDF y obtener una explicación útil de sus figuras sin realizar pasos manuales intermedios.

## Etapa 3 — Contexto del artículo y evidencia (2–4 días)

**Estado (2026-10-06):** completada. 309/309 resultados principales rastreables hasta la figura, el pie o un pasaje con página; 67/67 figuras mencionadas detectadas frente al JATS. Ver [reports/stage3-context.md](reports/stage3-context.md).

### Objetivo

Evitar que la figura se interprete de forma aislada incorporando el texto del artículo que la describe.

### Trabajo

- Extraer el texto del PDF conservando páginas y secciones.
- Detectar menciones como `Figura 2`, `Fig. 2b` o equivalentes.
- Recuperar los párrafos cercanos a cada mención.
- Combinar figura, pie y párrafos relacionados antes del análisis.
- Mostrar qué fragmentos respaldan cada explicación.
- Distinguir entre observación visual, afirmación de los autores e inferencia del modelo.

### Entregable

Una explicación contextualizada que relaciona la figura con los resultados y conclusiones del artículo e incluye referencias a las páginas utilizadas.

### Criterio de finalización

Las afirmaciones principales pueden rastrearse hasta la figura, el pie o un fragmento concreto del artículo.

## Etapa 4 — Aplicación utilizable (4–7 días)

**Estado (2026-10-06):** implementada y verificada técnicamente (`sfi serve`); queda pendiente la prueba con personas ajenas al desarrollo, que es el criterio de finalización. Ver [reports/stage4-web-app.md](reports/stage4-web-app.md).

### Objetivo

Convertir el prototipo técnico en una aplicación sencilla que pueda utilizarse sin acceder al código.

### Trabajo

- Crear una pantalla para cargar el artículo.
- Mostrar el progreso del procesamiento y los errores recuperables.
- Permitir navegar entre las figuras del documento.
- Presentar imagen, pie, explicación y evidencia en una misma vista.
- Añadir zoom y enlace a la página original.
- Guardar temporalmente los resultados para no repetir análisis costosos.

### Entregable

Una aplicación web local capaz de procesar varios PDF de forma individual.

### Criterio de finalización

Una persona ajena al desarrollo puede cargar un artículo, localizar una figura y entender la explicación sin ayuda.

## Etapa 5 — Precisión y trazabilidad (2–4 semanas)

**Estado (2026-10-07):** en curso. Corpus SFI-48 seleccionado y con referencia automática; en `dev` + `validation` se cumplen los umbrales de figuras (F1 de cajas 0,990 con las cajas revisadas), pies (0,985), contexto (Recall@5 0,95) y pérdidas silenciosas (0). Estado de cada umbral en [reports/stage5-gates.md](reports/stage5-gates.md). La aplicación tiene una pantalla de revisión humana (cajas, paneles y rúbrica; guía en [ANNOTATION_GUIDE.md](ANNOTATION_GUIDE.md)); las 43 cajas dudosas están revisadas. Las figuras multipanel se separan en paneles con su sub-pie (línea base de E02, [informe](reports/stage5-panels.md)): letras y sub-pies coinciden con el JATS, pero las cajas de panel no alcanzan el umbral (AP50 0,50 frente a 185 cajas humanas) y no se muestran. Una primera revisión de explicaciones con otra IA, verificada ([informe](reports/stage5-explanations-judge.md)), encontró errores de lectura de gráficos y no objetó nada de lo atribuido a los autores; el prompt 0.4 añade reglas de lectura. En `validation` (233 afirmaciones), los errores confirmados en afirmaciones de confianza alta bajan a 3 de 207 (0,0145; IC 95 % 0,005–0,042, umbral 0,02). Una capa de evidencia ([ADR 0007](decisions/0007-ocr-evidence-layer.md)) guarda el texto de cada figura (texto PDF y OCR con RapidOCR) y enlaza los números de las afirmaciones con el sitio donde están impresos. El OCR lee bien el 0,897 de los números (umbral 0,95), así que todavía no invalida afirmaciones. Faltan mejores cajas de panel (las letras se localizan en el 0,87 de los casos y pueden servir de anclas), la rúbrica humana y la evaluación de `test`. Ver [reports/stage5-sfi48-baseline.md](reports/stage5-sfi48-baseline.md).

### Objetivo

Resolver los casos difíciles y reducir explicaciones incorrectas o no respaldadas.

### Trabajo

- Separar figuras multipanel y relacionar paneles como `(a)`, `(b)` o `(c)` con sus descripciones.
- Mejorar OCR para textos pequeños, ejes, leyendas, unidades y barras de escala.
- Incorporar niveles de confianza y un estado de “no se puede determinar”.
- Comprobar números, citas y referencias generadas.
- Comparar las respuestas con anotaciones humanas en los artículos de prueba.
- Medir extracción, calidad de explicación, citas correctas, tiempo y coste.

### Entregable

Una versión fiable para los tipos de artículos y figuras incluidos en el conjunto de evaluación.

### Criterio de finalización

El sistema alcanza los umbrales definidos en `docs/EVALUATION_PLAN.md` y no presenta inferencias como hechos cuando carece de evidencia.

## Etapa 6 — Producto robusto (2–4 meses adicionales)

### Objetivo

Preparar el sistema para uso continuado, múltiples usuarios y una variedad amplia de documentos.

### Trabajo

- Añadir usuarios, permisos, historial y políticas de conservación de documentos.
- Procesar trabajos en segundo plano con reintentos y recuperación de fallos.
- Incorporar monitorización de calidad, latencia, consumo y costes.
- Proteger la carga y el procesamiento de documentos no confiables.
- Evaluar distintos extractores y proveedores sin acoplar el producto a uno solo.
- Ampliar las pruebas por disciplina, idioma y tipo de PDF.
- Documentar despliegue, copias de seguridad y operación.

### Entregable

Una aplicación desplegable y mantenible, con seguridad, observabilidad y evaluación continua.

### Criterio de finalización

El sistema cumple los objetivos operativos y de calidad acordados para producción y puede recuperarse de errores sin perder la trazabilidad.

## Alcance recomendado para la primera entrega

La primera entrega debe terminar al completar la etapa 3. Incluirá:

1. carga de un PDF;
2. extracción de figuras y pies;
3. recuperación de los párrafos que mencionan cada figura;
4. análisis con un modelo multimodal;
5. explicación estructurada con referencias al documento.

No necesita inicialmente entrenamiento propio, agentes autónomos, un índice multimodal complejo, múltiples proveedores ni infraestructura distribuida. Esas decisiones deben tomarse después de probar el flujo básico con artículos reales.

## Resumen temporal

| Nivel alcanzado | Resultado acumulado | Tiempo orientativo |
|---|---|---:|
| Etapas 0–2 | Prototipo que extrae y explica figuras | 2–4 días |
| Etapa 3 | Explicaciones respaldadas por el artículo | 4–8 días acumulados |
| Etapa 4 | Aplicación web utilizable | 1–2 semanas acumuladas |
| Etapa 5 | Mayor precisión y evaluación formal | 3–6 semanas acumuladas |
| Etapa 6 | Producto robusto para uso continuado | 3–6 meses acumulados |

Estos rangos no significan que haya que esperar meses para utilizar el sistema. El valor principal aparece en las primeras etapas; el tiempo adicional corresponde a generalización, control de calidad, seguridad y operación a escala.
