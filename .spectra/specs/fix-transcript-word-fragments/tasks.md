# Plan de Implementación — Renderizado de turnos completos en la transcripción

## Delta ejecutable #880 — 2026-11-13

Continúa la misma unidad y tarjeta `task_e54417ff1e164f69`, criterios #897, diseño #898 y actualización técnica de `design.md`. Ansel transmitió autorización de implementación posterior; Fer conserva merge y Ansel coordina cualquier sustitución de servicios vivos. El plan histórico de abajo no se reabre ni equivale a finalización del delta.

| Fase | Tareas | Dependencias |
|---|---|---|
| RED | A1 | Criterios AC-R1–AC-R8 aprobados |
| Implementación QA aislada | A2–A3 | A1 |
| Regresiones y calificación | A4–A5 | A2/A3 |
| Presentación e integración | A6 | A4/A5 y contrato final revisado |

### A1 — RED acústica y palabras [x]
**Archivo:** `backend/tests/asr_engine/test_native_acoustic_alignment.py`.
**Acción:** probar N0–N2 y D0/D1 con texto, límites y evidencia suministrada; luego agregar score no-habla bajo observado con ruido real de motores.
**Criterio de Completado:** RED ejecutado con 3 fallos conductuales/7 passes; contraejemplo adicional con 2 fallos/10 passes antes de corregir su regla. No error de importación como sustituto.
**Dependencias:** ninguna adicional. Propiedades P-R1–P-R4.

### A2 — VAD existente y límites originales [x]
**Archivo:** `backend/asr-engine/native_main.py`.
**Acción:** opt-in QA de VAD powerset con checkpoint local ya instalado, sin descargas; audio completo decodificado en memoria; scores no son detector de voz. Extraer palabras solo si reconstruyen exactamente texto y tiempos, fallback de fuente completa en caso contrario. Limpiar temporales existentes; no logs de evidencia.
**Criterio de Completado:** tests A1 GREEN; modo por defecto conserva contrato, permisos y limpieza. No implica calificación humana.
**Dependencias:** A1. Propiedades P-R1/P-R2/P-R3/P-R8/P-R10.

### A3 — Atribución exclusiva opt-in [x]
**Archivos:** `backend/app/diarization/assignment.py`, `backend/app/diarization/worker.py`, `backend/tests/diarization/test_exclusive_assignment.py`.
**Acción:** `require_exclusive` conserva Speaker N con varios candidatos; mide unión de intervalos duplicados. Worker solo lo usa con `DIARIZATION_EXCLUSIVE_ASSIGNMENTS=1`; modo legacy conserva contrato. D0 distingue A/B y D3 mantiene cluster sin texto.
**Criterio de Completado:** tests de atribución exclusiva y propiedades legacy pasan juntos; no se borra speaker ni se reinterpreta resultado guardado.
**Dependencias:** A1/A2. Propiedades P-R4/P-R5/P-R6/P-R7.

### A4 — Regresiones/contratos [~]
**Archivos:** `backend/tests/asr_engine/`, `backend/tests/diar_engine/`, `backend/tests/diarization/`, `backend/tests/transcription/`; evidencia en `acoustic-qa-validation.md`.
**Acción:** ejecutar suites sin excluir fallos, Ruff de cambios y mypy definido por proyecto; comparar deuda previa con base #882. Probar cleanup y errores/capabilities ya existentes.
**Criterio de Completado:** registrar comandos/resultados reales; ningún fallo nuevo oculto. Mypy global tiene deuda previa y no se declara PASS.
**Dependencias:** A2/A3. P-R5/P-R7–P-R11.

### A5 — Calificación acústica [~]
**Archivo:** `.spectra/specs/fix-transcript-word-fragments/acoustic-qa-validation.md`.
**Acción:** ejecutar motores reales offline en proceso aislado con ruido, saludo al inicio, voz tras ruido y voz débil sintéticos; después contrastar habla humana autorizada y casos de overlap sin retener clips/evidencia privada.
**Criterio de Completado:** controles sintéticos y validación humana informados por separado; ningún resultado de TTS se presenta como aceptación de video real. Variante permanece opt-in hasta pasar la calificación.
**Dependencias:** A2/A3/A4. P-R1/P-R2/P-R11.

### A6 — Completar presentación/fallback [x código QA; integración/calificación pendientes]

La orden posterior de Ansel separa la entrega de código de su instalación/calificación real. No se limita a documentos ni espera otro permiso técnico. La entrega de Nahuel es PR actualizado para integración QA, sin merge; A5 y A6.5 siguen a cargo de Ansel.

#### A6.1 — Fuente padre y evidencia efímera [x]
**Archivos:** `backend/asr-engine/native_main.py`, `backend/app/transcription/asr_engine.py`, `backend/app/transcription/local_provider.py`, `backend/tests/asr_engine/test_native_acoustic_alignment.py`.
**Acción:** devolver fuentes completas y alignment interno opcional; validar reconstrucción/orden/límites sin persistir words. Conservar fallback completo, permisos y cleanup.
**Criterio de Completado:** prueba exige un padre más todas las words exactas; no monotonicidad conserva fuente y overlap monotónico sigue válido.
**Dependencias:** A2/A3. P-R2/P-R3/P-R5/P-R8/P-R10.

#### A6.2 — Proyección final y activación atómica [x]
**Archivos:** `backend/app/diarization/presentation.py`, `backend/app/transcription/worker.py`, `backend/app/diarization/worker.py`, `backend/app/diarization/repository.py`, `backend/app/infra/models.py`, `backend/alembic/versions/014_final_transcript_presentation.py`.
**Acción:** preparar salida final referida a padres/revisión en memoria y entregar bundle final mediante revisión existente. Usar columnas JSON de la misma revisión con validación estricta, sin texto duplicado/words/scores. Fallback entero ante incertidumbre; conservar clusters. Materializar proyección/speakers/review juntos sin nueva inferencia, coordinador ni finalizador.
**Criterio de Completado:** `backend/tests/diarization/test_prepared_presentation_worker.py` y `backend/tests/integration/test_final_presentation.py` pasan en SQLite/PostgreSQL real, incluyendo rollback tras flush, retry/redelivery, autorización y expiración; migración upgrade/downgrade/upgrade PASS.
**Dependencias:** A6.1. P-R3/P-R4/P-R6/P-R7/P-R8/P-R10.

#### A6.3 — API opt-in y presentación conservadora [x]
**Archivos:** `backend/app/meetings/router.py`, `frontend/src/api.ts`, `frontend/src/transcript-turns.ts`, `frontend/src/components/TranscriptView.tsx`, `frontend/src/transcript-projection.test.ts`.
**Acción:** exponer solo resultado final con `presentation_version=2`; validar IDs/revisión/partición completa/codepoints e intervalos. Rechazo completo sin assignments v1 si proyección inválida. Agrupar corridas de voz entre fuentes sin unir gaps ni A/B/A, conservar nombres de review de misma revisión y seek por intervalo.
**Criterio de Completado:** RED conductual dos padres/misma voz produce 2 filas; GREEN produce 1 fila y 2 intervalos separados. Suite frontend/typecheck global/build PASS y recorrido APX sintético con labels/seek observados.
**Dependencias:** A6.2. P-R3/P-R4/P-R5/P-R7/P-R9.

#### A6.4 — Regresiones y publicación [x al publicar candidato]
**Archivos:** `backend/tests/diarization/test_presentation.py`, `backend/tests/diarization/test_prepared_presentation_worker.py`, `backend/tests/integration/test_final_presentation.py`, `frontend/src/transcript-projection.test.ts`, `presentation-qa-validation.md` en esta spec.
**Acción:** ejecutar suites backend/frontend, mypy/Ruff del proyecto y diffcheck; documentar fallos ambientales/deuda previa sin ocultarlos. Revisar límites de privacidad y publicar commit en #900, no merge.
**Criterio de Completado:** evidencia y SHA remoto coherentes; typecheck TS PASS; ningún error nuevo de mypy en módulos cambiados; límites S3/CI/calificación explícitos.
**Dependencias:** A4/A6.3. P-R8/P-R10/P-R11.

#### A6.5 — Instalación combinada y calificación del original [ ] Ansel
**Archivos/seam:** `presentation-qa-validation.md`, `acoustic-original-window-validation.md`, runtime QA #899/#248.
**Acción:** integrar contratos sin sobrescribir indicador/playback/nombres/resumen; aplicar migración solo QA y ensayar original autorizado, acceso S3/CORS/estados, incertidumbre y etiquetas en portal.
**Criterio de Completado:** candidato combinado instalado y probado por Ansel; aceptación de Fer separada. No afirmar listo el producto por fixtures o menor conteo de filas.
**Dependencias:** A5/A6.4. P-R1–P-R11.

## Trazabilidad y alcance

Derivado exclusivamente de `bugfix.md` APPROVED (`9fed8e2b14a10bb25960011326e3ebf9e7af5b27`, blob `ddf34bb41dc5d9d9aa38c15c312e9cf24a4e7b05`) y `design.md` APPROVED (`bc18206308380a321873c8baabb353073dd4a628`, blob `3b5230ae64e87139492fcad228d2290fa0554048`). Autoridad del comportamiento de producto: `PRODUCT_BASELINE.md` APPROVED (`4953b3b4b8a058fd4738342307cc50bfd66814f1`, blob `c6f9ef9bf3fac9eac23763e25e25e1089a16c446`), §4.C.4; la versión previa `f31c1437d002a49849fc577446290ab83d29a584` citada por el bugfix tiene el mismo requisito de turnos, sin delta de alcance. La evidencia QA sintética se conserva por separado en `qa-reproduction.md`, snapshot `d458eac3a38e2fc0089bb8698f418646aaa287a8` (rama `origin/fix/transcript-word-fragments`); no se incorpora ni altera el bugfix aprobado.

Solo datos sintéticos en todas las pruebas. No almacenar ni alterar `Transcript`/`SpeechTurn` fuente; no copiar etiquetas entre revisiones de la misma grabación; no extender retención ni buscar audio alternativo. Cuando audio histórico esté confirmado como ausente/expirado y el transcript siga retenido, preservar fragmentos y exponer `not_reconstructible`. Sin cambio a `packages/shared-types` ni a `docker-compose.yml`; sin tarea de ajuste de motor/Compose.

## Resumen de Fases

| Fase | Descripción | Tareas | Dependencias |
|---|---|---|---|
| 1 | Agrupador y asignación | T1–T4 | T1 → T2; T3 → T4 |
| 2 | Esquema, revisiones, atomicidad y backfill | T5–T12 | T5 → T6; T6 → T7/T8 integrado → T9 → T10; T10 → T11 → T12 |
| 3 | API, portal y playback | T13–T18 | T10/T12 → T13 → T14; T15/T2/T14 → T16; T17/T2/T16 → T18 |
| 4 | Validación integrada y gate independiente | T19–T20 | T4, T6, T7/T8 integrado, T10, T12, T14, T16, T18 → T19 → T20 |

Las fases agrupan por lectura; el DAG indicado en cada tarea es el único orden obligatorio. Las pruebas RED anteceden a su implementación GREEN. T1, T3, T5, T13, T15 y T17 son pruebas independientes sin dependencias de entrada y pueden iniciarse en worktrees separados. El RED de T7/T8 ya está registrado; su GREEN requiere T6. T9 requiere T6 y T7/T8 integrado; T11 requiere T6, T7/T8 integrado y T10. El RED previamente registrado se conserva como primer commit/evidencia del mismo issue/PR #646/#720. El issue #647 se marca como supersedido por #646 solo después de que el GREEN integrado pase y se entregue; hasta entonces permanece abierto con vínculo de trazabilidad y sin duplicar rama, PR o ejecución. T9 requiere PostgreSQL real, no SQLite; es un prerrequisito de ejecución expresado por el diseño, no una dependencia artificial. La codificación por fases no obliga a serializar tareas sin una arista de dependencia.

## Fase 1: Agrupador y asignación

### T1: RED — propiedades del agrupador y de intervalos derivados

**Archivo / seam:** `frontend/src/transcript-turns.test.ts`; función de diseño `groupTranscriptTurns(segments, speakerIdByTurnId)` y conversión a `PlaybackInterval[]`.

**Acción:** Añadir pruebas sintéticas para corridas máximas contiguas por `speaker_id` (Propiedad 1), `A,B,A` e IDs distintos con igual etiqueta (Propiedad 2), ausencia/overlap no positivo como separador; comprobar orden estable, unión de texto no vacío, fuentes preservadas, intervalos uno-a-uno con IDs y límites originales, gaps, overlaps, ausencia de intervalo en timing inválido y no mutación (Propiedad 7 y AC1, AC3, AC5–AC6). Ejecutar antes de implementar y conservar salida RED.

**Criterio de Completado:** `cd frontend && npm run test -- src/transcript-turns.test.ts` falla por las expectativas nuevas (no por setup o import inexistente). Guardar el resultado como evidencia de la tarea.

**Dependencias:** Ninguna

### T2: GREEN — agrupador puro y mapping de intervalos fuente

**Archivo / seam:** `frontend/src/transcript-turns.ts`; `groupTranscriptTurns` y derivación de `PlaybackInterval[]` según diseño §5.

**Acción:** Implementar la función pura para ordenar establemente por `sequence`, agrupar solo fuentes adyacentes con speaker ID válido y asignación positiva ya filtrada, conservar referencias/texto/timestamp de la primera fuente y mantener un playback interval por cada fuente temporizada sin ampliar límites.

**Criterio de Completado:** `cd frontend && npm run test -- src/transcript-turns.test.ts` pasa todos los casos RED de T1; el refactor (si se realiza) conserva ese resultado.

**Dependencias:** T1 — obligatorio RED antes de código.

### T3: RED — asignación de speaker exige overlap positivo

**Archivo / seam:** `backend/tests/diarization/test_assignment_property.py`; función de diseño `assign_turns`.

**Acción:** Añadir prueba property-based con datos sintéticos que exige asignación únicamente si solapamiento máximo es estrictamente positivo, retorna el overlap y desempata máximos positivos por menor `sequence`; máximo cero deja la fila sin speaker. Ejecutar y guardar fallo esperado antes del fix.

**Criterio de Completado:** Desde `backend/`, `<root>/backend/.venv/bin/python -m pytest tests/diarization/test_assignment_property.py` falla en la conducta aún no implementada, sin fallar por entorno.

**Dependencias:** Ninguna

### T4: GREEN — persistir overlap medido por asignación

**Archivo / seam:** `backend/app/diarization/assignment.py`, `backend/app/diarization/worker.py`; función `assign_turns` y persistencia `SpeakerAssignment`.

**Acción:** Retornar y persistir el máximo overlap positivo para las filas asignadas; no asignar speaker si el máximo es cero y preservar el desempate definido. No introducir etiqueta como criterio de agrupación.

**Criterio de Completado:** Desde `backend/`, `<root>/backend/.venv/bin/python -m pytest tests/diarization/test_assignment_property.py tests/diarization/test_worker.py` pasa.

**Dependencias:** T3 — obligatorio RED antes de código.

### T5: RED — fixtures de migración conservan generaciones fuente

**Archivo / seam:** `backend/tests/diarization/test_migration.py`; migración Alembic posterior a `011`, modelos `Diarization`, `SpeakerAssignment`, `SpeakerReview`.

**Acción:** Crear casos sintéticos con generación histórica y review previa; verificar IDs/assignments/review preservados, `processing_revision=1`, `is_legacy=true`, `overlap_ms=NULL`, unicidad por `(diarization_id, turn_id)` y coexistencia de una misma fila fuente en distintas generaciones. Ejecutar antes de migración/modelo nuevo y capturar RED.

**Criterio de Completado:** Desde `backend/`, `<root>/backend/.venv/bin/python -m pytest tests/diarization/test_migration.py` falla específicamente por los campos/constraints aún ausentes, con el runner operativo.

**Dependencias:** Ninguna

### T6: GREEN — esquema y migración de generaciones

**Archivo / seam:** `backend/app/infra/models.py`, `backend/alembic/versions/` migración siguiente a `011`; modelo `Diarization` y asignación.

**Acción:** Añadir `processing_revision`, `is_legacy`, `overlap_ms`; migrar filas existentes sin modificar sus IDs o relaciones, reemplazar unicidad conforme al diseño, permitir `provider=NULL` para intentos no iniciados y mantener provider/defaults descritos. La migración no contacta motores, audio ni jobs.

**Criterio de Completado:** Desde `backend/`, `<root>/backend/.venv/bin/python -m pytest tests/diarization/test_migration.py` pasa; las aserciones sintéticas demuestran preservación del legado y constraints por generación.

**Dependencias:** T5 — obligatorio RED antes de código.

### T7/T8 integrado — RED→GREEN: máquina de estados y terminal no reconstruible

**Mapeo y disposición de issues:** Esta unidad usa el issue #646, branch `feature/issue-646-transcript-turns-t7` y PR #720 para RED y GREEN: un solo task/issue/branch/PR, sin ejecución duplicada en #647. **Tracking:** Issue #646 · Card task_ddf6ac39a1b44285. El issue #647 permanece abierto, vinculado a esta unidad y pendiente de la disposición final tras GREEN; no se crea una tarjeta ni PR de implementación duplicados para el T8 absorbido. Preservar sin cambios el commit RED `19a229c1e2cb45b038ff890be34771eef267f3dc` y su salida enfocada (2 fallos de aserción esperados, 9 pases; sin `TypeError`) como primer commit/evidencia; el PR no se fusiona mientras la suite siga RED. Todo el comportamiento de T8 queda incorporado abajo sin reducción. #647 queda abierto y vinculado a #646/#720 hasta que el GREEN integrado satisfaga ambos criterios; recién entonces Ansel registra que #647 fue supersedido por #646, enlaza la evidencia de entrega y dispone su cierre. No crear issue, card, rama ni PR duplicados.

**Archivo / seam:** `backend/tests/diarization/test_state_property.py`; funciones de transición de `backend/app/diarization/state.py`.

**Acción:** Mantener como fase RED del issue #646 el conjunto de propiedades sintéticas ya ejecutado, sin alterar sus casos ni su evidencia; cubren transición terminal `pending -> not_reconstructible` solo con `audio_unavailable`, rechazo de causa/evidencia no autoritativa, terminalidad y no-op de reentrega; incluir que `failed -> pending` solo se permite ante retry explícito con causa reintentable, y se rechaza para causa terminal, permisos o causa no verificada. Representar la evidencia recibida, causa y retry explícito en un evento estructurado e inmutable y probar la decisión de la función pura de transición en `state.py`; esta prueba no autentica la evidencia ni consulta o selecciona generaciones persistidas. Conservar el criterio global de que pending/failed no desplazan la generación activa, con cobertura repartida por seam: T9/T10 prueban reserva, commit y conservación de la generación activa; T11/T12 prueban la inspección del objeto exacto y el backfill que aportan evidencia; T13/T14 prueban que API/review exponen la última generación completada pese a un intento posterior. Conservar la salida RED ya ejecutada como evidencia del issue #646.

**Criterio de Completado (RED):** La salida RED ya registrada permanece preservada y ligada a #646/#720: desde `backend/`, `<root>/backend/.venv/bin/python -m pytest tests/diarization/test_state_property.py` fallaba con aserciones esperadas, no por setup. Esta evidencia no autoriza merge ni GREEN antes de T6.

**Dependencias:** Ninguna

#### GREEN — estado versionado `not_reconstructible` (misma unidad T7/T8)

**Archivo / seam:** `backend/app/diarization/state.py`, enum/check de estado en `backend/app/infra/models.py`; transiciones `pending`, `failed`, `completed`.

**Acción:** Incorporar `not_reconstructible` terminal con causa `audio_unavailable`; permitir `failed -> pending` únicamente cuando una solicitud de retry explícita confirme causa reintentable, manteniendo la misma revisión. Rechazar retry para estado terminal, permisos, causa desconocida o solicitud ausente. Los errores de storage/engine no crean `not_reconstructible` sin evidencia terminal.

**Criterio de Completado:** Desde `backend/`, `<root>/backend/.venv/bin/python -m pytest tests/diarization/test_state_property.py` pasa.

**Dependencias:** T6 antes de ejecutar GREEN (modelo y constraints necesarios); RED ya evidenciado como primera fase del mismo issue/PR #646/#720.

### T9: RED — reserva idempotente y atomicidad concurrente

**Archivo / seam:** `backend/tests/integration/test_diarization_reservation_concurrency.py`; `DiarizationRepository.reserve_next_revision` y claim worker descritos en diseño.

**Acción:** Crear pruebas sintéticas integradas contra PostgreSQL real para dos reservas concurrentes, redelivery de publicación, caída tras commit antes de publicar, doble claim, rollback de generación y conservación de generación activa ante fallo. Ejecutar antes de la implementación del repositorio/worker y registrar el fallo observado.

**Criterio de Completado:** Desde `backend/`, `<root>/backend/.venv/bin/python -m pytest tests/integration/test_diarization_reservation_concurrency.py` (PostgreSQL disponible) falla en el comportamiento nuevo, sin usar SQLite.

**Dependencias:** T6 y T7/T8 integrado — requiere esquema revisado y estados definidos.

## Fase 2: Esquema, revisiones, atomicidad y backfill

### T10: GREEN — reservar y publicar una sola revisión atómicamente

**Archivo / seam:** `backend/app/diarization/repository.py`, `backend/app/diarization/worker.py`; `reserve_next_revision`, claim de `pending -> in_progress`, persistencia transaccional de diarization/assignments/review.

**Acción:** Serializar reserva con `Meeting SELECT ... FOR UPDATE`, aplicar constraint de revisión, publicar tras commit, permitir re-publicar la misma pendiente y hacer claim condicional idempotente; escribir speakers, assignments y review solo como generación completa en una transacción. Fallas o intentos incompletos no reemplazan la generación activa.

**Criterio de Completado:** La prueba RED de T9 pasa con PostgreSQL; ejecutar `<root>/backend/.venv/bin/python -m pytest tests/diarization/test_repository.py tests/diarization/test_worker.py` desde `backend/` para confirmar rutas de repository/worker.

**Dependencias:** T9 — obligatorio RED antes de código.

### T11: RED — backfill verifica elegibilidad y objeto exacto

**Archivo / seam:** `backend/tests/diarization/test_reprocess_legacy.py`, `backend/tests/infra/test_object_store_availability.py`; `reprocess_legacy` y `ObjectStore.inspect`.

**Acción:** Probar selección solo de legado con transcript/recording vigente, disponibilidad del `audio_ref` exacto, ausencia de referencia sin inferencia, expiración/audio missing terminal, errores transitorios/permiso no terminales, reuso de pending y no-op de completed/terminal. Los fixtures y logs de prueba usan exclusivamente datos sintéticos. Ejecutar y registrar RED antes de añadir el backfill/adaptador.

**Criterio de Completado:** Desde `backend/`, `<root>/backend/.venv/bin/python -m pytest tests/diarization/test_reprocess_legacy.py tests/infra/test_object_store_availability.py` falla en seams aún ausentes/nuevos, sin error de entorno.

**Dependencias:** T6, T7/T8 integrado y T10 — requiere modelo, estado y reserva idempotente.

### T12: GREEN — inspección de objeto y backfill seguro

**Archivo / seam:** `backend/app/infra/object_store.py`, `object_store_s3.py`, nuevo `backend/app/diarization/reprocess_legacy.py`; `ObjectStore.inspect` y comando de backfill.

**Acción:** Implementar `inspect` que clasifica solo ausencia inequívoca como `missing` y propaga errores no concluyentes; añadir backfill re-ejecutable filtrado por legado/retención/recording, revisión reservada, publicación tras commit con solo meeting/revision, worker que revalida audio/retención y emite capability para el objeto exacto. No consultar fuentes alternas ni cambiar retención; expiración/ausencia confirmada produce intento terminal sin hijos.

**Criterio de Completado:** Desde `backend/`, `<root>/backend/.venv/bin/python -m pytest tests/diarization/test_reprocess_legacy.py tests/infra/test_object_store_availability.py tests/diarization/test_worker.py` pasa.

**Dependencias:** T11 — obligatorio RED antes de código.

### T13: RED — API y review siguen la generación activa con autorización

**Archivo / seam:** `backend/tests/meetings/test_diarization_endpoint.py`, `backend/tests/speaker_review/`; GET diarization, GET/PUT speaker-review y `SpeakerReviewService.record_disposition`.

**Acción:** Añadir pruebas sintéticas de última generación completada versus último intento, `not_reconstructible`, overlap/revision, auth intacta; review activa por revisión, lectura histórica por `revision_id`, etiqueta elegida/actual desde todos los items, elementos pendientes separados, mapa completo tras `named`/`corrected`, y replay idempotente. Ejecutar y conservar RED antes del cambio API/review.

**Criterio de Completado:** Desde `backend/`, `<root>/backend/.venv/bin/python -m pytest tests/meetings/test_diarization_endpoint.py tests/speaker_review` falla en las nuevas expectativas, no por setup.

**Dependencias:** T10 y T12 (generaciones y estados/API terminal disponibles).

### T14: GREEN — API de diarización y revisión por generación

**Archivo / seam:** `backend/app/meetings/router.py`, `speaker_review_service.py` y esquemas ya correspondientes; rutas `GET /api/v1/meetings/{meeting_id}/diarization`, `GET .../speaker-review`, `PUT .../speaker-review/revisions/{revision_id}/speakers/{speaker_id}`.

**Acción:** Exponer generación activa completada, último intento, `processing_revision`, `overlap_ms`; resolver review activa o histórica autorizada; preservar mapa de etiquetas completo, items pendientes y respuesta completa del receipt idempotente. Mantener `_get_authorized_meeting` y no filtrar audio, texto extra ni `raw_label`.

**Criterio de Completado:** Desde `backend/`, `<root>/backend/.venv/bin/python -m pytest tests/meetings/test_diarization_endpoint.py tests/speaker_review` pasa.

**Dependencias:** T13 — obligatorio RED antes de código.

## Fase 3: API, portal y playback

### T15: RED — adapter wire y vista no mezclan revisiones

**Archivo / seam:** `frontend/src/api.test.ts`, `frontend/src/components/TranscriptView.test.tsx`; adapter de `frontend/src/api.ts` y componente `TranscriptView`.

**Acción:** Añadir fixtures sintéticas para campos snake_case→camelCase de diarización/review y `labels_by_speaker_id`; verificar que solo se usan assignments positivos y labels de la misma revisión, `review.items` no es fuente de etiquetas, ausencia/error/legacy/unknown deja `Speaker N`, `not_reconstructible` muestra estado conservando fragmentos, el transcript sigue visible durante pending/fallo, y filas agrupadas preservan fuentes. Ejecutar y registrar RED.

**Criterio de Completado:** Desde `frontend/`, `npm run test -- src/api.test.ts src/components/TranscriptView.test.tsx` falla por expectativas nuevas, no por setup.

**Dependencias:** Ninguna — el test RED se puede escribir a partir del seam y contrato aprobados antes del código.

### T16: GREEN — adapter y TranscriptView usan atribución validada

**Ejecución 2026-11-13:** Issue #655 · APX `task_17d5224c897743f6`. GREEN frontend preparado con RED T15 preservado (`f8f4f40` → cherry-pick `a350eb4`). Comando normativo 49 PASS, regresión frontend 113 PASS, typecheck de todos los workspaces y build PASS; recorrido APX con HTTP sintético documentado en `qa-t16-green.md`. Pendiente integración de T14/PR #850 y sus gates; no constituye integración ni aceptación de producto. Fer conserva merge.

**Archivo / seam:** `frontend/src/api.ts`, `frontend/src/components/TranscriptView.tsx`; adapter GET/PUT y renderizado de `TranscriptView`.

**Acción:** Adaptar estructura wire al modelo camelCase aprobado y consumir transcript fuente, diarización y review de la misma revisión. Agrupar solo asignaciones positivas de la generación activa; usar label de `labelsBySpeakerId`, fallback aprobado a speaker label/`Speaker N`, e indicar `not_reconstructible` sin ocultar ni reescribir fuente.

**Criterio de Completado:** Desde `frontend/`, `npm run test -- src/api.test.ts src/components/TranscriptView.test.tsx` pasa.

**Dependencias:** T15 (RED) y T2/T14 (agrupador y contrato API implementados, necesarios para integrar la vista).

### T17: RED — playback conserva subintervalos, gaps y seeks

**Archivo / seam:** `frontend/src/components/__tests__/MeetingPlaybackView.test.tsx`, `PlaybackController.test.ts`; `MeetingPlaybackView` y `PlaybackController.findPassageAt`.

**Acción:** Añadir caso sintético de una fila visual formada por dos fuentes `[0,100]` y `[200,300]`, dos intervalos exactos, ningún passage en 150, highlight solo dentro de intervalo, y Play desde el primer `startMs`; cubrir overlap, timing inválido y texto ausente sin asociación inventada. Capturar RED antes de cambiar playback/view.

**Criterio de Completado:** Desde `frontend/`, `npm run test -- src/components/__tests__/MeetingPlaybackView.test.tsx src/components/__tests__/PlaybackController.test.ts` falla por comportamiento faltante, no por setup.

**Dependencias:** Ninguna — el test RED se deriva del contrato de playback aprobado; se implementa luego de T16.

### T18: GREEN — conectar filas agrupadas con intervalos de playback fuente

**Ejecución 2026-11-13:** Issue #657 · APX `task_94d76af0e39f436a`. GREEN preparado sobre T16 PR #859 (`00e505a`), RED T17 preservado (`81c1467` → `3a6f2f6`). Comando normativo 33 PASS; regresión frontend 120 PASS; typecheck de todos los workspaces y build PASS. Evidencia de corrección de fixture de metadata, integración y navegador APX: `qa-t18-green.md`. Pendiente integración de T16/T14 y gates T19/T20; Fer conserva merge.

**Archivo / seam:** `frontend/src/components/MeetingPlaybackView.tsx`, `frontend/src/components/__tests__/MeetingPlaybackView.test.tsx`, `frontend/src/components/__tests__/PlaybackController.test.ts`.

**Acción:** Renderizar filas de presentación agrupadas por separado de intervalos fuente; mapear passage activo por `presentationTurnId`, resaltar solo durante intervalos originales, dejar gaps sin passage y arrancar desde el primer intervalo sin sintetizar un `end_ms` compuesto.

**Criterio de Completado:** Desde `frontend/`, `npm run test -- src/components/__tests__/MeetingPlaybackView.test.tsx src/components/__tests__/PlaybackController.test.ts` pasa.

**Dependencias:** T17 (RED), T2 y T16 (agrupador e integración de filas necesarios para playback agrupado).

## Fase 4: Validación integrada y gate

### T19: Validar las suites afectadas y la concurrencia real

**Continuidad 2026-11-13 / #658:** Sobre PR #902 `178f893`, la suite PostgreSQL aislada reprodujo 3FAIL/6PASS por fixture de disponibilidad de objeto ausente; corrección exclusivamente de pruebas conserva todas las aserciones y añade verificación del objeto exacto. GREEN 9PASS; Ruff PASS; deuda mypy idéntica a base (28), no PASS. Evidencia, alcance y limpieza: `t19-postgres-evidence-20261113.md`. Gate T19 completo sigue pendiente de #248 y validaciones acumuladas; no merge ni aceptación implicados.

**Archivo / seam:** suites listadas en diseño §Ubicación y pruebas; validación final de backend, API, portal, agrupador y playback.

**Acción:** Ejecutar desde `frontend/`: `npm run test -- src/transcript-turns.test.ts src/components/TranscriptView.test.tsx src/components/__tests__/MeetingPlaybackView.test.tsx src/components/__tests__/PlaybackController.test.ts src/api.test.ts` y `npm run typecheck`. Desde `backend/`, ejecutar `<root>/backend/.venv/bin/python -m pytest tests/diarization/test_assignment_property.py tests/diarization/test_state_property.py tests/diarization/test_worker.py tests/diarization/test_repository.py tests/diarization/test_reprocess_legacy.py tests/diarization/test_migration.py tests/infra/test_object_store_availability.py tests/meetings/test_diarization_endpoint.py tests/speaker_review`; también `<root>/backend/.venv/bin/python -m pytest tests/integration/test_diarization_reservation_concurrency.py` contra PostgreSQL real, nunca SQLite.

**Criterio de Completado:** Todos los comandos terminan con exit 0 en el entorno indicado; conservar logs/salida y SHA probado. No reportar ejecución como aprobada si falta DB/runner.

**Dependencias:** T4, T6, T7/T8 integrado, T10, T12, T14, T16 y T18; son los componentes incluidos en estas suites.

### T20: Revisión de seguridad y privacidad independiente

**Archivo / seam:** Cambios implementados en `backend/app/diarization/`, `backend/app/infra/object_store.py`, `backend/app/infra/object_store_s3.py`, `backend/app/meetings/` y migración; autorización de endpoints, capability de audio y aislamiento de identidad/revisión.

**Acción:** Solicitar gate independiente de Zev sobre el SHA integrado, enfocando autorización y no exposición de objeto/audio/texto, capability limitada al `audio_ref` exacto, retención, no transferencia de identidad entre generaciones y datos sintéticos. No cambiar política de seguridad/privacidad ni ampliar alcance.

**Criterio de Completado:** Evidencia de Zev sobre el SHA exacto con resultado `NO_ACTIONABLE_FINDINGS`; si reporta hallazgos, resolverlos mediante issues autorizados y repetir el gate antes de PR de implementación. Las suites de T19 permanecen verdes.

**Dependencias:** T19 — gate posterior a implementación y validación; no impone secuencia entre componentes independientes durante desarrollo.

### Corrección de escucha T13/T14 — decisión posterior 2026-11-13 (#652, #653, #893)

**Encargo:** Sin clips por hablante, escuchar el medio original para identificar/renombrar. #893 tiene una ruta de clip no equivalente, no integrar como solución de este defecto. Mantener revisión por generación y propietario. Tarea frontend en el worktree/PR #850; no duplicar cambios de runtime #894 ni la implementación de procesamiento #248.

**Prueba y entrega:** `frontend/src/speaker-review-interval.test.ts` cubre tramo continuo más largo, cap 20 s, tramo breve <5 s, gap >250 ms, atribución desconocida, cambio y overlap. Tests `TranscriptView` prueban click sobre el reproductor original y ausencia de GET `/excerpt`; `PlaybackController` detiene a fin y seek ordinario sigue intacto. Ejecutar Vitest y `npm run typecheck`, verificar diff y navegador APX con grabación autorizada antes de declarar escucha real; no reprocesar ni subir grabaciones para QA. Publicar PR actualizado sin merge; Ansel revisa e integra. El gate exacto T14 sigue sujeto al GREEN independiente de #248; no presentarlo como cumplido por la UI.
