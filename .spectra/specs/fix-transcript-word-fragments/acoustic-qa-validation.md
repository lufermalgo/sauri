# Evidencia incremental QA #880 — 2026-11-13

Encargo actualizado de Ansel por autorización correctiva de Fer, misma tarjeta `task_e54417ff1e164f69`. Base #882 `7e8d296`; criterios #897 y diseño #898 incorporados como documentos, sin merge de PRs. No reemplazo de servicios vivos, nuevas grabaciones del dueño, consultas privadas, reprocesamiento persistido ni cambios de datos.

## Continuación posterior

La pieza de procedencia/proyección/fallback quedó implementada para integración QA; ver `presentation-qa-validation.md` y tareas A6.1–A6.5. Ansel aportó además evidencia read-only del original en `acoustic-original-window-validation.md`. Los límites y conteos de la primera pieza que siguen se conservan como históricos, no como estado vigente de los faltantes. Instalación combinada/calificación y aceptación continúan separadas del PR de código.

## Estado real de la primera pieza (histórico)

**Avance parcial, no listo para prueba integral del dueño ni aceptación.** Flags QA apagados por defecto. Faltan calificación con voz humana autorizada, conservación completa de procedencia padre/proyección/fallback, recorrido de presentación/playback y candidato integrado instalable validado. La emisión por palabra puede seguir fragmentando los casos sin atribución: no se presenta como solución total.

## RED y regresiones

Desde `backend/`, intérprete `<root>/backend/.venv/bin/python`:

- `-m pytest tests/asr_engine/test_native_acoustic_alignment.py -q` antes de implementar: **3 failed, 7 passed**, diferencias conductuales de palabra/segmento y admisión de ruido, no fallos de importación.
- La primera política basada también en score decoder falló en integración de motores; regresión añadida antes del ajuste: **2 failed, 10 passed** con score bajo, incluyendo ruido fuera del prefijo inicial.
- `-m pytest tests/asr_engine tests/diar_engine tests/diarization tests/transcription -q` tras corregir: **220 passed, 1 skipped**, cinco warnings previos de SQLite. No se excluyeron fallos para aprobar.
- Ruff sobre motor, asignador, worker y dos módulos nuevos: corregida longitud de línea en el test; resultado final registrado en PR.
- `mypy app/diarization/assignment.py app/diarization/worker.py`: **Success: no issues found in 2 source files**.
- `mypy .` definido por proyecto: **82 errores en 8 archivos**, tanto en candidato como base exacta #882; mismos diagnósticos al comparar sin orden/summary, no errores nuevos en los cambios. No equivale a typecheck global PASS ni a PR listo para integrar. No cambié exclusiones/configuración.
- Sin TypeScript modificado en este delta. Las validaciones frontend previas de #882 no certifican el nuevo comportamiento QA.

## Motores reales, señales sintéticas — NO voz humana validada

Ejecuté un proceso separado con el Python nativo instalado, `HF_HUB_OFFLINE=1` y `TRANSFORMERS_OFFLINE=1`; checkpoint powerset local existente, MPS y MLX existentes. Audio de control: ruido generado determinísticamente y voz sintética TTS local ya instalada. No descargas/modelos nuevos ni audio del dueño; directorio temporal eliminado al terminar. La prueba no sustituye una validación de grabación real humana.

| Control | Resultado final real de motores |
|---|---|
| Ruido de 6 s | VAD: 0 regiones; decoder: 1 segmento; admisión: 0 unidades. |
| Voz breve desde inicio | VAD: 1 región; admisión: 2 unidades, primera a 0 ms. |
| Voz tras ruido | VAD: 1 región; admisión: 9 unidades; offsets del original conservados. |
| Misma voz con amplitud reducida a 0,08 tras ruido | VAD: 1 región; admisión: 9 unidades. 0,08 es dato del fixture, no umbral de producto. |

La regla anterior `no_speech_prob > 0.6` no rechazaba el ruido: score del decoder aproximadamente `1e-10`, similar al score de habla. Lo comprobé dos veces. Eliminé esa dependencia, **sin ajustar otro umbral**: la decisión usa el VAD neuronal powerset existente con los parámetros fijos de biblioteca y sin duración mínima/relleno de gaps. La exactitud del VAD sobre habla humana débil sigue no demostrada; por eso no activo el flag por defecto ni certifico corregido el video.

## Cómo ensayar el candidato sin tocar vivo

Solo en un despliegue/proceso QA aislado con el código de este candidato: motor ASR con `ASR_ACOUSTIC_VALIDATION=1`; worker de diarización con `DIARIZATION_EXCLUSIVE_ASSIGNMENTS=1`. Se requiere el checkpoint powerset **ya instalado** en cache local o ruta `ASR_VAD_MODEL_PATH`; si falta, falla explícitamente en vez de descargar o devolver éxito vacío. Ambos flags permanecen desactivados por defecto.

Ansel debe coordinar el runtime exacto y la prueba antes de sustituir servicios. Este documento no inicia procesos web, despliega ni autoriza activar el candidato en el entorno del dueño. No se ha completado la condición de candidato instalable/aceptado.
