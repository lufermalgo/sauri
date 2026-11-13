# Seguimiento mínimo real del portal (#892)

## Alcance y estado de entrega

Autorización: pedido explícito de Fer del 13/11/2026, transmitido por Ansel en `task_5d2838ff10c446ed`. Spec: `.spectra/specs/portal-visual-design`, solo R7–11. Implementación en rama `feature/portal-processing-indicator-20261113`, base `41ab5f4`. No autoriza rediseño completo. PR borrador: https://github.com/lufermalgo/sauri/pull/894, código `8bb2c17`. Integración reservada a Fer: no merge.

Se preservó la enmienda documental original desde el worktree `docs-portal-processing-stages-20261113`, sin editar ese worktree. Diseño y tareas de esta porción están incorporados, manteniendo requisitos 1–6 y fases previas. La aceptación de producto y la validación del procesamiento real NO están completadas por los tests.

### Qué hace el código

- `GET /api/v1/meetings/{meeting_id}/processing`, autenticado y owner-scoped, publica una proyección de los datos existentes. No crea, reintenta ni cancela jobs; no agrega migraciones.
- Claim durable de transcripción: pendiente antes del claim; en curso después del inicio confirmado y mientras el claim no esté vencido. No es un heartbeat ni prueba de utilización instantánea de GPU.
- Transcripción persistida y `Meeting.completed` completan solo ASR. Diarización usa la revisión más reciente del transcript actual y distingue pending/in_progress/completed/failed/not_reconstructible.
- «Listo para revisar» requiere ambas etapas completas, turnos con intervalos válidos, transcript no vencido y diarización no legacy; un claim de recovery no completa un resultado anterior. No significa precisión validada, identidad cierta ni revisión humana terminada.
- El portal consulta secuencialmente cada 2000 ms, aborta al desmontar/cambiar de reunión, conserva el último snapshot ante fallo y permite reintentar solo lectura. No se solapan consultas. El resultado de una subida anterior no se asocia a un archivo nuevo.
- La pantalla de prueba espera ready y luego consulta transcript/diarización. Al reabrir una reunión se consulta el estado sin subir de nuevo; se preserva el acceso existente al contenido parcial, rotulado como tal, y se refresca la vista al cambiar la ejecución lista. No se modifica playback ni el algoritmo de atribución.
- Se conserva fetch para multipart. No ofrece bytes transmitidos: subida y procesamiento usan indicadores indeterminados, sin porcentajes/ETA inventados. La nueva comunicación de estados está en español, en el recurso `frontend/messages/processing.es.json`; identificadores de código en inglés. El hook inicial señaló literales españoles como identificadores: se separó el recurso localizado de código, sin desactivar, cambiar ni saltar hooks.

### Qué no se mide

Se inspeccionaron los workers y los servicios `backend/asr-engine/native_main.py`, `backend/asr-engine/main.py`, `backend/diar-engine/native_main.py`: MLX/Whisper y pyannote devuelven una respuesta final, no un contrato de progreso. Descarga/decodificación (incluido ffmpeg en pyannote) no exponen eventos al core. Por eso «Preparación del audio» dice «Detalle no disponible», y «Preparación del resultado» solo se completa cuando los artefactos persistidos permiten confirmarlo. No se simulan pasos independientes, ni se infiere diarización a partir de `transcribing`.

No se cambian motores, modelos, GPU nativa Mac, Docker central, credenciales, datos, consentimiento, retención, política ni costo. No se copian grabaciones privadas al repo.

## Validación ejecutada

Python usado: venv existente del backend, Python 3.13. Comandos desde `backend/` (sustituí `PY`/`BIN` por ese entorno):

```sh
$PY -m pytest tests/meetings/test_processing.py tests/meetings/test_get_meeting_property.py tests/transcription tests/diarization tests/integration/test_pipeline_e2e.py -q
$BIN/ruff check app/meetings/processing.py app/meetings/router.py tests/meetings/test_processing.py
$BIN/mypy app/meetings/processing.py app/meetings/router.py tests/meetings/test_processing.py
```

Resultados: **192 passed, 3 skipped**; ruff y mypy de archivos modificados pasan. Incluye transiciones ASR→diarización→ready/fallo, ejecución vigente, recuperación, legacy/expiración, intervalos inválidos, autorización de endpoint (401/403/404/owner) y lectura sin crear trabajos. Los tests de integración de pipeline usan motores controlados: NO son evidencia de MLX/pyannote real.

Desde `frontend/`: `npm run test` → **106 passed / 12 archivos**; `npm run typecheck` y `npm run build` pasan. JSDOM informa tres advertencias preexistentes `HTMLMediaElement.prototype.pause` en tests de playback, que pasan; no se ocultaron ni se modificaron esos tests.

También se ejecutó el comando amplio `pytest --continue-on-collection-errors -m 'not integration' -q`: **546 passed, 2 failed, 10 errors, 5 skipped, 2 deselected**. Los fallos no pertenecen a esta entrega:

- Falta `OBJECT_STORE_ENDPOINT` para prueba de almacenamiento real.
- Falta ruta de speaker-review esperada por un RED existente.
- Falta `app.transcription.processing_pipeline` durante colección.
- Nueve errores piden `SAURI_QA_POSTGRES_URL` aislado (algunos tests no tienen marker integration).

Comparación con exportación completa de base `41ab5f4`, mismos comandos/entorno: **528 passed, los mismos 2 failed y 10 errors**, mismos skips/deselecciones. `ruff check .`: mismos 3 hallazgos de base; `mypy .`: mismos 82 errores en 8 archivos sin modificar. No se debilitó ningún control ni se cambió CI para esconderlos.

CI publicado: https://github.com/lufermalgo/sauri/actions/runs/43472620108. Ambos jobs terminaron sin ejecutar pasos. Anotación literal: “The job was not started because recent account payments have failed or your spending limit needs to be increased. Please check the 'Billing & plans' section in your settings”. No hay logs de ejecución (`log not found`); no se cambió billing, se reintentó ni se eludió ese bloqueo.

`git diff --check` pasa. No hay cambios Rust/extensión/modelos/migraciones.

## Límite material del contrato core existente

En la base y en el runtime de referencia `baea619`, `GET /diarization` usa `scalar_one_or_none()` sin elegir revisión: si hay más de una revisión puede fallar. El endpoint nuevo de seguimiento sí elige la última revisión del transcript y no completa una revisión vieja. El arreglo de la lectura del resultado por generación pertenece a #653 (API core); esta entrega no lo duplica ni cambia atribución. En la pantalla de prueba, si esa lectura falla, no se declara listo: se comunica fallo de actualización y se reintenta lectura. Validar la combinación con la entrega core actual antes de integración; no interpretar tests con mocks como prueba de que #653 ya está integrado.

## Navegador APX y pendiente de aceptación

Se abrió `http://127.0.0.1:15273/` con APX: el runtime de referencia respondió y mostró la pantalla de acceso (tab `t25`). No hay sesión autenticada en ese tab, no se ingresaron credenciales ni se eludió el login. No se cargaron videos ni se sustituyó el runtime. Esa captura NO valida el indicador nuevo.

Pendiente, coordinado por Ansel: conectar candidato preservando el código de Nahuel y el resto del candidato actual, acceder con la sesión autorizada y contrastar etapas del navegador con persistencia/logs core durante una carga/proceso real autorizado, sin duplicar cargas privadas. Registrar captura del indicador y límites; recién entonces declarar validada la funcionalidad visible y cambiar el PR de borrador a listo. Fer conserva el merge.

## Conexión exacta del candidato (solo Ansel, tras coordinar la ventana)

Se verificó `git apply --check` del parche de código contra el worktree de referencia `baea619`, sin aplicar cambios: pasó. Los comandos de aplicación/build/despliegue siguientes son instrucciones; **no fueron ejecutados contra el runtime**. No uses `down`, `clean`, `up` global, migraciones, ni reinicies worker/motores. No imprimas `qa.env`, tokens o configuración expandida.

1. Usá un worktree de integración NUEVO basado en el candidato runtime que Ansel decida conservar (incluyendo correcciones core/Nahuel). No edites el worktree de referencia. A continuación se muestra cómo partir del HEAD de referencia observado; si cambió o tiene modificaciones sin preservar, detenete y reconcilialas primero.

```sh
ROOT=/Users/lufermalgo/Proyectos/sauri
SOURCE="$ROOT/.worktrees/feature-portal-processing-indicator-20261113"
RUNTIME="$ROOT/.worktrees/qa-local-platform-browser-continuity-20261113"
# Definí SCRATCH como tu carpeta temporal APX, nunca el checkout raíz.
: "${SCRATCH:?Definí tu carpeta temporal APX}"
INTEGRATION="$SCRATCH/portal-processing-892-integration"
git -C "$RUNTIME" status --short
git -C "$ROOT" worktree add -b qa/portal-processing-892 "$INTEGRATION" "$(git -C "$RUNTIME" rev-parse HEAD)"
git -C "$SOURCE" diff 41ab5f4..HEAD -- backend/app/meetings/router.py backend/app/meetings/processing.py frontend/src frontend/messages > "$SCRATCH/portal-processing-892.patch"
git -C "$INTEGRATION" apply --check "$SCRATCH/portal-processing-892.patch"
git -C "$INTEGRATION" apply "$SCRATCH/portal-processing-892.patch"
# Ante conflicto, NO fuerces ni reemplaces archivos enteros: conservar contratos/cambios actuales.
# Incorporá en este candidato de prueba las entregas core/Nahuel que Ansel haya verificado.
```

2. Repetí typecheck, tests y build sobre esa combinación. Construí SOLO imágenes API/portal del candidato combinado (no despliega):

```sh
docker build -t sauri-qa-892-api -f "$INTEGRATION/backend/Dockerfile" "$INTEGRATION/backend"
docker build -t sauri-qa-892-portal -f "$INTEGRATION/frontend/Dockerfile" "$INTEGRATION"
```

3. Proyecto observado: `sauri-local-qa-04d47768cad6`, portal 15273, API 18100. Reconfirmá labels con `docker inspect` antes de tocarlo. Usá los **mismos** dos archivos Compose y `qa.env` locales que ya usa la validación (los paths de labels `com.docker.compose.project.config_files` y su directorio); no otro proyecto ni otra base. Guardá en tu scratch los IDs de imagen actuales de API y portal para rollback. Escribí `candidate.override.yml` en scratch con:

```yaml
services:
  api:
    image: sauri-qa-892-api
  portal:
    image: sauri-qa-892-portal
```

Con `BASE_COMPOSE`, `RUNTIME_OVERRIDE` y `QA_ENV` definidos a los paths **existentes verificados**:

```sh
: "${BASE_COMPOSE:?}" "${RUNTIME_OVERRIDE:?}" "${QA_ENV:?}"
docker compose --project-directory "$RUNTIME" --env-file "$QA_ENV" \
  -p sauri-local-qa-04d47768cad6 -f "$BASE_COMPOSE" -f "$RUNTIME_OVERRIDE" \
  -f "$SCRATCH/candidate.override.yml" up -d --no-deps --no-build api portal
```

Esto recrea únicamente API/portal con su configuración vigente; mantiene worker, motores nativos, redes, volúmenes, cuenta y datos. Requiere coordinación, no está autorizado como acción automática por este documento. No ejecutar en `sauri-fer-test`. Rollback: misma operación restringida usando las imágenes previas guardadas; sin borrar recursos.

4. Verificá `/portal-health` y `/api-health`, luego APX con la sesión existente. Probá consulta/reapertura sin nuevo upload; para transiciones activas coordiná UNA carga autorizada o la próxima del dueño. Comprobá fallo de consulta por separado de job fallido sin alterar la cuenta ni datos. No publiques contenido privado. No cambies merge/aceptación a completados hasta contar con esa evidencia.
