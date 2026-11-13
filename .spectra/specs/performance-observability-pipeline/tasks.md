# Tareas — Rendimiento, precisión y observabilidad

## Estado y contrato

Encargo de Fer 13/11/2026 17:10: tres fases SDD y primera mejora medible en 30 minutos. Documento de tareas completo no significa implementación completa. Base de primera entrega: `178f893551405774bc5d9006d0eb90cd4c33f586`, candidato QA combinado #902, todavía no main. Worktree de Ansel `.worktrees/perf-pipeline-observability`, rama `perf/pipeline-observability`. Tarea APX `task_e2a1fd161b4d4910`. Revisión de issues abiertos realizada por API del repositorio; no se encontró issue de rendimiento/observabilidad equivalente. El issue de esta unidad se vincula en evidence.md al crearlo.

Primera unidad T1–T4: Ansel integra la entrega de Nahuel en la rama candidata tras revisión y pruebas; condición de cierre PR listo para integrar, no merge a main ni instalación implícita. Alcance asignable: `assignment.py`, pruebas diferenciales, benchmark; no editar specs ni resúmenes en paralelo. T5 la implementa Ansel en archivos distintos. T6–T12 son backlog ordenado de la reescritura, no trabajo simultáneo oculto. Cada unidad posterior requiere contrato acotado e issue vinculado antes de comenzar.

## Resumen de Fases

| Fase | Tareas | Dependencias |
|---|---|---|
| Primera aceleración exacta | T1–T4 | Contratos actuales de atribución |
| Uso observable del resumen | T5 | Sobre Ollama actual |
| Correlación y recursos | T6–T8 | T5 |
| Coordinación e inferencia | T9–T11 | T6–T8 |
| Validación y promoción | T12 | Por unidad entregada |

## Fase 1: Primera aceleración exacta

### T1: Oracle diferencial antes del cambio
**Archivo:** `backend/tests/diarization/test_assignment_equivalence.py` (nuevo), `backend/app/diarization/assignment.py` (lectura).
**Acción:** Conservar en el test un oracle independiente del algoritmo previo; generar con Hypothesis turnos/segmentos válidos desordenados, huecos, duplicados, solapamientos y hablantes sin segmentos. Probar ambos modos, no mutación, desempates y turnos degenerados. Registrar ejecución antes de optimizar.
**Criterio de Completado:** Suite pasa sobre implementación base; cubre P1. El test exige equivalencia, no una implementación particular.
**Dependencias:** Ninguna.
**Estado:** En ejecución por Nahuel, sesión performance-first-slice; Ansel verifica entrega.

### T2: Indexar consultas de solapamiento
**Archivo:** `backend/app/diarization/assignment.py`.
**Acción:** Reemplazar recorrido total por índice temporal por hablante construido una vez por llamada; conservar exactamente multiplicidad en acumulado y unión en exclusivo, orden de turnos y desempates por sequence. Usar enteros, sin estado global ni acceso a DB.
**Criterio de Completado:** T1, `tests/diarization/test_assignment_property.py` y `tests/diarization/test_exclusive_assignment.py` pasan; revisión confirma contrato público idéntico. P1.
**Dependencias:** T1.
**Estado:** Pendiente.

### T3: Benchmark reproducible de etapa
**Archivo:** `_tools/benchmark-assignment.py` (nuevo), `.spectra/specs/performance-observability-pipeline/evidence.md`.
**Acción:** Comparar base y optimizada con misma entrada, warmup y 7 repeticiones alternadas. Ofrecer entrada JSON de intervalos sin texto para replay; etiquetar generación sintética de manera explícita. Verificar igualdad antes de medir. Reportar muestras, mediana, ratio y tamaño de entrada sin IDs personales. No derivar segmentos reales desde asignaciones finales.
**Criterio de Completado:** Comando reproducible y salida real; reducción >=20% de mediana de etapa para promover, sin extrapolación al resumen ni al pipeline completo. P2/P7.
**Dependencias:** T2.
**Estado:** Pendiente.

### T4: Regresión y publicación de primera unidad
**Archivo:** `backend/tests/diarization/`, `.spectra/specs/performance-observability-pipeline/evidence.md`.
**Acción:** Ejecutar pruebas pertinentes, ruff/mypy, revisar diff, crear commit y PR con issue vinculado. Revisar candidato final y registrar checks/limitaciones sin desactivar hooks. Si no hay mejora, continuar solución dentro de la ventana o reportar resultado negativo.
**Criterio de Completado:** PR candidato con evidencia y sin hallazgos pendientes de esta unidad; no declararlo instalado/integrado. P1/P2/P7.
**Dependencias:** T3.
**Estado:** Pendiente.

## Fase 2: Uso observable del resumen

### T5: Recuperar contadores Ollama sin contenido
**Archivo:** `backend/app/summaries/engine.py`, `backend/tests/summaries/test_engine_usage.py` (nuevo).
**Acción:** Emitir evento estructurado seguro con duración monotónica, resultado y contadores válidos del sobre Ollama ya recibido: prompt_eval_count, eval_count, total_duration, load_duration, prompt_eval_duration, eval_duration. Convertir ns a s. Omitir inválidos/ausentes, no loguear payloads, modelos libres, URLs ni excepciones crudas. Conservar generate y CanonicalSummary. Pruebas con secretos centinela y datos adversos, cancelación/error y timeouts existentes.
**Criterio de Completado:** Pruebas de resúmenes y privacy pasan; evento observado contiene solo campos aprobados, no se añade una llamada al proveedor. P4.
**Dependencias:** Ninguna; independiente de T1–T4.
**Estado:** Implementado y probado por Ansel en commit8b17a86, PR#908. 33 pruebas focales y regresión182passed/1skipped; evento observado en pruebas con transporte de inferencia simulado, no en nueva generación real. No instalado. Detalle en evidence.md.

## Fase 3: Correlación y recursos

### T6: Contexto OTel entre servicios y broker
**Archivo:** `backend/app/infra/telemetry.py` (nuevo), `backend/app/main.py`, `backend/app/infra/queue_rabbitmq.py`, workers en `backend/app/transcription/worker.py`, `backend/app/diarization/worker.py`, `backend/app/summaries/worker.py`, `backend/tests/telemetry/test_context.py` (nuevo).
**Acción:** Integrar SDK OTel, contextvars, spans y contexto W3C validado; sin baggage arbitrario ni cuerpos/SQL parametrizado en instrumentación automática. Firma y verificación de mensajes conservadas; contexto nuevo cubierto por firma. Separar espera, intento y persistencia, links de reintento, excepciones categorizadas.
**Criterio de Completado:** Pruebas extremo a extremo de contexto y firma pasan; misma operación se recorre sin contenido ni doble conteo de éxito. P3/P4.
**Dependencias:** T5.
**Estado:** Backlog.

### T7: Métricas de recursos y consumo
**Archivo:** `backend/app/infra/telemetry.py`, `_tools/resource-sampler.py` (nuevo), `backend/tests/telemetry/test_resources.py` (nuevo), `frontend/src/api.ts`, `extension/src/core/api/client.ts`, `extension/src/upload-queue.ts`, `backend/app/telemetry/router.py` (nuevo).
**Acción:** Implementar métricas, unidades y labels acotados del diseño, muestrear cada 5 s CPU/RSS/I/O procesos propios, stats Docker del proyecto y memoria/presión host diferenciadas. Ausencias explícitas para Metal/energía; no sudo ni nuevas capacidades. Registrar pool DB, cola/outbox, almacenamiento y tokens reales/estimados separados. Instrumentar duración percibida y reintentos en portal/extensión, solo hacia Sauri; receptor autenticado con lotes de hasta50 eventos/32KiB, límite60 lotes/minuto, lista positiva y sin contenido de usuario. Agregar pruebas de límites, autenticación y privacidad; ejecutar typechecks definidos en package.json de frontend y extensión antes de declarar listo.
**Criterio de Completado:** Fixtures Linux/macOS verifican unidades y ausencia, labels no contienen IDs, muestra real observada de host y Docker sin atribución falsa de GPU. P4/P8.
**Dependencias:** T6.
**Estado:** Backlog.

### T8: Collector, paneles y presupuestos locales
**Archivo:** `ops/observability/compose.yml`, `ops/observability/otel-collector.yaml`, `ops/observability/grafana/` (nuevos), `backend/tests/telemetry/test_failure_budget.py` (nuevo), `docs/operations/observability.md` (nuevo).
**Acción:** Configurar OTLP interno, Prometheus/Tempo/Loki/Grafana con acceso local restringido, sin exportación externa, retención 7 días/cuota conjunta 512 MiB, buffers <=8 MiB por proceso, sampling y contador de pérdida. Probar caída/disco lleno, scrub de centinelas y consulta por operación. Medir overhead y recursos del propio stack, no ocultarlos como producto.
**Criterio de Completado:** Paneles de latencia, recursos, cola, tokens y errores vistos en navegador APX con captura; pruebas de caída/privacy/cuotas y comparación overhead con objetivo <5% de mediana. Limpiar Docker temporal exclusivo tras ensayo. P4/P5/P8.
**Dependencias:** T6, T7.
**Estado:** Backlog.

## Fase 4: Coordinación e inferencia

### T9: Admisión global con lease y fencing
**Archivo:** `backend/app/infra/resource_admission.py`, migración nueva en `backend/alembic/versions/`, `backend/tests/telemetry/test_admission_integration.py` (nuevos), workers y clientes de motores existentes.
**Acción:** Plaza inicial 1 por host, lease 30 s, heartbeat 10 s, reloj DB y fencing; FIFO por prioridad con envejecimiento. Reservar antes de inferencia en los tres motores, transacciones cortas, liberar en finally, no commit obsoleto. Conservar mensajes e idempotencia y no descargar modelos ajenos.
**Criterio de Completado:** PostgreSQL real concurrente demuestra P6, caída/recuperación y que health/API siguen respondiendo; comparación con y sin contención distingue espera de inferencia.
**Dependencias:** T6, T7.
**Estado:** Backlog.

### T10: Preparación efímera y responsividad de motores
**Archivo:** `backend/asr-engine/native_main.py`, `backend/diar-engine/`, `backend/tests/asr_engine/`, `backend/tests/diarization/`.
**Acción:** Inspeccionar pipeline activo y eliminar solo descargas/decodificación redundantes comprobadas. Aislar trabajo síncrono que bloquea event loop con un worker controlado por admisión, sin inferencias concurrentes inseguras. Compartir datos solo dentro de vida del Trabajo, en memoria/pipes, liberar al cancelar. Mantener alineación por palabra, original e incertidumbre.
**Criterio de Completado:** Comparación real mismo original/configuración, control de memoria y health responsive bajo carga; salida y Contrato_de_Calidad preservados. P1/P7/P8.
**Dependencias:** T9.
**Estado:** Backlog.

### T11: Evaluar estrategias de inferencia y resumen largo
**Archivo:** `backend/app/summaries/engine.py`, `_tools/benchmark-pipeline.py`, `.spectra/specs/performance-observability-pipeline/quality-evaluation.md` (nuevos donde corresponda).
**Acción:** Comparar resumen completo con bloques/síntesis sobre mismo texto, documentando decisiones/acciones/cifras/omisiones; comparar opciones ASR/diarización solo con evidencia humana y referencias temporales cuando existan. Registrar tiempo total, tokens, recursos y calidad. No forzar hablantes ni instalar modelos nuevos ni enviar datos fuera del entorno aprobado. Diseñar contratos adicionales de captura incremental antes de implementarla.
**Criterio de Completado:** Informe reproducible con candidato aceptable o rechazo explícito; no habilitar cambio por defecto si degrada calidad o necesita decisión de privacidad/gasto/modelo. P2/P7.
**Dependencias:** T8–T10.
**Estado:** Backlog.

### T13: Reutilizar pool para lectura de transcripción (candidato medido)
**Archivo:** `backend/app/main.py`, `backend/app/infra/database.py`, `backend/app/meetings/router.py`, `backend/tests/meetings/test_transcript_pool.py` (nuevo).
**Acción:** Exponer la session factory del lifespan por dependencia; limitar cambio a GET transcript, conservar sesión por petición, autorización, auditoría y errores, cerrar engine solo al terminar aplicación. No usar cache de respuestas ni sesión global. Probar dos usuarios, ausente/no autorizado, múltiples peticiones y shutdown. Repetir comparación de consultas con el mismo corpus real y verificar contrato HTTP mediante suite de API.
**Criterio de Completado:** Pruebas de autorización/contrato/lifecycle pasan y reducción de mediana >=20% del subcamino DB sin cambios de salida; no extrapolar al endpoint completo ni inferencia. Benchmark previo READ ONLY14,907125→8,170ms disponible en evidence.md; no equivale a implementación.
**Dependencias:** T5 para observabilidad inicial; no depende de GPU ni T9. Puede preceder T6 como unidad separada.
**Estado:** Backlog; no implementado ni instalado.

## Fase 5: Validación y promoción

### T12: Verificar cada unidad candidata e instalación
**Archivo:** `.spectra/specs/performance-observability-pipeline/evidence.md`, `docs/operations/observability.md`, suites afectadas.
**Acción:** Revisar diff actual, pruebas y seguridad; vincular issue/APX/commit/PR, resolver conflictos/checks, informar qué está documentado, publicado, integrado e instalado. Para instalar, seguir el alcance aprobado preservando datos y entorno del dueño. No borrar worktrees ajenos. Toda UI se comprueba con APX; limpieza solo de recursos temporales exclusivos.
**Criterio de Completado:** Evidencia del candidato exacto y estado fiel; integración/instalación solo se declaran con comprobación real. P1–P8 según unidad.
**Dependencias:** Por unidad: tareas implementadas y pruebas correspondientes; no bloquea publicar T1–T5 esperando T6–T11.
**Estado:** Pendiente por unidad.
