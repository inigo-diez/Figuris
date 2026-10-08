# Reutilización y licencias

El inventario inicial de componentes, modelos y datasets está en [../research/license-inventory.md](../research/license-inventory.md).

## Licencia del proyecto

El código y la documentación propios se publican bajo **Apache License 2.0**, que permite también el uso comercial. Las condiciones principales son conservar la licencia y los avisos aplicables, identificar modificaciones y respetar sus términos de patentes y atribución. No se añadirá una restricción de uso no comercial, porque dejaría de ser una licencia de código abierto según la definición de la OSI.

El nombre legal del titular del copyright continúa pendiente. No se atribuirá la titularidad al asistente, a OpenAI ni a una organización que no sea la propietaria real. Véase [Decisiones vigentes del proyecto](PROJECT_DECISIONS.md#1-publicación-y-licencia).

La licencia del repositorio no se extiende automáticamente a los artículos, figuras, datasets, pesos, modelos ni componentes de terceros.

## Política

- Revisar la licencia antes de instalar, copiar, modificar o distribuir código.
- Preferir dependencias mantenidas a copiar grandes bloques de implementación.
- Registrar versión, repositorio, licencia, uso y modificaciones.
- Conservar avisos y atribuciones exigidos.
- No incorporar código sin licencia explícita ni con términos incompatibles.
- Tratar modelos, datasets, pesos y servicios como activos con licencias independientes.
- Someter cualquier dependencia crítica a revisión de mantenimiento y riesgo.

## Registro mínimo

| Componente | Fuente | Versión/commit | Licencia | Forma de uso | Cambios | Obligaciones |
|---|---|---|---|---|---|---|

El registro operativo también debe distinguir `artifact_type` (`code`, `model`, `dataset`, `document`) y conservar hash, licencia del build exacto y fecha de revisión.

## Opciones de reutilización

1. Dependencia publicada y fijada por versión.
2. Servicio externo detrás de una interfaz propia.
3. Fork mantenido con historial y avisos intactos.
4. Módulo adaptado con atribución y pruebas.
5. Idea arquitectónica reimplementada sin copiar código protegido.

La selección final debe equilibrar calidad técnica, licencia, mantenimiento, reproducibilidad y coste de sustitución.

