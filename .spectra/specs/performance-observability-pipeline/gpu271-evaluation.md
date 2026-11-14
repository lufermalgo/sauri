# #907 — Evaluación GPU aislada y recorrido integral

## Contrato y estado

Continuación de Ansel del13/11/2026: autoriza evaluar Torch/torchaudio2.7.1 en entorno nativo desechable, verificar procedencia/compatibilidad/seguridad, probar retención GPU de forma acotada y después original completo→atribución→resumen y repetición integral. Sin CPU, modelos nuevos, gastos/servicios externos, cambio de parámetros acústicos, reemplazo del runtime dueño ni merge por Nahuel. No corresponde volver a pedir la misma autorización técnica. Requisitos R1–R7/R9 y T14 de performance-observability-pipeline; task_e2a1fd161b4d4910, issue#907, PR#917. Ansel verifica e integra.

Este documento sucede al límite histórico de `real-pipeline-memory.md` sin borrar fallos previos. La corrida ASR fallida no es baseline comparable. Primera corrida integral con dependencia corregida EN CURSO; no se afirma total, velocidad o precisión todavía.

## Procedencia, compatibilidad y aislamiento

Wheels obtenidos exclusivamente de metadata HTTPS PyPI y files.pythonhosted.org, verificados contra SHA256 publicado y nombre/versión interna:

| Paquete | Wheel / SHA256 |
|---|---|
|torch2.7.1|`torch-2.7.1-cp311-none-macosx_11_0_arm64.whl`; `aea4fc1bf433d12843eb2c6b2204861f43d8364597697074c8d38ae2507f8730`|
|torchaudio2.7.1|Wheel CPython3.11/macOSarm64 verificado; hash completo en `gpu271/wheel-manifest.json` adjunto a la tarea.|
|sympy1.14.0|Wheel oficial puro Python verificado; satisface `sympy>=1.13.3` de Torch2.7.1.|

Venv propio bajo scratch/gpu271. Reutiliza paquetes no reemplazados del Python nativo por .pth de solo lectura; su site-packages local precede el heredado. Pip no desinstaló ni escribió paquetes fuera del entorno aislado. `pip --isolated check`:sin requisitos rotos. Imports efectivos de torch/audio apuntan al scratch, versiones2.7.1, MPS disponible. El dueño conserva torch/audio2.5.1/sympy1.13.1. Python3.11.12/macOS27.2arm64; pyannote.audio3.3.2 y MLX0.32.4/mlx-whisper0.4.3 existentes se reutilizan, sin descargar modelos.

## Carga segura real

Los checkpoints existentes se copiaron al scratch; red deshabilitada en proceso nativo, HF offline y sin lectura de credenciales del dueño. Hashes:

- segmentación3.0: `da85c29829d4002daedd676e012936488234d9255e65e86dfab9bec6b1729298`.
- wespeaker-resnet34: `366edf44f4c80889a3eb7a9d7bdf02c4aede3127f7dd15e274dcdb826b143c56`.

La primera carga2.7.1 falló con `UnpicklingError`: el default `weights_only=True` rechaza cuatro clases de schema/versionado usadas por esos checkpoints. Se inspeccionaron los globals estáticos y el código de los tipos: dataclass Specifications, enums Problem/Resolution y str-subclass TorchVersion. Se mantiene weights_only=True, sin `weights_only=False`, variables de bypass ni importación arbitraria desde el pickle; allowlist contextual solo de esos4tipos y cerrada tras cargar, también ante error. No se cambia a serialización irrestricta ni se habilita un endpoint nuevo para checkpoints.

Carga real con ese contexto:0,585s; Pipeline3.1 en MPS, driver59211776B/tensores32480512B. Parámetros efectivos sin cambios: segmentation.min_duration_off0, clustering centroid/min_cluster_size12/threshold0,7045654963945799; no num/min/max_speakers. El PR añade compatibilidad acotada del loader y pruebas de ámbito/fallo; no actualiza instalaciones globales ni obliga al dueño a adoptar esta dependencia.

## Prueba técnica acotada, no precisión acústica

LSTM sintético MPS: input[4,589,60], hidden128,2layers,bidirectional,eval/inference_mode. Pesos/input idénticos generados por NumPy, sin audio. Versión2.5.1:1iteración para salida de referencia, no una nueva pasada de audio fallida;2.7.1:25iteraciones tras comprobar presión1. Synchronize/empty_cache tras cada iteración, RSS/driver/tensores y presión medidos.

-2.7.1 driver108118016→108101632B entre iteración1y25; live2924800B constante; RSS222448→222624KiB; presión1.
-Outputs y/h/c frente a2.5.1:delta máximo0 en los tres, igualdad exacta observada. No prueba equivalencia universal ni precisión del pipeline.
-Se conserva el diagnóstico previo2.5.1 de25iteraciones/crecimiento~768MiB como evidencia histórica, no como benchmark total.

Esto verifica el operador del wheel real; ya no se deduce la corrección solo del autorelease en source. No elimina la necesidad del original completo y la guardia de recursos.

## Recorrido real en ejecución

Primera corrida nueva: job`job_010e7fd31cb740ae`, run`perf907-653482a2`, orquestador38331/ASR38461. Mismo original400361891B/SHA256`9b53197391d1bbbb38962da948ddec8189f411bfffb6086100fc5f45a09c7857`;5654,853s contenedor/5654,82s decodificados. Fuente QA bd638ee, contratos productivos reales. Python backend existente orquesta HTTP autenticado/S3/PG/Rabbit firmado/workers; child nativo aislado2.7.1 ejecuta MLX/MPS. Preparación PCM16/16kmono exclusivamente RAM/pipes, sin voz derivada persistente.

Se mantienen word_timestamps=true, condition_on_previous_text=false, hallucination_silence_threshold2, idiomaes, VAD/granular/exclusivo=false; MPSbatches4/4 con clustering global inalterado; qwen2.5:14b/plantilla fija para resumen. El child ASR termina antes de MPS, y MPS antes de Ollama. Recursos/esperas registrados. No se finge reserva global distribuida T9 ni instalación del stack QA.

Los resultados nuevos se preservan como artefactos privados0600 separados de telemetría (texto/anotaciones/summary), para comparación real; NO se suben a Git, prompts ni fixtures. El checkpoint histórico de1506turnos/hash permanece inmutable. La base efímera anterior ya había sido eliminada al cerrar aquel intento: no hay raw transcript recuperable de esos1506turnos y no se inventa su recuperación. Esta ejecución integral recomputa el original y evita volver a perder esos outputs.

Límites: API/worker de validación están alojados en Python host, infra central temporal en Docker; no es aceptación del despliegue productivo. Sin referencia humana temporal no hay WER/DER ni identidades validadas; tres personas esperadas no sustituyen esa referencia. Dos recorridos del candidato no se presentarán como una aceleración frente a una basal que nunca terminó.

## Matriz de reparación y controles

Se conserva íntegra la matriz por reparación de `main-delivery.md` (QA bd638ee/#899/#902→main#912), incluidos assignment, telemetría, outbox/worker/registro real, firma/confirmación de broker, ORM, rutas y dependencias. Este PR no descarta ni declara integrados los cambios QA excluidos allí.

| Delta actual | Estado / prueba |
|---|---|
|Allocator MLX|Ya publicado en0adb38b/PR917, no desplegado. Pruebas ASR/transcripción y ejecución real anterior preservadas.|
|Compatibilidad segura loader MPS|Nuevo en PR917; tests RED2fallos→GREEN, contexto de4tipos y fallo cerrado. Dependencia2.7.1 solo evaluada en entorno desechable.|
|Preparación en memoria/separación de intérpretes|Adaptador de validación explícito, no sustitución silenciosa del endpoint productivo que crea WAV; fuente/hashes preservados en scratch y tarea.|
|QA acústico/UI/granularidad|Permanece según matriz previa, fuera del delta main de este PR. Se usa configuración congelada para comparar, no se incorpora ni despliega el resto de QA.|

Comando focal desde backend: `python -m pytest -p no:cacheprovider tests/asr_engine tests/diar_engine tests/transcription tests/diarization -q` →225PASS/1SKIP (integración PostgreSQL sin URL),39,96s. Ruff de4Python cambiados PASS; mypy estricto de2tests nuevos PASS; no mocks usados como inferencia real. Compilación/controles sobre SHA final y evidencia integral se registran al finalizar. Sin TS/Rust/UX tocados. Actions desactivado con aprobación; no bloqueo de facturación ni CI ficticio.

## Pendiente de cierre

Terminar primera corrida, registrar total/etapas/recursos/resultados, identificar dominante y repetir integral con condiciones explícitas; comparar salida/atribución/summary/calidad sin fabricar WER/DER. Revisar SHA actual, pruebas/seguridad locales equivalentes pertinentes, actualizar PR y entregar a Ansel sin merge. Eliminar recursos Docker/venv/wheels/copias temporales exclusivamente propios tras preservar evidencia y outputs autorizados; no borrar entorno/cachés/servicios/datos/worktrees del dueño.
