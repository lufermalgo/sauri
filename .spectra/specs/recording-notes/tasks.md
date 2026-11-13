# Plan de Implementación — Notas asociadas a una grabación

## Estado, autoridad y alcance

**Fase redactada para revisión; no aprobada para implementar.** Tarjeta APX `task_da770723a44e445e`. Requisitos y diseño aprobados e integrados mediante PR #187; diseño exacto `eb80f4e`, blob `21bea048644f28636dc8b5b64a213d1771371ce7`. Base técnica contrastada: `origin/main` `41ab5f4017b9a6547b42aef8630ff41999f0557e` (13/11/2026). Los requisitos siguen siendo R1.1–1.2 y R2.1–2.3; no se agregan capacidades a partir del código.

Resultado funcional previsto: añadir una nota desde la extensión o la entrada de notas de un control flotante **ya visible y autorizado**, conservar su grabación de destino y consultarla en el portal separada de la transcripción. No incluye edición, borrado individual, Markdown, formato/longitud de producto, control oculto, nueva captura, permisos Chrome, reconocimiento de voz ni cambios de acceso/retención.

La identidad durable de captura y subida ya existe en `extension/src/recording-db.ts`, `upload-queue.ts`, `background.ts` y `core/recording-completion.ts`; **se consume y extiende, no se reemplaza ni se crea otra cola de subida**. Las tarjetas de reuniones llamadas `NoteDTO`/“My Notes” no son notas de grabación. La respuesta de meeting ya puede exponer `recording_id` tras autorización: probar y reutilizar antes de añadir otro lookup.

Los encargos de implementación deben vincular esta spec, tarea y criterio, issue, base/SHA, ejecutor, rama/worktree bajo `.worktrees/`, dependencias, pruebas y contrato de cierre. No se generan ahora issues de implementación masivos ni se inicia una asignación. Ansel verifica cada entrega; Fer conserva el merge. Un PR listo no equivale a integración ni aceptación de producto.

## Resumen de Fases

| Fase | Descripción | Tareas | Dependencias |
|---|---|---|---|
| 0 | Preflight de pruebas, política y superficie flotante | T0 | Ninguna |
| 1 | RED/GREEN de persistencia y ciclo de vida del servidor | T1–T2 | T0 |
| 2 | RED/GREEN de API privada, idempotencia y lookup | T3–T4 | T0; T2 antes de T4 |
| 3 | RED/GREEN de outbox y entrega durable en extensión | T5–T8 | T0; T4 antes de T8 |
| 4 | RED/GREEN de entradas de extensión y portal separado | T9–T12 | T8 para T10; T4 para T12 |
| 5 | Integración, seguridad y validación de entrega | T13–T15 | Todas las piezas pertinentes |

Total: **16 tareas**, incluidas **7 tareas de pruebas** (T1, T3, T5, T7, T9, T11, T13), más preflight, siete implementaciones y un cierre de validación. El orden de fases no agrega dependencias distintas de las expresas.

## Fase 0: Prerrequisitos comprobables

### T0: Resolver preflight sin ampliar producto ni políticas

**Archivo:** `.spectra/specs/recording-notes/implementation-evidence.md` (nuevo), `extension/manifest.json`, `extension/src/content.ts`, `extension/src/recording-db.ts`, `extension/src/upload-queue.ts`, `extension/tests/e2e/global-setup.ts`, `backend/app/auth/audit.py`, `backend/app/retention/worker.py`, `SECURITY.md` (solo lectura salvo el registro de evidencia).

**Acción:** Registrar el candidato real y comandos disponibles; comprobar configuración de pytest/Hypothesis, Vitest/fake-indexeddb/fast-check y E2E. No instalar dependencias ni descargar modelos sin necesidad autorizada. Confirmar la política aprobada aplicable a notas pendientes locales de grabaciones eliminadas/inaccesibles; no inventar retención ni limpiar esos datos por conveniencia. Identificar la superficie flotante existente, su autorización y mensaje de activación. En la base inspeccionada `content.ts` no demuestra un control flotante de notas: si no existe una superficie aprobada, bloquear **solo la integración flotante de T10 y su aceptación**, sin construir el control general. Mantener disponible el resto de tareas independientes. Registrar quién hará la revisión independiente de seguridad dentro de Sauri (un especialista ausente no es un veto ficticio).

**Criterio de Completado:** Evidencia con SHA, comandos y disponibilidad, política citada o decisión concreta pendiente, superficie flotante citada o dependencia explícita, ausencia de permisos nuevos y responsables de validación. Los fallos de infraestructura son bloqueos, no evidencia RED. Antes de persistir notas en producción debe existir resolución de política aplicable; este plan no la concede.

**Dependencias:** Ninguna.

## Fase 1: Persistencia separada y ciclo de vida

### T1: RED de esquema, aislamiento y cascada de notas (P4/P5/P6)

**Archivo:** `backend/tests/recording_notes/test_persistence.py`, `backend/tests/recording_notes/test_lifecycle_property.py` (nuevos).

**Acción:** Con PostgreSQL sintético aislado, verificar por introspección la tabla `recording_notes`, UUID cliente único, FK de grabación con cascada, contenido textual y fecha UTC del servidor; no importar un modelo inexistente como sustituto de una aserción. Probar orden `(created_at,id)`, grabaciones antiguas con colección vacía, upgrade/downgrade/re-upgrade preservando medios/transcripciones ajenos, borrado/expiración de grabación que elimina solo sus notas y expiración de transcripción que conserva notas. P4/P6 usan al menos 100 ejemplos; incluir dos grabaciones y comprobar que crear notas no muta transcript/turns (P5).

**Criterio de Completado:** Desde `backend/`, `pytest tests/recording_notes/test_persistence.py tests/recording_notes/test_lifecycle_property.py` alcanza las aserciones y falla por comportamiento ausente. Registrar base exacta, salida y commit RED; error de colección/DB no satisface el criterio.

**Dependencias:** T0 (infraestructura; política no debe impedir fixtures sintéticos).

### T2: GREEN del modelo y migración aditiva

**Archivo:** `backend/app/infra/models.py`, `backend/alembic/versions/<revision_real>_recording_notes.py` (nombre determinado al implementar), `backend/app/retention/worker.py` solo si la cascada/ruta existente lo exige.

**Acción:** Crear `RecordingNote` con `id`, `recording_id`, `content`, `created_at`, índice `(recording_id,created_at,id)` y FK `ON DELETE CASCADE`. Descubrir el grafo Alembic actual y elegir parent real preservando ramas publicadas; no fijar ahora un identificador ni modificar revisiones ajenas. No crear seeds ni notas desde transcript. Conservar eliminación vigente; expiración de solo transcript no borra notas. Usar fixtures sintéticos y no migrar la base del dueño. Tras GREEN refactorizar solo la pieza nueva y repetir pruebas.

**Criterio de Completado:** T1 pasa en PostgreSQL, round-trip de migración preserva recursos preexistentes, revisión de diff confirma ausencia de nueva política de retención. `ruff check .` y `mypy .` desde `backend/` con resultados/límites reales registrados; deuda previa se separa y no se oculta debilitando controles.

**Dependencias:** T1; política del servidor aplicable confirmada en T0 antes de habilitar persistencia real.

## Fase 2: API de grabación y contrato privado

### T3: RED de rutas, ownership y replay (P3/P4/P5)

**Archivo:** `backend/tests/recording_notes/test_routes.py`, `backend/tests/recording_notes/test_idempotency_property.py`, `backend/tests/recording_notes/test_recording_lookup.py` (nuevos).

**Acción:** Ejercitar rutas ASGI reales POST/GET `/api/v1/recordings/{recording_id}/notes`. POST acepta `{id: UUID, content: texto}` y devuelve nota con `recording_id` y `created_at`: 201 primera vez, 200 replay idéntico, 409 reutilización conflictiva sin mutación, 422 entrada malformada, 401 sin sesión y mismo 404 para grabación ausente/ajena antes de leer notas. No filtrar existencia de una nota de otro dueño por el 409. Probar solicitudes concurrentes con mismo ID en PostgreSQL, datos idénticos, aislamiento entre grabaciones y usuarios, auditoría permitida/denegada sin contenido/tokens y transcript inmutable. GET devuelve lista ordenada, incluida vacía. Probar lookup actual de `recording_id` por meeting con ownership; no añadir ruta si ya cumple. Al menos 100 ejemplos para replay y aislamiento.

**Criterio de Completado:** `cd backend && pytest tests/recording_notes/test_routes.py tests/recording_notes/test_idempotency_property.py tests/recording_notes/test_recording_lookup.py` falla por aserciones de funcionalidad ausente, con fixtures operativos; conservar por separado aserciones que ya pasan y no fingir RED del lookup existente.

**Dependencias:** T0. Las rutas faltantes permiten RED sin depender de T2.

### T4: GREEN de API y lookup sin cambiar el transcript

**Archivo:** `backend/app/recording_notes/{router,service,repository,schemas}.py` (nuevos), `backend/app/main.py`, `backend/app/meetings/router.py` solo si falta el lookup probado.

**Acción:** Incluir router; reutilizar auth/session y comprobar propietario de `SessionRecording.meeting.created_by` antes de acceder al recurso. Aplicar insert-on-conflict con comparación de grabación/owner/contenido sin sobrescribir; el conflicto entre dueños no revela datos ajenos. Devolver campos exactos de T3 y fechas UTC; no introducir ediciones ni límite de formato/longitud de producto. Mantener mutaciones fuera del router y auditoría sin texto sensible. Verificar el commit separado del helper de auditoría existente: no permitir que su commit adelante una escritura parcial o invalide transacciones de la API. Conservar lookup compatible y transcript original. Refactorizar tras GREEN y repetir.

**Criterio de Completado:** T1/T3 pasan con concurrencia real; `cd backend && pytest tests/recording_notes && pytest && ruff check . && mypy .` registrados con resultados y límites por comando, sin skips encubiertos. No desplegar todavía; revisión de seguridad pendiente T15.

**Dependencias:** T2, T3; política aplicable de T0.

## Fase 3: Outbox de notas y entrega durable

### T5: RED de destino inmutable y migración local (P1/P3/P6)

**Archivo:** `extension/src/recording-notes-db.test.ts`, `extension/src/recording-notes-outbox.test.ts` (nuevos), `extension/src/recording-db.test.ts`, `extension/src/upload-queue.test.ts` (existentes o ampliar).

**Acción:** Con fake-indexeddb/fast-check, probar nota UUID estable y target discriminado `pending_capture {sessionId,meetingId}` o `existing_recording {recordingId}` persistidos antes de informar guardado. El destino no cambia por selección nueva, reinicio o fallo de POST. Existing-recording funciona sin captura y sin llamar ingesta. La migración conserva chunks, trabajos y completion records actuales. Fallo/quota/abort del commit no permite éxito ni envío desde estado volátil. Al menos 100 secuencias para invariancia de destino y replay. Integrar las pruebas con módulos reales; si falta el seam, crear únicamente la estructura de prueba mínima, no la implementación anticipada ni un fake que sustituya producción.

**Criterio de Completado:** `cd extension && npm run test -- src/recording-notes-db.test.ts src/recording-notes-outbox.test.ts` presenta aserciones RED esperadas con entorno operativo; guardar base/commit/salida. Imports faltantes son infraestructura pendiente, no RED.

**Dependencias:** T0.

### T6: GREEN del outbox sin duplicar la identidad de captura

**Archivo:** `extension/src/recording-notes-db.ts`, `extension/src/recording-notes-outbox.ts` (nuevos), `extension/src/recording-db.ts`, `extension/src/upload-queue.ts` solo para integración necesaria.

**Acción:** Añadir almacenamiento durable de notas y estados de entrega; migrar sin borrar stores. Reutilizar completion mapping existente para resolver pending-capture; persistir el destino directo para existing-recording en la misma transacción que nota. No reinterpretar selección actual al reintentar ni reutilizar limpieza de chunks. Exponer operación compartida para encolar y confirmar por noteId solo contra respuesta coincidente. Refactorizar después de GREEN.

**Criterio de Completado:** T5 pasa, conservación de datos de versiones anteriores comprobada; `cd extension && npm run test && npm run typecheck && npm run build` registrados. No pruebas con notas del dueño.

**Dependencias:** T5; política de residuales locales confirmada T0 antes de usar datos reales.

### T7: RED de recuperación y acknowledgements (P1/P3/P6)

**Archivo:** `extension/src/background.recording-notes.test.ts`, `extension/src/core/api/recording-notes.test.ts` (nuevos), `extension/src/background.upload-retry.test.ts`, `extension/src/background.recording-completion.test.ts`.

**Acción:** Probar integración con flujo de subida existente: HTTP401/403/404/422/409/5xx, fetch/Blob/JSON exception, respuesta perdida, recording_id malformado/ajeno y fallo de commit de mapping nunca hacen done, limpian chunks ni entregan notas. Verificar éxito duplicado guarda mapping antes de done; start/alarm recupera processing con mismos IDs/keys. Tres intentos agotados conservan datos y requieren retry explícito del mismo destino. Nota POST perdida reintenta mismo noteId; conflicto pausa, 401 espera auth, 403/404 no retarget. Reiniciar entre transiciones con al menos 100 secuencias, incluidas existing-recording sin ingesta. Las protecciones de subida que ya pasan son regresiones, no trabajo para reimplementar: el RED nuevo debe demostrar pérdida/entrega indebida de **notas** o falta de su integración.

**Criterio de Completado:** `cd extension && npm run test -- src/background.recording-notes.test.ts src/core/api/recording-notes.test.ts src/background.upload-retry.test.ts src/background.recording-completion.test.ts` registra regresiones existentes y al menos una aserción RED genuina de notas, sin fallar por infraestructura.

**Dependencias:** T0. T6 no es prerrequisito del RED de integración.

### T8: GREEN de cliente privado y worker de notas

**Archivo:** `extension/src/core/api/client.ts`, `extension/src/background.ts`, `extension/src/recording-notes-outbox.ts`, `extension/src/upload-queue.ts` si hay brechas verificadas.

**Acción:** Implementar POST autenticado con guard/timeout existentes, validar noteId/recordingId/response y drenar solo destinos durables confirmados. Conectar start/alarm/recuperación sin otra cola de subida; existing-recording omite ingesta. Conservar estados de fallo y retry explícito, sin loops indefinidos ni descarte automático. No logs de contenido/tokens. No marcar entregado por mera subida. Reutilizar capacidades completion y corregir solo brechas probadas. Refactorizar con las mismas pruebas.

**Criterio de Completado:** T5/T7 pasan, incluyendo abortos y reinicios; `cd extension && npm run test && npm run typecheck && npm run build` pasan o se registran bloqueos concretos sin declarar listo el candidato. Contrato cotejado contra T4.

**Dependencias:** T4, T6, T7; política aplicable T0.

## Fase 4: Entradas autorizadas y lectura separada

### T9: RED de composición compartida y mensaje flotante (P1/P2)

**Archivo:** `extension/src/panel/components/RecordingNoteInput.test.tsx`, `extension/src/background.recording-note-entry.test.ts` (nuevos), `extension/src/panel/SidePanelApp.test.tsx`, `extension/src/content.preservation.test.ts`.

**Acción:** Probar entrada de panel con contexto activo o grabación existente explícita; no contexto implica no encolar, error de IDB conserva input y no declara guardado; selección posterior no retarget. Para contrato flotante probar sender tab/session vigentes, mensajes stale/forged rechazados sin nota, y activación sin transportar token o contenido por DOM/content script. Solo la UI de extensión compone la nota. No exigir un nuevo control visual general para poder probar el contrato.

**Criterio de Completado:** `cd extension && npm run test -- src/panel/components/RecordingNoteInput.test.tsx src/background.recording-note-entry.test.ts src/panel/SidePanelApp.test.tsx src/content.preservation.test.ts` alcanza aserciones RED de la nueva entrada; las pruebas de rechazo y conservación existentes siguen registradas por separado.

**Dependencias:** T0.

### T10: GREEN de entrada de panel y conexión flotante existente

**Archivo:** `extension/src/panel/components/RecordingNoteInput.tsx` (nuevo), `extension/src/panel/SidePanelApp.tsx`, `extension/src/background.ts`, `extension/src/content.ts`, `extension/src/core/types.ts` para el contrato nuevo.

**Acción:** Una función `addRecordingNote(context,content)` para la UI de extensión; guardar antes de confirmar y distinguir pendiente de entregado. Panel y activación flotante validada usan el mismo input/outbox. No reutilizar NoteDTO de tarjetas ni exponer credenciales/texto a la página. Integrar notas en el control visible solo si T0 identificó implementación y alcance autorizado; si no existe, entregar panel y contrato de mensaje como parcial explícito y mantener pendiente P2 extremo a extremo, sin crear control ni vía oculta. No ampliar manifest. Refactorizar y repetir.

**Criterio de Completado:** T9 pasa, suites/typecheck/build de extensión pasan; entrada autorizada observada mediante navegador APX cuando el entorno soporte extensión, con captura y sin alterar datos personales. Un test aislado no certifica la interacción flotante ausente. El cierre integral de T10 exige esa interacción real; una parcialidad no cierra R1.2.

**Dependencias:** T8, T9; superficie flotante verificada en T0 solo para ese subrecorrido.

### T11: RED de lectura independiente en portal (P4/P5)

**Archivo:** `frontend/src/components/RecordingNotes.test.tsx` (nuevo), `frontend/src/api.test.ts`, `frontend/src/App.test.tsx` (ampliar o crear siguiendo Vitest existente).

**Acción:** Probar mapper RecordingNote snake_case→camelCase y fetch autenticado por recordingId autorizado. Grabaciones A/B no mezclan respuestas tardías; colección vacía, loading/error propios, notas visibles aunque transcript esté pendiente/falle; transcript visible aunque notes falle. Mostrar texto como texto escapado, separado de Transcript, sin inferir Markdown ni formato de producto. Meeting sin recording_id no dispara GET a un destino supuesto. No usar grabaciones del dueño.

**Criterio de Completado:** `cd frontend && npm run test -- src/components/RecordingNotes.test.tsx src/api.test.ts src/App.test.tsx` alcanza aserciones RED funcionales y mantiene las pruebas previas. Guardar base y salida, sin considerar imports/runner ausente como RED.

**Dependencias:** T0. No necesita T4 para contratos sintéticos.

### T12: GREEN del apartado Notes separado del transcript

**Archivo:** `packages/shared-types/src/index.ts`, `frontend/src/api.ts`, `frontend/src/components/RecordingNotes.tsx` (nuevo), `frontend/src/App.tsx`.

**Acción:** Añadir RecordingNote `{id,recordingId,content,createdAt}` y mapper; obtener recording_id desde lookup autorizado probado T4 y consultar notes sin depender del éxito de transcript. Estados separados por grabación, prevención de respuestas tardías y contenido escapado. Reutilizar auth existente, nunca token en URL ni nuevo rediseño. Refactorizar tras GREEN.

**Criterio de Completado:** T11 pasa; `cd frontend && npm run test && npm run typecheck && npm run build` y typecheck de `packages/shared-types` según su script real pasan. Navegador APX: abrir dos grabaciones sintéticas, alternar selección, comprobar Notes/Transcript separados y error independiente, capturar resultado. No declarar disponible en portal del dueño sin despliegue autorizado.

**Dependencias:** T4, T11.

## Fase 5: Integración y entrega

### T13: RED del recorrido combinado y ciclo de vida (P1–P6)

**Archivo:** `extension/tests/e2e/recording-notes.spec.ts` (nuevo), `extension/tests/e2e/fixture.py`, `extension/tests/e2e/global-setup.ts`, `backend/tests/recording_notes/test_integration.py` (nuevo).

**Acción:** Usar dos capturas sintéticas distintas, entrada panel y control visible autorizado, pérdida de acknowledgement/retry con destino estable, consulta portal con notas y transcript separados, existing-recording sin captura, borrado/expiración selectivo y denegación a otro dueño. Utilizar runner/fixture existente; cualquier extensión del fixture debe seguir llamando APIs reales, no sustituir notas por respuestas simuladas para declarar integración. Llevarlo a aserciones RED contra base preimplementación; prerrequisitos ambientales se resuelven primero. Si falta superficie flotante autorizada, registrar el subrecorrido bloqueado, no simular aceptación. Docker aislado con nombres únicos y teardown que elimine contenedores/redes/volúmenes temporales incluso si falla.

**Criterio de Completado:** `cd extension && npm run test:e2e -- recording-notes.spec.ts` y `cd backend && pytest tests/recording_notes/test_integration.py` con evidencia RED de aserción, no de login/servicios/fixture. P1–P6 cubiertas por pruebas previas y recorrido; ausencias ambientales no se cuentan como skips exitosos. Ausencia de recursos QA comprobada al finalizar cada intento.

**Dependencias:** T0. No esperar a que todas las implementaciones estén hechas para fabricar un RED tardío.

### T14: GREEN de wiring combinado sobre candidato integrado

**Archivo:** `extension/tests/e2e/recording-notes.spec.ts`, `backend/tests/recording_notes/test_integration.py`, `extension/src/background.ts`, `frontend/src/App.tsx`, `backend/app/main.py`, `.spectra/specs/recording-notes/implementation-evidence.md`.

**Acción:** Conservar commits RED y combinar predecesores en candidato aislado; corregir únicamente wiring necesario para ejecutar el recorrido real. Ejecutar en orden migración sintética→API→clientes, sin migrar producción. Repetir E2E y lifecycle con PostgreSQL y recursos propios, revisar diff y refactorizar preservando garantías. Ningún fixture sintético certifica audio/transcripción real ni aceptación general de producto.

**Criterio de Completado:** T13 pasa en recorridos habilitados y sin omisiones ocultas; registro de SHAs/commits/comandos/resultados, evidencia de interacción y limpieza Docker verificada. El recorrido flotante bloqueado impide declarar completo R1.2, aunque otros recorridos puedan entregarse como parciales claramente rotulados.

**Dependencias:** T2, T4, T8, T10, T12, T13; cierre integral requiere resolver superficie flotante/política T0.

### T15: Validación final, revisión de seguridad y propuesta de entrega

**Archivo:** `.spectra/specs/recording-notes/implementation-evidence.md`, `.spectra/specs/recording-notes/tasks.md`, `SECURITY.md` solo ante correcciones de documentación necesarias y autorizadas.

**Acción:** Revisar candidato exacto, propietarios, concurrencia, no divulgación, escape, auditoría, residual local y cascada con un revisor independiente del equipo Sauri o worker acotado autorizado; Ansel resuelve hallazgos y repite controles, sin exigir agentes históricos ausentes. Backend `pytest`, `ruff check .`, `mypy .`; extensión `npm run test`, `npm run typecheck`, `npm run build`, `npm run test:e2e`; frontend `npm run test`, `npm run typecheck`, `npm run build`; shared-types typecheck real. Identificar deuda previa por comparación con base, sin eludir CI ni protecciones. Registrar facturación/CI si sigue bloqueando. Ofrecer a Fer PR listo para merge con funcionalidad, límites y evidencia; no integrar sin su decisión. Tras merge comprobar SHA, migración/despliegue autorizados, recorrido APX y aceptación de producto separada.

**Criterio de Completado:** PR con todas las pruebas aplicables, hallazgos corregidos/verificados, ninguna aprobación de política inventada, checklist R1/R2 satisfecho o parcialidades abiertas. Estado explícito: publicado/listo/integrado/aceptado. No cerrar entrega integral con flotante no verificado, CI requerido fallido o datos del dueño alterados. Recursos de QA eliminados y ausentes; worktrees/ramas se preservan salvo limpieza autorizada.

**Dependencias:** T14 y todas las resoluciones de T0 necesarias para entrega; merge y aceptación reservados a Fer.

## Matriz de trazabilidad

| Propiedad del diseño | Requisito | RED antes de implementación | GREEN / validación |
|---|---|---|---|
| P1 destino desde extensión | R1.1 | T5, T7, T9, T13 | T6, T8, T10, T14 |
| P2 entrada flotante validada | R1.2 | T9, T13 | T10, T14; gate de superficie T0 |
| P3 invariancia de replay | R1.1–1.2 | T3, T5, T7, T13 | T4, T6, T8, T14 |
| P4 lectura por grabación | R2.1 | T1, T3, T11, T13 | T2, T4, T12, T14 |
| P5 separación de contenido | R2.2–2.3 | T1, T3, T11, T13 | T2, T4, T12, T14 |
| P6 fallos y ciclo de vida | R1.1–R2.3 | T1, T5, T7, T13 | T2, T6, T8, T14 |

## Dependencias, colaboración y límites de cierre

T1→T2; T3+T2→T4; T5→T6; T7+T6+T4→T8; T9+T8→T10; T11+T4→T12; T13+implementaciones→T14→T15. T0 habilita infraestructura y separa política/superficie por impacto, sin bloquear pruebas sintéticas independientes. T1/T3/T5/T7/T9/T11/T13 pueden avanzar como RED independientes; asignar una pieza a la vez inicialmente y evitar concurrencia sobre background.ts, App.tsx, modelos o fixtures compartidos. La ruta de integración entre ramas preserva el commit RED exacto, base y evidencia; el asignador verifica el diff integrado.

Los comandos son los scripts del repositorio, **no resultados ya ejecutados**. Esta fase solo valida documentación. Los tests de shared-types no se asumen por nombre: comprobar script actual; no aceptar un placeholder como prueba. La capacidad APX de navegador no garantiza que una extensión esté instalada/cargable: un entorno que no permita verificarla deja ese recorrido NO VERIFICADO, no lo convierte en prueba de portal.

No se aprobaron por este plan decisiones abiertas de formato/edición/control oculto, una nueva política de privacidad, seguridad o retención, una superficie flotante inexistente ni implementación anticipada. Solicitar revisión explícita de esta fase antes de asignar implementación; las aprobaciones de requisitos y diseño del PR #187 no se piden de nuevo.
