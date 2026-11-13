# Limpieza de archivos nativos ante fallo o cancelación

## Alcance y trazabilidad

Unidad técnica de la spec existente `fix-transcript-word-fragments`, issue #880, APX `task_94d76af0e39f436a`. Deriva del contrato de limpieza y no retención de auxiliares, diseño P-R8 y apartados de error/cancelación y pruebas de sinks. No cambia reconocimiento, modelos, umbrales, contrato HTTP ni política de retención. No es T20 ni cierre de T19, no habilita #248 ni reconocimiento futuro #246/#253. Base exacta PR902 `178f893551405774bc5d9006d0eb90cd4c33f586`. Fer conserva integración.

## Defecto reproducido antes del cambio

Una descarga sintética que escribe bytes y lanza `asyncio.CancelledError` deja un archivo temporal en ambos motores. `_download_audio` limpiaba únicamente en `except Exception`, que no incluye esa cancelación. La cancelación propagaba pero los bytes quedaban en disco. En diarización la conversión también quedaba fuera del `finally` que elimina el audio original; una cancelación durante ffmpeg podía dejar ambos archivos.

Probe offline ejecutado por Ansel antes de editar: `reproduce_cancel_cleanup.py` en scratch del hilo `th_1bad6286ee274fbf`. Resultado observado: ASR **1 archivo remanente**, DIAR **1 archivo remanente**; limpieza final del directorio sintético por `TemporaryDirectory`. No se invocó lifespan, modelo, ffmpeg real, almacenamiento real ni red.

## Corrección

- Descarga de ambos motores: guard de éxito y `finally` eliminan el archivo si la descarga no concluye; las excepciones ordinarias mantienen su traducción y las cancelaciones siguen propagando.
- Conversión DIAR: mismo guard, sin convertir cancelación en error HTTP.
- Endpoint DIAR: `finally` exterior cubre conversión e inferencia, y elimina WAV solo si se obtuvo su ruta. Errores HTTP ordinarios conservan categorías y status.
- No se captura/silencia `BaseException`, no se alteran timeouts ni se reintenta inferencia. No se promete limpiar después de SIGKILL o caída del host.

## Validación de Ansel

Intérprete `/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python`, desde el `backend/` del worktree de esta unidad:

- Probe repetido tras el cambio: **0 archivos remanentes en ambos motores**, cancelación propagada.
- `PYTHONDONTWRITEBYTECODE=1 <python> -m pytest -p no:cacheprovider tests/asr_engine tests/diar_engine -q`: **54 passed** antes de agregar la matriz de regresión de Nahuel.
- `<python> -m ruff check asr-engine/native_main.py diar-engine/native_main.py`: **PASS**.
- Regresión ampliada: `<python> -m pytest -p no:cacheprovider tests/asr_engine tests/diar_engine tests/diarization/test_assignment_property.py tests/diarization/test_exclusive_assignment.py tests/diarization/test_presentation.py tests/summaries/test_engine_timeout.py -q`: **89 passed in 2.36s**. Sin DB ni motores reales.
- `git diff --check`: **PASS**.
- Hallazgo y alcance registrados en issue #880: https://github.com/lufermalgo/sauri/issues/880#issuecomment-6866827492 .
- Mypy conjunto no es comando válido para estos dos archivos homónimos (`Duplicate module named native_main`). Ejecutado separadamente en candidato y base exacta: ASR **8 errores preexistentes** y DIAR **3 preexistentes**, mismos códigos/mensajes; **0 nuevos**. Incluye imports de motores ausentes del venv de pruebas y anotaciones históricas. No se agregaron ignores ni se modificó el entorno para ocultarlos. No se declara typecheck global verde ni PR listo.

## Límites y pendientes

Nahuel agregó matriz sintética HTTP en dos archivos separados (20 casos); Ansel revisó ambos archivos y ejecutó la matriz completa: **20 passed in 0.23s**, Ruff y Mypy de ambos tests **PASS**. Revisión: los errores se inyectan en los límites reales del handler, comprueban identidad de la cancelación propagada, ausencia de archivos antes del teardown y ausencia de centinelas en respuesta/log; los controles de éxito conservan contrato. Regresión final ampliada con ambos archivos presentes: **100 passed in 2.36s**, `git diff --check` PASS. No se declara Mypy global verde. Publicación pendiente. Estas pruebas no simulan ni acreditan una desconexión de cliente real durante código nativo síncrono, liberación GPU ni exactitud acústica. No se inició inferencia, DB, Docker ni se tocó runtime o grabaciones del dueño. Las cancelaciones inyectadas prueban la propiedad de limpieza y propagación en los límites síncronos.

Integración/instalación **no realizadas**. CI externa ya bloqueada por facturación/límite GitHub en las entregas anteriores; no se ejecutan reintentos ni se eluden controles.
