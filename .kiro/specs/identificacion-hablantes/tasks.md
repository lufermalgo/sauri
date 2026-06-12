# Implementation Plan: Identificación de hablantes (diarización)

## Overview

Plan de implementación incremental del Milestone 3 (diarización), construido **espejando 1:1** el módulo de Transcripción (`backend/app/transcripcion/`) y reutilizando la infraestructura existente (`backend/app/infra/`). Se sigue disciplina TDD estricta **RED → GREEN → REFACTOR** (AGENTS.md §3): cada tarea de prueba se escribe y ejecuta **antes** de su tarea de implementación correspondiente, debe fallar primero, y **nunca** se marca como opcional (`*`).

Las pruebas de propiedad usan Hypothesis con un mínimo de **100 ejemplos** (`@settings(max_examples=100)`) y cada una lleva la etiqueta obligatoria como comentario:
`# Feature: identificacion-hablantes, Property {N}: {texto}`.

El runner (`pytest` + Hypothesis) y la base de datos de prueba ya existen en el backend; la Tarea 1 verifica el entorno y crea el esqueleto del paquete antes de cualquier implementación.

Lenguaje de implementación: **Python** (definido por el diseño y por el stack existente del backend).

## Tasks

- [~] 1. Verificar el entorno de pruebas y crear la estructura del paquete de diarización
  - Ejecutar la suite existente (`pytest`) desde `backend/` para confirmar que el runner, Hypothesis y la base de datos de prueba (`tests/conftest.py`) funcionan; si algo no corre, dejarlo operativo antes de continuar.
  - Crear el paquete `backend/app/diarizacion/__init__.py` (esqueleto vacío) espejando la estructura de `backend/app/transcripcion/`.
  - Confirmar que los nuevos archivos de prueba bajo `backend/tests/` son descubiertos por `pytest`.
  - _Requisitos: infraestructura de pruebas (AGENTS.md §3)_

- [x] 2. Máquina de estados pura del Estado_De_Diarizacion (`app/diarizacion/estado.py`)
  - [x] 2.1 Escribir prueba de propiedad para `aplicar_evento_diarizacion` (RED)
    - **Property 16: Corrección de la máquina de estados del Estado_De_Diarizacion**
    - **Validates: Requirements 9.1, 9.2, 9.3**
    - Generar pares (estado_actual, evento); verificar transiciones válidas (`pendiente`+`iniciar_proceso`→`en_proceso`, `en_proceso`+`diarizacion_completada`→`completada`, `en_proceso`+`fallo_motor`→`fallida` con `causa="fallo_del_motor"`) y que estados terminales/eventos no admitidos conservan el estado sin éxito. Ejecutar y confirmar que falla.
  - [x] 2.2 Implementar `estado.py` (GREEN)
    - Implementar `aplicar_evento_diarizacion(estado_actual, evento) -> ResultadoTransicionDiarizacion` con la tabla de transiciones propia, espejando `app/reuniones/state_machine.py` pero independiente (no toca `Reunion`).
    - Ejecutar 2.1 hasta verde; refactorizar manteniéndola verde.
    - _Requisitos: 9.1, 9.2, 9.3_

- [x] 3. Interfaz `MotorDiarizacion` y tipos de datos (`app/diarizacion/motor_diarizacion.py`)
  - [x] 3.1 Escribir prueba de propiedad de orden ascendente del Resultado_De_Diarizacion (RED)
    - **Property 6: Orden ascendente de los Segmentos_De_Hablante**
    - **Validates: Requirements 5.1**
    - Generar listas de `SegmentoDeHablante` y verificar que un `ResultadoDiarizacion` válido queda ordenado no decreciente por `inicio_ms`. Ejecutar y confirmar que falla.
  - [x] 3.2 Implementar `motor_diarizacion.py` (GREEN)
    - Definir la clase abstracta `MotorDiarizacion` (`diarizar`, `capacidades`) y los tipos `OpcionesDiarizacion`, `SegmentoDeHablante`, `ResultadoDiarizacion` (con orden ascendente por `inicio_ms`), `CapacidadesDiarizacion`, espejando `motor_asr.py`.
    - Ejecutar 3.1 hasta verde; refactorizar.
    - _Requisitos: 2.7, 5.1, 5.5_

- [x] 4. Fabrica_De_Diarizacion (`app/diarizacion/factory.py`)
  - [x] 4.1 Escribir prueba de propiedad de selección de proveedor (RED)
    - **Property 1: Selección del proveedor por configuración**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    - Generar `DIARIZATION_PROVIDER` con capitalización/espacios arbitrarios y casos ausente/vacío; verificar `Proveedor_Local` para "local"/vacío/ausente y `Proveedor_Nube` para "cloud". Confirmar que falla.
  - [x] 4.2 Escribir prueba de propiedad de valor inválido (RED)
    - **Property 2: Valor de proveedor inválido señala error con el valor recibido**
    - **Validates: Requirements 2.5**
    - Generar valores que normalizados no sean "local"/"cloud"/vacío; verificar `ValueError` cuyo mensaje incluye el valor recibido y que no se instancia ningún proveedor. Confirmar que falla.
  - [x] 4.3 Escribir pruebas por ejemplo de la fábrica (RED)
    - Casos: "local"/"cloud" con URL definida (Req 2.2, 2.3); `DIARIZATION_LOCAL_URL` ausente o vacía con proveedor local → `ValueError` indicando la ausencia de URL (Req 2.6). Confirmar que fallan.
    - _Requisitos: 2.2, 2.3, 2.6_
  - [x] 4.4 Implementar `factory.py` (GREEN)
    - Implementar `crear_motor_diarizacion()` espejando `crear_motor_asr`: normalizar `DIARIZATION_PROVIDER`, construir exactamente un proveedor, validar URL local y valor inválido.
    - Ejecutar 4.1, 4.2 y 4.3 hasta verde; refactorizar.
    - _Requisitos: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [x] 5. Proveedor_Local (`app/diarizacion/proveedor_local.py`)
  - [x] 5.1 Escribir prueba de propiedad de mapeo fiel de la respuesta local (RED)
    - **Property 4: Mapeo fiel de la respuesta local a Segmentos_De_Hablante**
    - **Validates: Requirements 3.4**
    - Generar respuestas con N elementos `{speaker, start_ms, end_ms}`; verificar N `SegmentoDeHablante` con `etiqueta_cruda/inicio_ms/fin_ms` preservados y en el mismo orden. Confirmar que falla.
  - [x] 5.2 Escribir pruebas por ejemplo del Proveedor_Local (RED)
    - Casos: error HTTP → fallo sin segmentos parciales (Req 3.5); timeout/inalcanzable → fallo (Req 3.6); respuesta sin clave `segments` → `ValueError`, distinguida de `segments: []` (lista vacía válida) (Req 3.7). Confirmar que fallan.
    - _Requisitos: 3.5, 3.6, 3.7_
  - [x] 5.3 Implementar `proveedor_local.py` (GREEN)
    - `POST {DIARIZATION_LOCAL_URL}/diarize` con `{"audio_ref": ...}`, timeout 600 s; conversión de segmentos; verificación explícita `if "segments" not in data`; propagación de excepciones. Espejar `transcripcion/proveedor_local.py`.
    - Ejecutar 5.1 y 5.2 hasta verde; refactorizar.
    - _Requisitos: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7_

- [x] 6. Proveedor_Nube (`app/diarizacion/proveedor_nube.py`)
  - [x] 6.1 Escribir prueba de propiedad de rechazo de endpoint no cifrado (RED)
    - **Property 3: Rechazo de endpoint no cifrado en el Proveedor_Nube**
    - **Validates: Requirements 4.2**
    - Generar `DIARIZATION_CLOUD_ENDPOINT` con esquemas distintos de `https`; verificar `ValueError` indicando el esquema no soportado, sin transmitir audio. Confirmar que falla.
  - [x] 6.2 Escribir prueba de propiedad de validez de los segmentos (RED)
    - **Property 5: Validez de los Segmentos_De_Hablante del resultado**
    - **Validates: Requirements 4.5, 5.2, 5.3, 5.4**
    - Generar respuestas externas; verificar para cada `SegmentoDeHablante`: `inicio_ms`/`fin_ms` enteros, `inicio_ms ≥ 0`, `fin_ms ≥ inicio_ms`, `fin_ms ≤ Duracion_De_Grabacion`, y `etiqueta_cruda` no vacía. Confirmar que falla.
  - [x] 6.3 Escribir pruebas por ejemplo del Proveedor_Nube (RED)
    - Casos: `DIARIZATION_CLOUD_API_KEY` ausente/vacía → `ValueError` (Req 4.4); timeout 120 s / error HTTP / respuesta sin segmentos válidos → `ErrorServicioExterno` conservando el audio (Req 4.6). Confirmar que fallan.
    - _Requisitos: 4.4, 4.6_
  - [x] 6.4 Implementar `proveedor_nube.py` (GREEN)
    - `__init__` lee y valida `DIARIZATION_CLOUD_API_KEY` y esquema `https` de `DIARIZATION_CLOUD_ENDPOINT`; `diarizar` por HTTPS con `Authorization: Bearer`, timeout 120 s; `_parsear_y_validar_respuesta` (adaptando `text`→`speaker`); `ErrorServicioExterno`. Espejar `transcripcion/proveedor_nube.py`.
    - Ejecutar 6.1, 6.2 y 6.3 hasta verde; refactorizar.
    - _Requisitos: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [x] 7. Etiquetador_De_Hablantes (`app/diarizacion/etiquetado.py`)
  - [x] 7.1 Escribir prueba de propiedad de número de hablantes (RED)
    - **Property 7: Número de hablantes igual a etiquetas crudas distintas**
    - **Validates: Requirements 5.5, 6.1**
    - Verificar biyección entre `Etiqueta_De_Hablante_Cruda` distintas y `Hablante`, y `num_hablantes` igual a esa cantidad. Confirmar que falla.
  - [x] 7.2 Escribir prueba de propiedad de etiquetado anónimo, ordenado y determinista (RED)
    - **Property 8: Etiquetado anónimo, ordenado y determinista de hablantes**
    - **Validates: Requirements 6.2, 6.3, 6.4**
    - Verificar orden por primer `inicio_ms` con desempate lexicográfico de la etiqueta cruda, `orden` consecutivo desde 1, `Etiqueta_De_Hablante = "Hablante N"`, sin campos de identidad nominal. Confirmar que falla.
  - [x] 7.3 Implementar `etiquetado.py` (GREEN)
    - `etiquetar_hablantes(segmentos) -> list[Hablante]` como función pura según el diseño.
    - Ejecutar 7.1 y 7.2 hasta verde; refactorizar.
    - _Requisitos: 5.5, 6.1, 6.2, 6.3, 6.4_

- [x] 8. Asignador_De_Turnos (`app/diarizacion/asignacion.py`)
  - [x] 8.1 Escribir prueba de propiedad de asignación por máximo solape (RED)
    - **Property 9: Asignación de Turnos por máximo solape con desempate determinista**
    - **Validates: Requirements 7.1, 7.2**
    - Generar topologías de solape adversas (turnos que cruzan varios segmentos, empates exactos, solape cero); verificar una `Asignacion_De_Hablante` por turno al `Hablante` de máximo solape acumulado, con desempate por menor `orden`. Confirmar que falla.
  - [x] 8.2 Escribir prueba de propiedad de preservación de los Turnos_De_Habla (RED)
    - **Property 10: Preservación de los Turnos_De_Habla de la Transcripcion**
    - **Validates: Requirements 7.3**
    - Verificar que `texto`, `inicio_ms`, `fin_ms` y `orden` de cada turno quedan sin modificar tras producir asignaciones. Confirmar que falla.
  - [x] 8.3 Implementar `asignacion.py` (GREEN)
    - `asignar_turnos(turnos, segmentos, hablantes)` como función pura: solape `max(0, min(te,se) - max(ts,ss))`, máximo acumulado, desempate por menor `orden`; cero turnos o cero segmentos → cero asignaciones.
    - Ejecutar 8.1 y 8.2 hasta verde; refactorizar.
    - _Requisitos: 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 9. Checkpoint - Asegurar que todas las pruebas de lógica pura pasan
  - 32 tests passing (confirmed 2026-06-12). All pure logic GREEN.

- [x] 10. Modelos ORM y migración Alembic 003
  - [x] 10.1 Añadir los modelos ORM a `app/infra/models.py`
    - Definir `Diarizacion` (tabla `diarizaciones`, `UniqueConstraint uq_diarizacion_reunion_id`), `Hablante` (tabla `hablantes`) y `AsignacionDeHablante` (tabla `asignaciones_de_hablante`, `UniqueConstraint uq_asignacion_turno_id`) con relaciones `back_populates`, siguiendo las convenciones existentes (PK `String(36)`, FKs `ondelete="CASCADE"`, `DateTime(timezone=True)`). Sin columnas/relaciones nuevas sobre `Reunion`/`Transcripcion`/`TurnoDeHabla`.
    - _Requisitos: 8.1, 8.4, 9.3, 9.4, 10.5_
  - [x] 10.2 Escribir prueba de integración de la migración 003 (RED)
    - Verificar `upgrade()`/`downgrade()` sobre la base de prueba: creación de las tres tablas, FKs en cascada y las restricciones de unicidad `uq_diarizacion_reunion_id` y `uq_asignacion_turno_id`; verificar que `downgrade` revierte en orden inverso. Confirmar que falla (migración aún inexistente).
    - _Requisitos: 8.1, 10.5_
  - [x] 10.3 Crear la migración `alembic/versions/003_diarizacion_schema.py` (GREEN)
    - `revision="003_diarizacion_schema"`, `down_revision="002_uq_transcripcion"`; `create_table` para las tres tablas con sus FKs `ondelete="CASCADE"`, columnas UUID y las `UniqueConstraint`; `downgrade()` en orden inverso. Bug de enums de Alembic resuelto (columnas `String` en 001/003, sin enums de Postgres). Validada en PostgreSQL real.
    - Ejecutar 10.2 hasta verde; refactorizar.
    - _Requisitos: 8.1, 8.4, 9.3, 9.4, 10.5_

- [x] 11. Repositorio_De_Diarizacion (`app/diarizacion/repository.py`)
  - [x] 11.1 Escribir prueba de propiedad de unicidad por Reunion (RED)
    - **Property 12: Unicidad de la Diarizacion por Reunion**
    - **Validates: Requirements 8.1, 10.5**
    - Sobre sesiones de prueba, verificar que múltiples procesamientos/reintentos del mismo `reunion_id` no producen más de una `Diarizacion`. Confirmar que falla.
  - [x] 11.2 Escribir prueba de propiedad de atomicidad de la persistencia (RED)
    - **Property 13: Atomicidad de la persistencia**
    - **Validates: Requirements 8.2, 8.3, 10.6**
    - Inyectar fallo a mitad de escritura; verificar rollback total (sin registros parciales) y propagación del fallo. Confirmar que falla.
  - [x] 11.3 Escribir prueba de propiedad de registro de metadatos del proveedor (RED)
    - **Property 14: Registro de metadatos del proveedor**
    - **Validates: Requirements 8.4**
    - Verificar que la `Diarizacion` persiste `proveedor` y `num_hablantes` consistentes con `capacidades()` y el resultado. Confirmar que falla.
  - [x] 11.4 Escribir prueba de propiedad de round-trip persistencia/recuperación (RED)
    - **Property 15: Round-trip de persistencia y recuperación**
    - **Validates: Requirements 8.5**
    - Persistir `Diarizacion` + `Hablantes` + `Asignaciones` y verificar que `obtener_por_reunion` recupera todo equivalente (con `selectinload`). Confirmar que falla.
  - [x] 11.5 Escribir prueba por ejemplo de consulta sin Diarizacion (RED)
    - `obtener_por_reunion` sobre una `Reunion` sin `Diarizacion` → `None`, sin error (Req 8.6). Confirmar que falla.
    - _Requisitos: 8.6_
  - [x] 11.6 Implementar `repository.py` (GREEN)
    - `crear(session, diarizacion, hablantes, asignaciones)` agregando a la sesión provista (sin commit propio) y `obtener_por_reunion(reunion_id)` con `selectinload`. Espejar `transcripcion/repository.py`.
    - Ejecutar 11.1–11.5 hasta verde; refactorizar.
    - _Requisitos: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 10.5, 10.6_

- [x] 12. Generalizar la cola para `DIARIZATION_MAX_RETRIES` (`app/infra/queue_rabbitmq.py`)
  - [x] 12.1 Escribir prueba de la lectura/validación de reintentos por tema (RED)
    - Verificar que `_leer_max_retries` honra `DIARIZATION_MAX_RETRIES` para el tema `"diarizar"` (rango 0–10, default 3) sin romper la lectura de `ASR_MAX_RETRIES` para `"transcribir"`; validar acotación del rango como lógica pura. Confirmar que falla.
    - _Requisitos: 10.2_
  - [x] 12.2 Generalizar `_leer_max_retries` en `queue_rabbitmq.py` (GREEN)
    - Parametrizar la lectura de la variable de reintentos por tema (sin alterar el comportamiento existente de `transcribir`), conservando rango 0–10 y default 3.
    - Ejecutar 12.1 hasta verde; refactorizar.
    - _Requisitos: 10.2_

- [x] 13. Worker_De_Diarizacion (`app/diarizacion/worker.py`)
  - [x] 13.1 Escribir prueba de propiedad de entrada inválida / insumo ausente (RED)
    - **Property 19: Entrada inválida o insumo ausente no persiste ni lanza excepción**
    - **Validates: Requirements 1.3, 1.4, 1.5, 1.6**
    - Generar mensajes con `reunion_id` ausente/vacío/solo-espacios/no-cadena, `reunion_id` inexistente, y `Reunion` sin `Transcripcion`; verificar terminación sin excepción y sin persistir. Confirmar que falla.
  - [x] 13.2 Escribir prueba de propiedad de resultado vacío → Diarizacion vacía válida (RED)
    - **Property 11: Resultado sin hablantes produce Diarizacion vacía válida**
    - **Validates: Requirements 7.4, 7.5**
    - Resultado con segmentos vacíos → `Diarizacion` con cero `Hablantes`/`Asignaciones`, `Estado_De_Diarizacion="completada"`, sin error; `Transcripcion` sin turnos → cero asignaciones. Confirmar que falla.
  - [x] 13.3 Escribir prueba de propiedad de fallo del motor (RED)
    - **Property 20: Fallo del motor se propaga sin persistir Diarizacion completada**
    - **Validates: Requirements 9.3, 10.1**
    - Excepción del motor → estado `"fallida"` con causa `"fallo_del_motor"`, propagación del fallo y sin `Diarizacion` en `"completada"`. Confirmar que falla.
  - [x] 13.4 Escribir prueba de propiedad de preservación del Estado_De_Proceso (RED)
    - **Property 18: Preservación del Estado_De_Proceso de la Reunion**
    - **Validates: Requirements 9.5**
    - Para cualquier `Estado_De_Proceso` inicial y cualquier desenlace, el `Estado_De_Proceso` de la `Reunion` permanece sin cambios (sin llamar a `registrar_transicion`). Confirmar que falla.
  - [x] 13.5 Escribir prueba de propiedad de marca UTC en cada cambio de estado (RED)
    - **Property 17: Cada cambio de estado registra una marca UTC**
    - **Validates: Requirements 9.4**
    - Cada transición exitosa registra `actualizada_en` en UTC. Confirmar que falla.
  - [x] 13.6 Escribir pruebas por ejemplo del worker (RED)
    - Casos: `reunion_id` inexistente → `ack` sin persistir (Req 1.5); `Reunion` sin `Transcripcion` → `ack` sin persistir (Req 1.6). Confirmar que fallan.
    - _Requisitos: 1.5, 1.6_
  - [x] 13.7 Implementar `worker.py` (GREEN)
    - Implementar `_procesar_diarizacion` (validar mensaje, cargar `Reunion`/`Transcripcion`, marcar `en_proceso`, crear motor, diarizar, etiquetar, asignar, persistir en una transacción, marcar `completada`/`fallida`) e `iniciar_worker` suscrito al tema `"diarizar"`. Espejar `transcripcion/worker.py`.
    - Ejecutar 13.1–13.6 hasta verde; refactorizar.
    - _Requisitos: 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 6.1, 7.1, 8.2, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1_

- [x] 14. Servicio_De_Diarizacion_Local (`diar-engine`)
  - [x] 14.1 Escribir prueba de contrato de `POST /diarize` y `GET /health` (RED)
    - Verificar el contrato: request `{"audio_ref": str}`, response `{"segments": [{"speaker","start_ms","end_ms"}...], "num_speakers": int}` (cero o más segmentos), y `GET /health → {"status":"ok"}`. Confirmar que falla.
    - _Requisitos: 3.1, 3.3_
  - [x] 14.2 Implementar `diar-engine/main.py` y su `Dockerfile` (GREEN)
    - Servicio FastAPI que descarga el audio del `Almacen_De_Objetos` por `audio_ref` (espejando `asr-engine/main.py`), ejecuta la diarización REAL (pyannote.audio) y devuelve los segmentos; añadir `Dockerfile`.
    - Ejecutar 14.1 hasta verde; refactorizar.
    - _Requisitos: 3.1, 3.3_

- [x] 15. Integración y cableado
  - [x] 15.1 Escribir prueba de integración de suscripción y publicación (RED)
    - Verificar que el worker se suscribe al tema `"diarizar"` al iniciar (Req 1.1) y que se publica un `Mensaje_De_Diarizacion` con `reunion_id` cuando una `Transcripcion` queda disponible (Req 1.2). Confirmar que falla.
    - _Requisitos: 1.1, 1.2_
  - [x] 15.2 Escribir prueba de integración de ack/nack/DLX y reintentos (RED)
    - Verificar `ack` tras éxito (Req 1.7), `nack` sin reencolar inmediato tras excepción (Req 1.8), derivación a DLX (Req 1.9, 10.3), descarte sin DLX (Req 10.4) y reintentos acotados por `DIARIZATION_MAX_RETRIES` (Req 10.2). Confirmar que falla.
    - _Requisitos: 1.7, 1.8, 1.9, 10.2, 10.3, 10.4_
    - Nota: ack/nack/DIARIZATION_MAX_RETRIES verificados en `test_integration.py`; DLX/descarte son comportamientos de la `ColaDeRabbitMQ` compartida (agnósticos al tema) cubiertos por `tests/test_queue.py`.
  - [x] 15.3 Cablear el arranque del worker y la publicación del mensaje (GREEN)
    - Registrar/arrancar el `Worker_De_Diarizacion` en el punto de entrada de workers (`app/worker.py`) y encolar el `Mensaje_De_Diarizacion` al completarse la transcripción, sin modificar el `Estado_De_Proceso` de la `Reunion`.
    - Ejecutar 15.1 y 15.2 hasta verde; refactorizar.
    - _Requisitos: 1.1, 1.2, 9.5_
  - [x] 15.4 Escribir prueba de humo de egreso HTTPS + autenticación del Proveedor_Nube (RED)
    - Verificar que el `Proveedor_Nube` transmite por HTTPS con cabecera `Authorization: Bearer` (Req 4.1, 4.3) usando un transporte simulado. Ejecutar y confirmar resultado.
    - _Requisitos: 4.1, 4.3_

- [x] 16. Checkpoint final - Asegurar que todas las pruebas pasan
  - 120 tests passing (confirmed 2026-06-12). Stack real validado: migración 003 aplicada en PostgreSQL, worker suscrito a 'diarizar' en runtime.

## Notes

- Disciplina TDD estricta (AGENTS.md §3): toda tarea de prueba (propiedad, ejemplo o integración) es **obligatoria** y **nunca** se marca con `*`; se escribe y ejecuta antes de su implementación y debe fallar primero (RED), luego pasar (GREEN) y mantenerse verde tras refactorizar.
- Cada propiedad de corrección (1–20) es una sub-tarea de prueba separada, anotada con su número de propiedad y los requisitos que valida.
- Las pruebas de propiedad usan Hypothesis con `@settings(max_examples=100)` (mínimo 100 ejemplos) y la etiqueta `# Feature: identificacion-hablantes, Property {N}: ...`.
- Cada tarea referencia los requisitos que satisface para trazabilidad (mapa 1:1 spec ↔ milestone, AGENTS.md §13).
- La Tarea 12 cierra la brecha de integración: generalizar `_leer_max_retries` para honrar `DIARIZATION_MAX_RETRIES` en el tema `"diarizar"` sin romper `ASR_MAX_RETRIES`.
- Los checkpoints (9 y 16) aseguran validación incremental ejecutando toda la suite.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.1", "5.1", "6.1", "7.1", "8.1", "10.1", "12.1", "14.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "4.2", "5.2", "6.2", "7.2", "8.2", "10.2", "11.1", "12.2", "14.2"] },
    { "id": 3, "tasks": ["4.3", "5.3", "6.3", "7.3", "8.3", "10.3", "11.2"] },
    { "id": 4, "tasks": ["6.4", "11.3"] },
    { "id": 5, "tasks": ["4.4", "11.4"] },
    { "id": 6, "tasks": ["11.5"] },
    { "id": 7, "tasks": ["11.6"] },
    { "id": 8, "tasks": ["13.1"] },
    { "id": 9, "tasks": ["13.2"] },
    { "id": 10, "tasks": ["13.3"] },
    { "id": 11, "tasks": ["13.4"] },
    { "id": 12, "tasks": ["13.5"] },
    { "id": 13, "tasks": ["13.6"] },
    { "id": 14, "tasks": ["13.7"] },
    { "id": 15, "tasks": ["15.1"] },
    { "id": 16, "tasks": ["15.2"] },
    { "id": 17, "tasks": ["15.3", "15.4"] }
  ]
}
```
