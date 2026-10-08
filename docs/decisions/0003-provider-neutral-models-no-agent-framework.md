# ADR 0003 — Adaptadores de modelos propios y sin framework agente inicial

- **Estado:** aceptada para el prototipo
- **Fecha:** 2026-10-06

## Contexto

El pipeline inicial es un DAG conocido. Los proveedores multimodales, precios, límites y modelos cambian con rapidez. LangChain/LangGraph pueden aportar conectores y checkpoints, pero también acoplamiento y una superficie adicional.

## Alternativas

- usar LangChain/LangGraph desde el inicio;
- programar todo contra un proveedor;
- contratos propios y cola de jobs, incorporando framework solo ante una necesidad medida.

## Decisión propuesta

Definir `MultimodalModel`, `EmbeddingProvider` y `JobOrchestrator` propios con schemas estrictos. Implementar el DAG explícitamente. Reevaluar LangGraph o Temporal cuando E06/E08 demuestren workflows dinámicos, human-in-the-loop o recuperación que no cubra la solución simple.

Para el prototipo, el primer adaptador será OpenAI. El modelo principal configurado será `gpt-6-luna` y `gpt-6.1-sol` quedará como respaldo para casos complejos o de baja confianza. Los IDs se inyectan por configuración, se validan al arrancar y nunca se fijan en la lógica de negocio. La ruta local se conserva en el contrato pero su implementación se aplaza hasta M6.

El presupuesto inicial es de 5 USD. Cada llamada debe registrar tokens, coste estimado, modelo real y versión del prompt. El fallback no se activa automáticamente hasta definir y evaluar la regla de escalado.

## Consecuencias

- menor dependencia y tests más deterministas;
- hay que mantener adaptadores pequeños;
- no se descarta un framework futuro, pero deberá justificar complejidad y licencia.
- un cambio de catálogo o proveedor no obliga a reescribir el pipeline;
- los precios documentados son una fotografía temporal y se verifican antes de cada integración o benchmark.

