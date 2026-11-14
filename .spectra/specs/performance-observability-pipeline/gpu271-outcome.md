# #907 / PR917 — Resultado GPU y bloqueo de la pareja integral

## Estado de cierre

**No listo para integrar.** Ansel revisa/integrará; Nahuel no mergeó ni desplegó. Se aplicó la autorización técnica de evaluar Torch/audio2.7.1 en un entorno desechable. No falta volver a pedir ese permiso. La diarización GPU del original completo terminó fuera del stack central; la pareja integral fresca se detuvo correctamente en su primera corrida por presión global de memoria. No hubo resumen, total exitoso ni comparación válida de aceleración integral.

Historial y procedencia: `gpu271-evaluation.md`, `real-pipeline-memory.md`; spec performance-observability-pipeline/T14/R1–R7/R9, task_e2a1fd161b4d4910 e issue#907. Este resultado sucede a los estados «en curso» de los documentos anteriores, sin borrar sus fallos.

## Cambios funcionales publicados por esta unidad

- Allocator MLX: guideline4GiB/caché libre256MiB; no hard cap del proceso ni cambio de modelo/decoder.
- Loader pyannote: contexto `safe_globals` de Specifications/Problem/Resolution/TorchVersion; no deshabilita weights_only ni introduce importación arbitraria del checkpoint. Compatible con la carga real2.7.1 probada; no equivale a ausencia de vulnerabilidades del runtime.
- Endpoint nativo de diarización: sustituye el WAV derivado en disco por PCM16→WAV seekable `BytesIO` en RAM, conservando16kHz/mono/PCM16 y el audio completo. El original descargado se limpia y el buffer se cierra también ante error. HTTP, bearer, capability firmada y orden de validación no cambian. No se fuerza cantidad de hablantes ni se descartan ventanas.

La preparación del endpoint no promete memoria constante: PCM RAM crece con duración y se suma a los buffers del modelo. No se inventa admisión global T9 ni una cuota dura. No se altera el runtime del dueño.

## Validaciones reales, no simuladas

### Procedencia y compatibilidad

Wheels oficiales PyPI/files.pythonhosted.org, SHA256/nombre/versión verificados; manifest adjunto a la tarea. Python3.11.12/macOSarm64, Torch/audio2.7.1, sympy1.14.0; resto de dependencias existentes reutilizadas read-only. `pip check` PASS e imports efectivos desde scratch. Dueño permanece Torch/audio2.5.1/sympy1.13.1.

Carga del **lifespan real del archivo PR917** en el venv aislado, offline, sin credenciales del dueño: ambos modelos `mps:0`; parámetros basales centroid/min_cluster_size12/threshold0,7045654963945799/min_duration_off0. Allowlist cerrada después de cargar, comparando el conjunto tras importar dependencias (el primer probe comparaba antes de esos imports y falló por su propio baseline, no por la carga).

LSTM MPS acotado:25iteraciones con driver108118016→108101632B y tensores2924800B constantes; y/h/c exactos frente al operador2.5.1 de referencia. Es prueba del wheel real, no mera lectura de autorelease en source ni certificación acústica.

### Conversión del endpoint real

Ejecutado `_convert_to_wav` del candidato con ffmpeg real y el original, sin inferencia adicional:8,441s;90477120frames/5654,82s,16kmono/16bit, buffer cerrado. SHA256 PCM `5bada55961ecb54f84190f039bf0d76bed05513e6a9c87c0bf19ec687e11007a`, **idéntico al input PCM del MPS exitoso**. Original400361891B/SHA256`9b53197391d1bbbb38962da948ddec8189f411bfffb6086100fc5f45a09c7857` intacto antes/después. No WAV del original en disco.

Además, normalización de todos los65536valores int16 y lectura/crop `Audio` real sobre IOBase sintético: igualdad exacta frente a float32 de referencia. Eso prueba compatibilidad de transporte, no precisión humana.

### Diarización completa del original

Job`job_3aabb0b0efc24691`, child63186, ejecución única y sin ASR/Ollama propios concurrentes. Preparación original→PCM por pipes, WAV solo RAM, entrada IOBase oficial de pyannote. RNG experimental Torch/NumPy0; batches4/4, clustering global/parámetros intactos y sin num/min/max_speakers. Segmentación y embeddings efectivos `mps:0`; fallback MPS deshabilitado.

- Diarización760,811s; total del child772,008s, incluye preparación/imports/carga.
-5646pasos de segmentación y4235batches de embeddings completos.
-1594segmentos, **8labels acústicos frente a3personas indicadas**. No mejora de precisión acreditada; no identidades validadas ni WER/DER sin referencia temporal humana.
-Driver de embeddings~253394944B estable; final253657088B. Live32480512B estable; máximo RSS observado1343307776B. Presión1 durante la corrida exitosa. RSS/driver/footprint no son contadores sumables ni utilización GPU.

Los intentos previos se conservan: TypeError del logger NumPy corregido con int explícito; guardia inicial inmediata alineada al contrato de experimento30s; abortos correctos por warning sostenido30,08s/30,21s; variante de scheduling4/16 no promovida por nueva advertencia global. Streaming/in-place eliminaron copias innecesarias, pero por sí solos no hicieron finalizar aquella vía. El reclaim del allocator devolvió0: no se atribuye un arreglo a esa llamada. IOBase permitió completar esta corrida, sin afirmar causa exclusiva universal.

## Pareja integral fresca: fallo de capacidad observado

Supervisor`job_c0845c5ad6f54eed` debía ejecutar full2 y full3 secuencialmente, sin replay. Full2/run`perf907-fe4fa139`, orquestador73362, ASR73471 y luego MPS80300; full3 **NO se inició**, porque el supervisor terminó al fallar full2. No se reporta como aún ejecutándose.

Fuente backend QA bd638ee, misma configuración acústica congelada, nueva semilla experimental0, MLX4GiB/256MiB, MPS4/4, pipelines nativos separados; API/worker Python host e infra central Docker temporal (PG/Rabbit/S3). Es validación aislada, no instalación de main. El body S3 se transmite por chunks y el hash se verifica antes de inferir; no se retienen400MB del original en el parent. S3 temporal en disco bajo directorio privado, no tmpfs; se preservaron controles y todos los servicios centrales necesarios.

- ASR completo718,578s, **1548turnos reales preservados**; handler729,896s. El checkpoint histórico1506/hash y el intento1549 siguen separados; no se inventa recuperación del raw1506 ya eliminado anteriormente.
- MPS inició con presión1 y ambos modelos mps:0. A41,771/56,816/71,821s del child, presión2 sostenida mientras driver273006592B/live32480512B se mantuvieron estables.
-Guardia abortó a71,850s, con warning30,122s, RSS547376KiB; swap host15964,12MiB usados de17408MiB. Backend terminó el intento a817,649s y eliminó sus3contenedores a818,462s.
-No atribución/resumen transaccionales en esa corrida ni total exitoso.817,649s es **duración hasta fallo**, nunca baseline total comparable.

La guardia permanece: preflightnormal, warning≥30s aborta y crítico aborta inmediatamente. No se la relaja, no se ejecuta CPU, no se repite la misma carga sin nueva capacidad ni se paran apps/servicios/modelos ajenos. Que la presión vuelva a1 después del cleanup no prueba una ventana estable para todo el pipeline.

**Acción externa necesaria:** coordinar una ventana con memoria suficiente para todos los servicios y la inferencia, liberando únicamente aplicaciones/trabajos que el dueño elija. No se recomienda ocultar el problema apagando S3/Rabbit/PG a mitad del benchmark ni presentar esa topología distinta como equivalente. Una vez disponible esa capacidad, repetir ambos integrales frescos; conservar checkpoints para una continuación funcional explícita, no usarlos como latencia de nueva inferencia.

## Atribución real parcial, explícitamente replay

Para aprovechar el trabajo preservado, se ejecutó la función productiva sobre el ASR real1548 de full2 y la diarización real1594/8labels del stage5 (mismo original, parámetros y semilla). Es **replay de outputs reales**, no otro benchmark sintético ni pipeline integral.

1546assignments/2turnos sin evidencia positiva/0intervalos de turno inválidos; igualdad exacta con el oracle naive en turnos/hablantes/desempates/overlap_ms. Observación única6,601ms, sin extrapolación al total ni percentiles. Resultados privados0600 se conservan fuera de Git; no se publican textos, nombres, muestras ni embeddings.

## Seguridad: hallazgo que no se oculta

Consulta pública OSV por versiones exactas: Torch2.7.1 tiene advisories conocidos, entre ellos **GHSA-63cw-57p8-fm3p / CVE-2026-24747**, corrupción de memoria/RCE con checkpoints maliciosos incluso weights_only=True. También existen advisories en lstm_cell/jit.script/unpack_sequence/ctc_loss. Torchaudio2.7.1 y sympy1.14.0 no devolvieron advisories en esa consulta; eso no es garantía general.

La evaluación usó exclusivamente checkpoints existentes/copias hash-verificadas, corpus autorizado, modelos/parámetros fijos y red denegada en el proceso de carga/inferencia; no aceptó checkpoints de terceros ni abrió otra superficie. No se afirma que Torch2.7.1 sea libre de vulnerabilidades ni se lo fija/instala como runtime productivo. El contexto de4tipos no remedia una falla del unpickler.

Antes de recomendar un despliegue hace falta resolver compatibilidad/seguridad con un runtime parcheado, sin excepciones de política ni cambios de modelo. Esto es distinto de volver a pedir autorización para evaluar2.7.1, que ya se ejecutó. Ninguna política de seguridad se debilitó para hacer pasar las pruebas.

## Controles de código y trazabilidad

RED del nuevo transporte1fallo/1PASS; tras implementar,228PASS/1SKIP en ASR/diarización/transcripción/assignment,15,68s. Skip: integración PostgreSQL sin URL, no afirmada como validada en esa suite. Contratos HTTP de bearer/capability antes de IO intactos; cierre de buffer y borrado del original descargado probados ante éxito y error de inferencia; timeout conversión no crea derivado ni altera fuente. Ruff focal PASS; mypy estricto de3tests diar PASS. Validación final/SHA/compile/baseline global se registran en el comentario de PR/tarea al publicar.

Se preserva íntegra la matriz por reparación de `main-delivery.md`: #912/main, T1–T3/telemetría y dependencias; QA bd638ee/#899/#902 fuera del delta siguen identificados, no arrastrados ni declarados desplegados. No TS/Rust/UX tocados. Actions desactivado por aprobación; no se invoca facturación como bloqueo. PR permanece DRAFT por evidencia integral y revisión pendientes, no se confunden publicación, integración y aceptación.
