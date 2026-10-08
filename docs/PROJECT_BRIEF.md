# Objetivo y alcance

## Visión

Scientific Figure Intelligence permitirá cargar uno o varios artículos científicos y explorar sus figuras como objetos estructurados, consultables y vinculados a la evidencia del documento.

## Capacidades objetivo

1. Extraer figuras con la máxima resolución disponible.
2. Detectar captions, numeración, paneles, leyendas, ejes, unidades, escalas, símbolos y colores.
3. Vincular cada figura con su sección, metodología, resultados y menciones dentro del texto.
4. Clasificar gráficas, diagramas, microscopía, imagen médica, mapas, estructuras moleculares, tablas-imagen y figuras multipanel.
5. Analizar conjuntamente imagen, caption y contexto del artículo.
6. Separar claramente:
   - observación visual;
   - afirmación de los autores;
   - inferencia del sistema;
   - incertidumbre.
7. Contestar preguntas sobre una figura, sus paneles o varias figuras relacionadas.
8. Citar página, figura, panel y fragmento de evidencia.
9. Permitir navegación, zoom, selección de regiones, comparación y revisión de fuentes.
10. Medir precisión, fidelidad, alucinaciones, latencia y coste.

## Usuarios iniciales

- Investigadores y estudiantes que revisan literatura científica.
- Analistas científicos, biomédicos o farmacéuticos.
- Equipos de revisión sistemática y diligencia científica.

## Caso de uso prioritario para la alpha

Un investigador carga un paper, revisa sus figuras y paneles, formula una pregunta y recibe una respuesta en la que cada afirmación está clasificada y enlazada a la región visual o fragmento textual que la sustenta. Puede comparar dos figuras sin perder la procedencia.

Flujo de éxito:

1. carga segura y progreso visible;
2. inventario de figuras con thumbnails, labels, captions y warnings;
3. selección de figura/panel y zoom;
4. análisis separado en observación, autor, inferencia e incertidumbre;
5. salto desde cada claim a PDF/figura/texto;
6. pregunta de seguimiento o comparación;
7. exportación estructurada con referencias.

## Requisitos funcionales de la alpha

- PDF born-digital y escaneado; JATS/XML cuando esté disponible.
- Extracción de figuras/captions/menciones y representación de paneles.
- OCR de elementos visuales con cajas y confianza.
- Preguntas sobre una o varias figuras del mismo documento.
- Claims tipados y citas a página, región y span.
- Navegación paper–figura–panel, overlays, zoom y comparación.
- Reprocesado con configuración/versiones distintas sin perder historial.
- Exportación JSON y reporte legible.

## Criterios de éxito

- métricas y gates de `docs/EVALUATION_PLAN.md` alcanzados o gaps explícitos;
- ninguna referencia inventada ni pérdida silenciosa en el test;
- un usuario puede verificar un claim en dos interacciones o menos;
- coste, latencia, versión y evidencia visibles por run;
- despliegue local reproducible y al menos un proveedor local y uno remoto intercambiables.

## Fuera del alcance inicial

- Sustituir el juicio experto o emitir conclusiones clínicas.
- Reproducir automáticamente experimentos científicos.
- Aceptar como cierta cualquier interpretación no respaldada por el artículo.
- Elegir definitivamente LangChain, LangGraph o un proveedor de modelos sin comparación previa.
- Emitir recomendaciones clínicas, regulatorias o de inversión.
- Garantizar digitalización exacta de cualquier chart o generalización universal entre disciplinas.
- Entrenar un modelo fundacional propio antes de demostrar que los componentes existentes no bastan.

## Supuestos iniciales

- Inglés es el idioma principal del primer benchmark; otros idiomas se evalúan en un estrato pequeño.
- El código propio se publica bajo Apache-2.0, compatible con uso comercial; titular del copyright: The Scientific Figure Intelligence Authors (ver `NOTICE`).
- Las APIs externas son opcionales y requieren consentimiento/política de egress; debe existir una ruta local razonable.
- La precisión y trazabilidad tienen prioridad sobre latencia en la primera alpha.
- El corpus solo incluye documentos con derechos de uso registrados por item.

## Resultado final esperado

Una aplicación desplegable y documentada, con API e interfaz, corpus de evaluación, experimentos reproducibles, trazabilidad de respuestas, tests y una arquitectura que permita cambiar extractores y modelos.

