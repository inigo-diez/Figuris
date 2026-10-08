# Decisiones vigentes del proyecto

**Actualizado:** 2026-10-06  
**Alcance:** decisiones prácticas para construir y publicar el primer prototipo.

Este documento resume las decisiones ya tomadas. Si una cifra, modelo o servicio externo cambia, prevalece la documentación oficial consultada en la fecha de ejecución y el cambio debe quedar registrado.

## 1. Publicación y licencia

- El repositorio se publicará en GitHub como proyecto de código abierto.
- El código propio se distribuye bajo **Apache License 2.0**.
- Se permite el uso personal, académico y comercial. No existe una cláusula de “solo uso no comercial”.
- Quien redistribuya el trabajo debe cumplir las obligaciones de licencia y atribución aplicables, conservar los avisos y señalar los archivos modificados.
- La licencia incluye una concesión expresa de patentes y una exclusión de garantías.
- Esta licencia cubre únicamente el código y la documentación propios. No cambia las licencias de artículos, figuras, datasets, modelos, pesos ni dependencias de terceros.

Referencias: [texto oficial de Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0) y [definición de código abierto de la OSI](https://opensource.org/osd).

### Titular del copyright

El aviso es `Copyright 2026 The Scientific Figure Intelligence Authors` y está en [NOTICE](../NOTICE). Sigue la convención habitual en proyectos Apache-2.0 (por ejemplo, “The Go Authors”): el titular son las personas que contribuyen, identificadas en el historial de git. No se usa como titular al asistente, a OpenAI ni a una organización inexistente.

Si más adelante se quiere un titular nominal (persona u organización con nombre legal), basta con sustituir el aviso en `NOTICE`.

## 2. Proveedor y modelos multimodales

El prototipo utilizará OpenAI mediante un adaptador propio y sustituible:

| Función | Configuración inicial | Uso |
|---|---|---|
| Modelo principal | `gpt-6-luna` | Análisis habitual de figuras con el menor coste posible |
| Modelo de respaldo | `gpt-6.1-sol` | Casos complejos o resultados de baja confianza |
| Ruta local | Pendiente para M6 | Privacidad, ejecución offline y comparación futura |

Los IDs no se fijarán dentro de la lógica de negocio. Se proporcionarán mediante variables de entorno, se validarán al iniciar la aplicación y cada ejecución registrará el proveedor y el ID real utilizado. De esta forma se podrán sustituir si cambian el catálogo, el acceso de la cuenta o los precios.

### Precios de referencia

Precios estándar publicados por OpenAI y comprobados el 2026-10-06, por millón de tokens:

| Modelo | Entrada | Entrada en caché | Salida | Admite imagen de entrada |
|---|---:|---:|---:|---|
| `gpt-6-luna` | 0,10 USD | 0,01 USD | 0,50 USD | Sí |
| `gpt-6.1-sol` | 2,00 USD | 0,10 USD | 10,00 USD | Sí |

Fuentes oficiales: [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) y [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

La expresión “20 veces más barato” se refiere únicamente a la tarifa por token de Luna frente a Sol. No garantiza que todos los documentos cuesten exactamente veinte veces menos, porque el coste final depende del tamaño de las figuras, el contexto, los tokens de razonamiento, la longitud de la respuesta y los reintentos.

### Control de gasto

- Presupuesto inicial total: **5 USD**.
- Registrar tokens y coste estimado de cada petición y de cada documento.
- Reutilizar resultados mediante caché para no analizar dos veces el mismo artefacto y configuración.
- Aplicar límites configurables de figuras, tokens y coste por documento.
- No escalar automáticamente a Sol salvo que una regla explícita de baja confianza o el usuario lo solicite.
- Comprobar precios, disponibilidad y acceso de la cuenta antes de conectar los modelos en código.

## 3. Ejecución y almacenamiento inicial

- Las etapas 0–2 usarán **SQLite y ficheros locales**.
- No se necesita Docker Compose para el primer prototipo.
- Persistencia y almacenamiento se accederán mediante interfaces propias para evitar acoplamiento.
- En M3 se podrá migrar a PostgreSQL/pgvector y MinIO si las métricas o el uso multiusuario lo justifican.

## 4. Credenciales y datos privados

- `OPENAI_API_KEY` se guardará exclusivamente en `.env` local.
- `.env` y sus variantes están ignorados por Git; `.env.example` solo contiene valores de ejemplo sin secretos.
- Nunca se escribirán claves en código, documentación, tests, logs o commits.
- Los PDF descargados, archivos procesados y resultados generados permanecerán en rutas ignoradas por Git salvo que exista una decisión expresa y su licencia permita publicarlos.

## 5. Artículos del piloto

La Etapa 0 comenzará con **12 artículos de PMC Open Access**, descargados únicamente por las vías oficiales y seleccionados con licencia CC BY verificada por artículo.

La muestra debe incluir gráficos, figuras multipanel, microscopía o imagen biomédica, diagramas, texto pequeño y al menos un PDF difícil. Por cada artículo se registrará:

- PMC ID y DOI;
- título y fuente;
- URL oficial de descarga;
- licencia y URL de la licencia;
- atribución requerida;
- posibles excepciones de copyright indicadas en figuras concretas;
- fecha de descarga;
- hash SHA-256 del archivo.

La licencia del artículo se comprobará individualmente: pertenecer a PMC Open Access no basta para asumir que todo su contenido puede redistribuirse. Los PDF no se incorporarán al repositorio público por defecto; el manifiesto sí podrá versionarse cuando no reproduzca material protegido.

## 6. Preparación de GitHub

Antes del primer commit público:

1. completar el titular del copyright (hecho: `NOTICE`);
2. verificar que `.gitignore` cubra secretos, PDF, datos y resultados;
3. revisar que no exista ninguna credencial en el historial o en los archivos preparados;
4. crear el commit inicial de documentación;
5. utilizar `main` como rama principal;
6. conectar y publicar el repositorio de GitHub.
