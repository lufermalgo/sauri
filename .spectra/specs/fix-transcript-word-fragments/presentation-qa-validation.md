# #880/#882 — continuación de #900: procedencia y presentación

Autor: Nahuel. 2026-11-13. Misma tarjeta `task_e54417ff1e164f69` y criterios #897. Encargo vigente de Ansel: código listo para integrar en QA; Ansel instala/califica, sin merge a cargo de Nahuel. Este informe reemplaza el estado de «faltan procedencia/proyección/fallback» de la primera pieza; no declara aceptado el producto.

## Resultado funcional

- El ASR nativo vuelve a emitir **fuentes padre completas**, no filas por palabra. Conserva sus tiempos absolutos. Las palabras válidas viajan en `alignment` solo por HTTP interno y en RAM del worker; no se serializan a DB, object store, cola ni API de producto. Words inválidas o texto no reconstruible preservan el padre.
- En modo granular local opt-in, el worker obtiene la diarización del mismo objeto autorizado mientras aún conserva las palabras. Produce únicamente el resultado final: speakers, assignments compatibles y una proyección por referencia a fuentes/rangos Unicode/intervalos originales. No hace clips ni vuelve a ejecutar ASR sobre fuentes guardadas.
- Una fuente solo se divide si **todas** sus palabras tienen atribución positiva a un único cluster. Ausencia, ambigüedad, simultaneidad, words inválidas o parciales: una pieza padre completa con `speaker_id=null`. No se usa el ganador del segmento como identidad de sus palabras. A/B/A se conserva; un cluster sin texto sigue existiendo.
- Un bundle final preparado queda ligado a la revisión pendiente existente. El job de diarización lo materializa sin repetir inferencia. Proyección, speakers y review se activan en el mismo commit; un fallo después de flush revierte todo y el retry explícito reutiliza la revisión. No hay nuevo coordinador, finalizador, endpoint de escritura ni mensaje con words/audio.
- Si la inferencia auxiliar preparatoria falla con error HTTP/runtime/validación, la fuente ASR completa permanece publicable por el flujo existente; no se preservan words para un retry. El resultado sin proyección mantiene las limitaciones v1, sin fabricar una v2 retrospectiva.
- La vista valida **toda** la proyección antes de usarla. Una referencia/revisión/rango inválido conserva las fuentes completas sin identidades de assignments v1. El texto se extrae por codepoints, no UTF-16, por lo que un emoji no desplaza rangos. Los nombres elegidos solo se leen del review de esa misma revisión.
- Las corridas consecutivas de la misma voz se agrupan también **entre fuentes**; cada intervalo mantiene ID propio y apunta a la fila agrupada. No se crea un envolvente de playback sobre los gaps. Fuentes inciertas no se agrupan inventando identidad.

## Refinamiento técnico del diseño

La propuesta extensa de #898 planteaba tres tablas normalizadas. La implementación acotada utiliza dos columnas JSON nullable en **la fila de revisión existente**: `prepared_result` (solo salida final preparada, sin texto duplicado/words/scores/timeline cruda) y `presentation` (proyección activa). La migración aditiva `014_final_presentation`, hija de `013_manual_recovery_persistence`, no hace backfill ni cambia fuentes.

Es una alternativa menor y atómica: la FK y retención de la revisión ya ligan ambos documentos al transcript; la validación estricta Pydantic y `validate_prepared`/`validate_projection` verifican las referencias cruzadas, partición completa, orden, speakers de la misma revisión e intervalos válidos contra fuentes antes del commit y de exponer la proyección. No hay API de edición de estos documentos. Se evita un subsistema adicional de persistencia/retención. No se afirma que cada referencia JSON tenga una FK SQL independiente. En una futura escritura externa sería necesario mantener esta validación, no confiar en JSON sin controles.

## Contrato mínimo para integración sobre QA #899

1. Incorporar el delta sobre el runtime QA coordinado por Ansel. #900 tiene base `qa/core-delivery-20261113`; **no probé una combinación instalada con #899**. No sustituir archivos enteros de #899: hay cambios concurrentes en `meetings/router.py`, `api.ts`, `TranscriptView.tsx` y la spec. Preservar su indicador, `latest_attempt`, `processing_revision`, `overlap_ms`, labels/review, playback y resumen. No toqué código de resumen, indicador ni controlador de playback.
2. Ejecutar `alembic upgrade head` en la DB QA antes de desplegar API/workers con estas columnas. No correr contra DB viva por este documento. La migración mantiene un único head y defaults NULL para resultados previos. Hacer downgrade borra solo la proyección nueva, no las fuentes; nunca se necesita como parte normal del despliegue.
3. Motor ASR nativo actualizado: `ASR_ACOUSTIC_VALIDATION=1`, checkpoint powerset local **ya instalado**, offline. Worker actualizado: `ASR_GRANULAR_PRESENTATION=1`; mantener `DIARIZATION_EXCLUSIVE_ASSIGNMENTS=1` para la ruta legacy/fallback. Todos los flags siguen apagados por defecto. Sin los nuevos flags, no se inventan palabras/proyecciones históricas.
4. Contrato interno ASR: `segments` contiene padres `{text,start_ms,end_ms}` y `alignment` opcional con `{text,start_ms,end_ms}`. Solo `LocalProvider`/worker procesa esa evidencia efímera. Las capabilities del objeto exacto se renuevan para cada llamada como antes; no se expande a otro audio.
5. La reserva se hace mediante `DiarizationRepository.reserve_next_revision` existente y el handoff de cola incluye la revisión reservada. En el seam #248/#899 conservar claims, verificación de generación, outbox, commits de etapas separados y finalizador único. El cálculo pareado ocurre antes del primer commit de fuentes para no guardar auxiliares; la activación sigue en la etapa diarización. No marcar esa revisión completada desde el cálculo preparatorio.
6. Portal: `GET .../diarization?presentation_version=2` añade `presentation`, `transcript_id`, `processing_revision` y `overlap_ms`. Sin parámetro no expone el documento ni cambia la forma v1. V2 contiene `version=2`, `policy_version=exclusive-source-v1`, IDs/revisión y `pieces[{source_turn_id,char_start,char_end,speaker_id,intervals[{start_ms,end_ms}]}]`. Rangos half-open en **Unicode codepoints**. No contiene texto duplicado, words, raw labels ni scores.
7. Reusar los componentes reales de #899: construir filas e intervalos con `projectTranscript`; labels por `turn.speakerId` de la revisión validada. No resolver speaker por el nuevo ID de pieza ni por un assignment padre. Indicador y resúmenes conservan su propio flujo. Ensayar la combinación completa antes de dársela a Fer.

## RED → GREEN

- Antes del módulo de proyección, la suite nueva falló por módulo ausente; esto verifica la dependencia, no se vende como reproducción conductual del ruido. Los RED acústicos conductuales de la primera entrega siguen documentados en `acoustic-qa-validation.md`.
- Hallazgo independiente de Ansel: dos padres de la misma voz generaban dos filas v2, versus una v1. Agregué prueba conductual: **1 failed, 9 passed**, `expected length 1 but got 2`. Corregí el agrupado sin unir sus intervalos `[0,1000)` y `[2000,3000)` ni el gap. GREEN y rerun completo se registran en PR.
- Regresión independiente de límites no monotónicos: tests preservados en el candidato; fallback entero sin reordenar ni recortar palabras. La prueba positiva mantiene overlap monotónico.

## Validación ejecutada

Intérprete backend: `/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python` (`PY` debajo).

```bash
# backend/
$PY -m pytest tests/asr_engine tests/transcription tests/diarization tests/meetings \
  --ignore=tests/meetings/test_playback_storage_integration.py -q
$PY -m pytest tests/diarization/test_prepared_presentation_worker.py \
  tests/diarization/test_presentation.py tests/asr_engine/test_native_acoustic_alignment.py -q
$PY -m mypy app/diarization/presentation.py app/diarization/repository.py \
  app/diarization/worker.py app/transcription/asr_engine.py app/transcription/worker.py \
  app/transcription/local_provider.py app/infra/models.py app/meetings/router.py \
  tests/diarization/test_prepared_presentation_worker.py tests/diarization/test_presentation.py
$PY -m mypy .
# raíz
npm run test --workspace frontend
npm run typecheck
npm run build --workspace frontend
```

- Regresión backend amplia final: **335 passed, 1 skipped**; suite focal final: **23 passed**. Suite adicional `tests/diar_engine`: **23 passed**. Código ensayado y publicado: `38a6fe6f6ddb02a43d908a4415b126a3329d2396`; la actualización posterior solo registra esta evidencia documental. No cambié assertions previas para ocultar fallos: la prueba ASR ahora exige el padre completo **y** todas las words/tiempos exactos del envelope.
- Frontend completo tras corregir el hallazgo adicional: **134 passed, 12 archivos**. La regresión focal de agrupado quedó GREEN y la suite completa pasó de nuevo. JSDOM advierte que `HTMLMediaElement.pause` no está implementado; sus assertions pasan, no equivale a reproducción real.
- `npm run typecheck` global PASS en extensión/frontend/shared-types; build frontend PASS.
- Mypy de los 10 archivos nuevos/modificados listados: PASS. `mypy .`: **82 errores en 8 archivos**, misma deuda previamente contrastada con base #882; no es PASS global. Ruff de todos los Python cambiados PASS; `git diff --check` PASS.
- PostgreSQL **16 real, contenedor exclusivo temporal**: cadena Alembic completa hasta 014 PASS; downgrade 014→013 y upgrade 013→014 PASS. `SAURI_QA_POSTGRES_URL=<DB exclusiva> $PY -m pytest tests/integration/test_final_presentation.py -q`: **2 passed**, incluyendo commits separados, rollback tras flush, retry/redelivery sin inferencia duplicada, fuentes inmutables, aislamiento de review y acceso/expiración de proyección. Contenedor eliminado, no solo detenido; no volúmenes persistentes ni servicios ajenos tocados.
- Corrida adicional de concurrencia histórica: **8 passed, 3 failed** incluyendo los 2 nuevos; los tres fallan al faltar `OBJECT_STORE_ENDPOINT`, antes de inferencia. La suite amplia original tuvo análogamente **331 passed, 1 skipped, 1 failed** por la prueba S3/CORS sin entorno. No son fallos de atribución, pero **no declaro esas integraciones aprobadas**. No descargué una imagen S3 nueva ni usé el store vivo para simular un green. Ansel debe ensayarlas en QA configurado.

## Navegador APX

Componente real `TranscriptView` + `MeetingPlaybackView` servido por Vite temporal aislado, API y audio **sintéticos**, no datos del dueño ni validación acústica. Navegador APX `t28`, origen local temporal 9414. Verifiqué tres filas: voz A con su nombre revisado, voz B con su nombre revisado y padre incierto entero `Speaker N`. Click en la segunda fila movió seek a **2000 ms** y el passage activo a voz B. Las capturas APX muestran el resultado. Un rango deliberadamente inválido conservó las dos fuentes completas sin identidades, comprobando fallback completo. No hubo error visible de componente; los primeros fallos del harness (ruta temporal/token sintético) se corrigieron antes del recorrido. El servidor temporal se termina al cierre.

## Límites de entrega

Candidato de **código para integración QA**, no producto integrado/aceptado. Ansel conserva instalación combinada #899, revisión de contratos #248, playback real, escucha/calificación acústica y comunicación al dueño. La evidencia read-only del original humano obtenida por Nahuel en la reactivación de la tarjeta está en `acoustic-original-window-validation.md`; no se amplía a identidad/precisión total ni se confunde con la prueba sintética de UI. La continuación de proyección no cambió admisión/VAD ni sus parámetros; hash final comprobado de `native_main.py`: `f6e1656186f60421c959dd1788323e7aee4170b730d16f85e5e9cd5bd11777f4`, idéntico al módulo ensayado en esa comprobación. No extiende esa evidencia a las nuevas piezas de presentación. CI remoto sigue sujeto al bloqueo de billing ya documentado, no sustituido por fixtures.
