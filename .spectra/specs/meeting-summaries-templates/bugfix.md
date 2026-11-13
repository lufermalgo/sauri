# Bugfix — T14/T26: presupuesto de generación local no streaming

## Descripción del Bug

Delta técnico autorizado de task_b7a67614c4f7420e, issues #281/#282 y candidato #899 (`afa74e3`). No abre otra spec ni cambia alcance aprobado. El adaptador crea `httpx.AsyncClient(timeout=60.0)`: como solicita `stream=False`, una inferencia local que aún evalúa la transcripción no envía cabeceras y agota el límite de lectura antes de producir el resumen.

Evidencia de runtime consultada en modo lectura, sin transcripciones: worker reintenta a 19:39:56, 19:41:18 y 19:43:03 UTC del 13/11/2026. Ollama registra POST `/api/generate` 500 tras 1m0s/1m10s y cancelación de tarea en los mismos instantes (hora local -05). El worker no registra la clase de excepción; no se afirma haber visto un stack `ReadTimeout`. El mecanismo de corte a 60s está confirmado en código y reproducido mediante contrato HTTP sintético. No demuestra que toda grabación termine en el nuevo presupuesto.

## Pasos para Reproducir

1. Partir de `afa74e3` e incorporar únicamente `tests/summaries/test_engine_timeout.py` del fix.
2. Ejecutar `PYTHONPATH=backend pytest backend/tests/summaries/test_engine_timeout.py -q`.
3. Observar 12 fallas: timeout de lectura fijo de 60s, configuración ignorada y ausencia de límite total configurable.
4. Para comprobar transporte sin datos reales, usar un servidor HTTP loopback sintético que espere 61s antes de devolver JSON canónico; el cliente anterior corta antes de las cabeceras. No volver a generar el resumen real durante esta corrección.

## Comportamiento Actual (Defecto)

WHEN la evaluación local no devuelve cabeceras en 60s, THEN el cliente cancela un trabajo todavía activo y consume los reintentos existentes.

## Comportamiento Esperado (Correcto)

- WHEN se inicia el worker, THEN SHALL leer `SUMMARIZATION_TIMEOUT_SECONDS`, default 900s, y rechazar valores vacíos, no numéricos, no positivos o no finitos.
- WHEN se genera un resumen, THEN SHALL aplicar ese presupuesto total finito por intento y de lectura HTTP, incluso con cliente inyectado; la conexión tiene límite propio de 10s sujeto al presupuesto total.
- WHEN vence el presupuesto, THEN SHALL propagar el error a la política vigente de reintentos/fallo terminal, sin publicar un éxito ficticio.

## Comportamiento Sin Cambios (Prevención de Regresiones)

- WHEN se solicita generación, THEN SHALL CONTINUE TO enviar la transcripción completa y el snapshot opaco sin cambiar prompt, plantilla, modelo, `stream=False` ni esquema canónico.
- WHEN ocurre error/agotamiento, THEN SHALL CONTINUE TO no persistir resumen ni claim exitoso; el handler terminal marca `failed` sin diagnósticos privados.
- WHEN se configura el proveedor, THEN SHALL CONTINUE TO exigir endpoint/modelo locales válidos, sin selector cloud ni fallback.
- WHEN corren trabajos ASR/diarización, THEN SHALL CONTINUE TO no alterar sus timeouts, procesos, datos ni servicios por esta entrega.

## Restricciones del Fix

Sin nuevos modelos, descargas, gastos, retención, migraciones o dependencias. Sin despliegue/merge ni nueva generación real. PR apilado hacia la rama de #899; Fer integra y Ansel verifica runtime/navegador después de coordinar ventana segura.

## Criterios de Aceptación

1. RED→GREEN del contrato de configuración, transporte, contenido completo y cancelación total.
2. Respuesta HTTP sintética no streaming con 61s de espera completa sin cancelación a 60s.
3. Regresión PostgreSQL descartable `sauri_t11_*`: error HTTP y timeout total no producen artefacto/claim y llegan a `failed` por el handler existente.
4. Suites backend pertinentes, lint y tipos del código afectado pasan; evidencia y límites en `timeout-evidence-20261113.md`. No confundir estas pruebas con resumen real ni aceptación de producto.
