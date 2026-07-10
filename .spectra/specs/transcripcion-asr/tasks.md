# Implementation Plan: Transcripción (ASR)

## Overview

Este plan completa y corrige el scaffold existente del módulo **Transcripción (ASR)** (`backend/app/transcripcion/`, `backend/asr-engine/`, `backend/app/infra/`) para cumplir los requerimientos de `requirements.md` y las decisiones de `design.md`. No se construye desde cero: cada tarea ajusta un archivo ya presente según la tabla "Estado del scaffold vs. requerimientos" del diseño.

Lenguaje de implementación: **Python** (el diseño usa Python; el backend ya usa Python/pytest). Las pruebas se ejecutan con la configuración existente (`backend/pyproject.toml`, `backend/tests/conftest.py`) en modo de ejecución única (no watch).

Decisiones de diseño clave reflejadas en las tareas:
- El `Worker_De_Transcripcion` controla una **única transacción** que abarca la persistencia (`Transcripcion` + `Turnos_De_Habla`) y la transición de estado; los métodos del `Repositorio_De_Transcripcion` operan **sobre la sesión provista por el worker**.
- Se requiere una **migración Alembic** que añada `UniqueConstraint(reunion_id)` a `transcripciones` (consciente del bug de creación de tipos enum en `001_initial_schema.py`).
- 17 propiedades de corrección se prueban con **Hypothesis** (mínimo 100 ejemplos, etiqueta `# Feature: transcripcion-asr, Property N: ...`). Las pruebas (propiedad, ejemplo, integración) se marcan opcionales con `*`.

Las tareas son atómicas para mapear 1:1 a issues de GitHub (AGENTS.md §13).

## Tasks

- [x] 1. Configurar infraestructura de pruebas del módulo
  - [x] 1.1 Configurar `conftest.py` con fixtures compartidas
    - Añadir a `backend/tests/conftest.py` un fixture de sesión async de SQLAlchemy contra una base de datos de prueba (motor + `create_session_factory` de `app/infra/database.py`), con creación/derribo del esquema vía `Base.metadata`
    - Añadir un perfil de Hypothesis con `max_examples=100` y registrar fixtures para mocks de `httpx` y de la `ColaDeTrabajos`
    - Verificar que `hypothesis` y `pytest-asyncio` (ya en `pyproject.toml`) cargan en la suite
    - _Requirements: 7.3, 7.7_

- [x] 2. Ajustar el esquema de datos para la unicidad por Reunion
  - [x] 2.1 Añadir `UniqueConstraint(reunion_id)` al modelo `Transcripcion`
    - Modificar `backend/app/infra/models.py`: agregar `__table_args__ = (UniqueConstraint("reunion_id", name="uq_transcripcion_reunion_id"),)` a la clase `Transcripcion`
    - _Requirements: 7.1, 9.5_

  - [x] 2.2 Crear migración Alembic para la restricción única
    - Crear `backend/alembic/versions/002_*.py` con `down_revision="001_initial_schema"` que añada la `UniqueConstraint` sobre `transcripciones.reunion_id` en `upgrade()` y la elimine en `downgrade()`
    - Tener en cuenta el bug de tech-debt en `001_initial_schema.py` (creación de tipos enum): la nueva migración NO debe recrear ni redefinir los tipos enum existentes; limitarse a la restricción única
    - _Requirements: 7.1, 9.5_

- [x] 3. Completar la `Fabrica_De_Motor` (`factory.py`)
  - [x] 3.1 Implementar normalización, selección y validación del proveedor
    - En `backend/app/transcripcion/factory.py`: normalizar `ASR_PROVIDER` con `strip().lower()`; `""`/ausente y `"local"` → `ProveedorLocal(ASR_LOCAL_URL)`; `"cloud"` → `ProveedorNube`
    - Otro valor → `ValueError` que incluya el valor inválido recibido; `ProveedorLocal` con `ASR_LOCAL_URL` ausente/vacía → `ValueError` indicando la ausencia de la URL
    - Construir exactamente un proveedor por invocación
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 3.2 Prueba de propiedad — selección por configuración
    - **Property 1: Selección del proveedor por configuración**
    - Generadores: `"local"`/`"cloud"` con capitalización y espacios arbitrarios; ausente/vacío/solo-espacios
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

  - [x] 3.3 Prueba de propiedad — valor inválido señala error con el valor recibido
    - **Property 2: Valor de proveedor inválido señala error con el valor recibido**
    - **Validates: Requirements 2.5**

  - [x] 3.4 Pruebas por ejemplo de la fábrica
    - Casos dirigidos: `"local"`/`"cloud"` con URL válida (Req. 2.2, 2.3) y `ASR_LOCAL_URL` ausente → `ValueError` (Req. 2.6)
    - _Requirements: 2.2, 2.3, 2.6_

- [x] 4. Completar el `Proveedor_Local` (`proveedor_local.py`)
  - [x] 4.1 Distinguir respuesta sin la clave `segments` de lista vacía válida
    - En `backend/app/transcripcion/proveedor_local.py`: reemplazar `data.get("segments", [])` por verificación explícita de presencia de la clave; ausencia de `segments` → señalar fallo (excepción); `segments: []` → resultado válido vacío
    - Mantener `POST {ASR_LOCAL_URL}/transcribe` con timeout 300 s, mapeo `text/start_ms/end_ms` → `SegmentoTranscripcion`, e idioma desde `language`
    - _Requirements: 3.4, 3.5, 3.6, 3.7_

  - [x] 4.2 Prueba de propiedad — mapeo fiel de la respuesta local
    - **Property 4: Mapeo fiel de la respuesta local a segmentos**
    - **Validates: Requirements 3.4**

  - [x] 4.3 Prueba de propiedad — orden ascendente del resultado
    - **Property 6: Orden ascendente de los segmentos**
    - **Validates: Requirements 5.1**

  - [x] 4.4 Pruebas por ejemplo del proveedor local
    - Error HTTP (Req. 3.5), timeout/inalcanzable (Req. 3.6) y respuesta sin `segments` (Req. 3.7), todas propagando excepción sin segmentos parciales
    - _Requirements: 3.5, 3.6, 3.7_

- [x] 5. Completar el `Proveedor_Nube` (`proveedor_nube.py`)
  - [x] 5.1 Exigir credencial, timeout y validación de segmentos
    - En `backend/app/transcripcion/proveedor_nube.py`: en inicialización, exigir `ASR_CLOUD_API_KEY` no vacía (`ValueError` indicando ausencia de credencial) y endpoint `https://` (ya presente)
    - Transmitir por HTTPS autenticando con la API key, timeout 30 s; validar cada segmento (`texto` no vacío, `inicio_ms`/`fin_ms` enteros ≥ 0, `fin_ms ≥ inicio_ms`)
    - Timeout/error/respuesta sin segmentos válidos → abortar, conservar la `Grabacion_De_Audio` sin modificar y señalar error del servicio externo
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6_

  - [x] 5.2 Prueba de propiedad — rechazo de endpoint no cifrado
    - **Property 3: Rechazo de endpoint no cifrado en el Proveedor_Nube**
    - **Validates: Requirements 4.2**

  - [x] 5.3 Prueba de propiedad — validez de los segmentos del resultado
    - **Property 5: Validez de los segmentos del resultado**
    - **Validates: Requirements 4.5, 5.2, 5.3, 5.4**

  - [x] 5.4 Pruebas por ejemplo/integración del proveedor nube
    - `ASR_CLOUD_API_KEY` ausente → `ValueError` (Req. 4.4); timeout cloud → error (Req. 4.6); integración: uso de HTTPS y cabecera de autenticación (Req. 4.1, 4.3)
    - _Requirements: 4.1, 4.3, 4.4, 4.6_

- [x] 6. Checkpoint - Proveedores y fábrica
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Completar el `Repositorio_De_Transcripcion` (`repository.py`)
  - [x] 7.1 `crear` opera sobre la sesión provista por el worker
    - En `backend/app/transcripcion/repository.py`: cambiar `crear` para aceptar una `AsyncSession` provista por el llamador (sin abrir/cerrar ni hacer commit), agregando `Transcripcion` y sus `Turnos_De_Habla` a esa sesión, dentro de la transacción del worker
    - _Requirements: 7.3, 7.4, 9.6_

  - [x] 7.2 `obtener_por_reunion` recupera la transcripción con sus turnos
    - En `repository.py`: cargar los `TurnoDeHabla` asociados (carga ansiosa o consulta de turnos); devolver `None` si no existe
    - _Requirements: 7.7, 7.8_

  - [x] 7.3 Prueba de propiedad — round-trip de persistencia y recuperación
    - **Property 13: Round-trip de persistencia y recuperación**
    - Usar la base de datos de prueba con sesión transaccional del fixture
    - **Validates: Requirements 7.7**

  - [x] 7.4 Prueba por ejemplo — consulta sin transcripción
    - `obtener_por_reunion` devuelve `None` cuando no existe transcripción (sin error)
    - _Requirements: 7.8_

- [x] 8. Completar el `Worker_De_Transcripcion` (`worker.py`)
  - [x] 8.1 Validar el mensaje y cargar la `Reunion`
    - En `backend/app/transcripcion/worker.py`: extraer `reunion_id`/`audio_ref`; si alguno está ausente, vacío o solo-espacios → terminar sin excepción y sin persistir; si la `Reunion` no existe → terminar sin excepción y sin persistir (habilita `ack`)
    - _Requirements: 1.2, 1.3, 1.4_

  - [x] 8.2 Aplicar la transición inicial `grabando → transcribiendo`
    - Si el estado actual es `grabando`, invocar `registrar_transicion(session, reunion, "grabacion_subida")` dentro de la transacción del worker
    - _Requirements: 8.1_

  - [x] 8.3 Persistir en una transacción única y transicionar a `completado`
    - Con segmentos: mapear `Segmentos_De_Transcripcion` a `Turnos_De_Habla` con `orden` iniciando en **1** y ascendente por `inicio_ms`; persistir vía `Repositorio_De_Transcripcion.crear(session, ...)`; `idioma = resultado.idioma or "es-CO"`; `proveedor`/`soporta_turnos` desde `motor.capacidades()` (no de `os.environ`); luego `registrar_transicion(..., "transcripcion_completada")` en la misma transacción
    - _Requirements: 5.5, 6.3, 6.4, 7.1, 7.3, 7.5, 7.6, 8.2_

  - [x] 8.4 Manejar resultado sin contenido transcribible
    - Lista vacía válida: no persistir `Transcripcion`, transicionar a `fallido` con causa `fallo_del_motor` vía evento `fallo_motor`, y terminar sin excepción (habilita `ack`)
    - _Requirements: 5.6, 7.2, 8.3_

  - [x] 8.5 Propagar el fallo del motor para habilitar reintentos
    - Una excepción del `MotorASR` (error HTTP, timeout, estructura inválida, error de configuración) se propaga sin persistir ninguna `Transcripcion`
    - _Requirements: 9.1_

  - [x] 8.6 Prueba de propiedad — entrada inválida no persiste ni lanza excepción
    - **Property 16: Entrada inválida no persiste ni lanza excepción**
    - **Validates: Requirements 1.3, 1.4**

  - [x] 8.7 Prueba de propiedad — corrección de la máquina de estados
    - **Property 14: Corrección de la máquina de estados**
    - Ejercita `aplicar_evento` sobre pares (estado, evento) generados
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.5**

  - [x] 8.8 Prueba de propiedad — registro de historial en cada transición
    - **Property 15: Registro de historial en cada transición**
    - **Validates: Requirements 8.4**

  - [x] 8.9 Prueba de propiedad — mapeo de segmentos a turnos
    - **Property 7: Mapeo de segmentos a turnos preserva orden y marcas sin identidad**
    - **Validates: Requirements 5.5, 7.6**

  - [x] 8.10 Prueba de propiedad — selección del idioma de la Transcripcion
    - **Property 9: Selección del idioma de la Transcripcion**
    - **Validates: Requirements 6.3, 6.4**

  - [x] 8.11 Prueba de propiedad — registro de metadatos del proveedor
    - **Property 12: Registro de metadatos del proveedor**
    - **Validates: Requirements 7.5**

  - [x] 8.12 Prueba de propiedad — resultado sin segmentos no produce Transcripcion
    - **Property 8: Resultado sin segmentos no produce Transcripcion**
    - **Validates: Requirements 5.6, 7.2**

  - [x] 8.13 Prueba de propiedad — fallo del motor se propaga sin persistir
    - **Property 17: Fallo del motor se propaga sin persistir**
    - **Validates: Requirements 9.1**

  - [x] 8.14 Prueba de propiedad — unicidad de la Transcripcion por Reunion
    - **Property 10: Unicidad de la Transcripcion por Reunion**
    - Reprocesar/reintentar el mismo mensaje y verificar a lo sumo una `Transcripcion`; requiere la migración 2.2
    - **Validates: Requirements 7.1, 9.5**

  - [x] 8.15 Prueba de propiedad — atomicidad de la persistencia
    - **Property 11: Atomicidad de la persistencia**
    - Inyectar un fallo durante la persistencia y verificar rollback total (ni `Transcripcion` ni `Turnos` parciales) con propagación de fallo
    - **Validates: Requirements 7.3, 7.4, 9.6**

  - [x] 8.16 Prueba por ejemplo — idioma prioritario por defecto al motor
    - El worker invoca al motor con `OpcionesTranscripcion(idioma_prioritario="es-CO")` cuando no hay configuración explícita
    - _Requirements: 6.1, 6.2_

- [x] 9. Checkpoint - Worker y persistencia transaccional
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Completar reintentos acotados y dead-letter en la `Cola_De_Trabajos` (`queue_rabbitmq.py`)
  - [x] 10.1 Conteo de reintentos acotado con `ASR_MAX_RETRIES`
    - En `backend/app/infra/queue_rabbitmq.py`: leer `ASR_MAX_RETRIES` (rango 0–10, default 3, con validación del rango) y contar reintentos del mensaje (p. ej. encabezado `x-death` o contador en el mensaje); reencolar mientras los reintentos `< ASR_MAX_RETRIES`
    - _Requirements: 9.2_

  - [x] 10.2 Derivación a dead-letter y descarte con registro
    - Configurar DLX para derivar a dead-letter al agotar reintentos (Req. 1.7, 9.3); sin DLX, descartar registrando el agotamiento de reintentos (Req. 9.4); mantener `nack` sin reencolar inmediato ante excepción (Req. 1.6)
    - _Requirements: 1.6, 1.7, 9.3, 9.4_

  - [x] 10.3 Prueba por ejemplo — validación del rango de `ASR_MAX_RETRIES`
    - Valores fuera de 0–10 rechazados; default 3 cuando ausente
    - _Requirements: 9.2_

  - [x] 10.4 Pruebas de integración de la cola
    - `ack` tras éxito (Req. 1.5), `nack` sin requeue ante excepción (Req. 1.6), reencolado con reintentos (Req. 9.2), derivación a dead-letter (Req. 1.7, 9.3) y descarte sin DLX (Req. 9.4)
    - _Requirements: 1.5, 1.6, 1.7, 9.2, 9.3, 9.4_

- [x] 11. Integrar el `Servicio_ASR_Local` (`asr-engine/main.py`)
  - [x] 11.1 Implementar faster-whisper preservando el contrato
    - En `backend/asr-engine/main.py`: reemplazar el stub por la integración real con faster-whisper, conservando el contrato `POST /transcribe` (`{audio_ref, language}` → `{segments:[{text,start_ms,end_ms}], language}`) y `GET /health`
    - _Requirements: 3.3_

  - [x] 11.2 Prueba de integración del contrato del asr-engine
    - Verificar `POST /transcribe` (forma de la respuesta) y `GET /health`
    - _Requirements: 3.3_

- [x] 12. Cableado e integración final
  - [x] 12.1 Asegurar la suscripción y el wiring del worker
    - Verificar/ajustar `iniciar_worker(cola, session_factory)` para suscribirse al tema `"transcribir"` al iniciar y que el wiring de `cola`/`session_factory` quede conectado en el arranque del backend
    - _Requirements: 1.1_

  - [x] 12.2 Prueba de integración — suscripción al tema "transcribir"
    - Verificar que al iniciar, el worker se suscribe al tema `"transcribir"`
    - _Requirements: 1.1_

- [x] 13. Checkpoint final - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Las tareas marcadas con `*` son opcionales (pruebas de propiedad, por ejemplo e integración) y pueden omitirse para un MVP más rápido. Por convención del proyecto (AGENTS.md §13) reciben además las etiquetas `test` y, las de propiedad, `pbt` al crear el issue de GitHub.
- Cada tarea referencia los requerimientos que satisface para trazabilidad y mapeo 1:1 a issues de GitHub.
- Las pruebas de propiedad usan Hypothesis con mínimo 100 ejemplos y la etiqueta `# Feature: transcripcion-asr, Property N: ...`; cada propiedad de corrección se implementa con una sola prueba.
- Los checkpoints aseguran validación incremental; las pruebas se ejecutan en modo de ejecución única (no watch) con la configuración de `backend/pyproject.toml`.
- El worker mantiene una única transacción que abarca persistencia y transición de estado; el repositorio opera sobre la sesión provista.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "3.1", "4.1", "5.1", "7.1", "10.1", "11.1"] },
    { "id": 1, "tasks": ["2.2", "7.2", "10.2", "3.2", "3.3", "3.4", "4.2", "4.3", "4.4", "5.2", "5.3", "5.4", "11.2"] },
    { "id": 2, "tasks": ["7.3", "7.4", "10.3", "10.4", "8.1"] },
    { "id": 3, "tasks": ["8.2"] },
    { "id": 4, "tasks": ["8.3"] },
    { "id": 5, "tasks": ["8.4"] },
    { "id": 6, "tasks": ["8.5"] },
    { "id": 7, "tasks": ["8.6", "8.7", "8.8", "8.9", "8.10", "8.11", "8.12", "8.13", "8.14", "8.15", "8.16", "12.1"] },
    { "id": 8, "tasks": ["12.2"] }
  ]
}
```
