# Prueba de usabilidad de la etapa 4

**Objetivo:** comprobar el criterio de finalización de la etapa 4: *una persona ajena al desarrollo puede cargar un artículo, localizar una figura y entender la explicación sin ayuda.*

**Duración:** 20–25 minutos por persona. **Participantes:** 2–3 personas que no hayan visto la aplicación. Al menos una debe leer artículos científicos con regularidad y otra no tiene por qué.

## Preparación (una vez)

1. Arrancar la aplicación con `sfi serve --open` y comprobar que la cabecera indica el modelo y el presupuesto (no «Sin clave de OpenAI»).
2. Elegir un PDF que **no** se haya procesado antes, de una disciplina cercana a la del participante. Debe tener entre 4 y 8 figuras, al menos una con varios paneles, y licencia CC BY. Guardarlo en el escritorio.
3. Tener esta hoja abierta para anotar. No explicar la aplicación ni el proyecto: solo «es una herramienta para entender las figuras de un artículo».

## Tareas

Leer cada tarea en voz alta y no ayudar. Si la persona se bloquea más de 2 minutos, anotar el bloqueo y pasar a la siguiente.

| # | Tarea | Éxito si… |
|---|---|---|
| 1 | «Tienes este artículo en el escritorio. Haz que la herramienta lo analice.» | sube el PDF y espera a que termine sin preguntar |
| 2 | «Busca la figura que habla de *[tema concreto de una figura]*.» | llega a esa figura desde la lista |
| 3 | «Explícame con tus palabras qué muestra esa figura y qué conclusión sacan los autores.» | su explicación coincide en lo esencial con la figura |
| 4 | «¿De dónde sale la afirmación *[una afirmación «según los autores» que cite el texto]*?» | pulsa la fuente y localiza el párrafo en la página |
| 5 | «¿Hay algo de esta figura que la herramienta diga que no se puede saber?» | encuentra la sección «Incertidumbres» o una afirmación «incierto» |
| 6 | «Amplía la parte de la figura donde se ve *[detalle pequeño: un eje, una barra de escala]*.» | usa el zoom y lo localiza |

## Qué anotar

Por tarea: éxito (sí / con dificultad / no), tiempo aproximado, dónde dudó y frases textuales del participante.

Prestar especial atención a:

- si entiende los cuatro tipos de afirmación sin leer la leyenda, o si la lee;
- si confía en exceso: si trata una inferencia o un «incierto» como un hecho;
- si percibe el aviso «no fiable» cuando aparece;
- confusiones de vocabulario (pie, pasaje, panel, «reprocesar»).

## Preguntas finales

1. Del 1 al 5, ¿cuánto te ha ayudado a entender la figura? ¿Por qué?
2. ¿Hubo algo que la herramienta dijera y no te creyeras? ¿Pudiste comprobarlo?
3. ¿Qué es lo que más te ha costado?
4. ¿La usarías con tus propios artículos? ¿Qué le falta?

## Criterio de aprobación

La etapa 4 se da por cerrada si **todas** las personas completan las tareas 1–3 sin ayuda y al menos 2 de 3 completan las tareas 4–6. Los problemas que aparezcan en dos o más personas se corrigen antes de cerrarla, aunque se cumpla el criterio.

## Registro

Guardar las notas en `docs/reports/stage4-usability-AAAA-MM-DD.md`, sin nombres de los participantes (P1, P2, P3).
