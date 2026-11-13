# Recorrido real: arranques, memoria y bloqueo observado

## Objetivo y aislamiento

Corrección explícita de Fer 13/11/2026 18:02, APX `task_e2a1fd161b4d4910`, issue #907. La entrega de rendimiento total exige original completo → carga API → almacenamiento → RabbitMQ → ASR real → diarización real → persistencia → solicitud de resumen → Ollama real → persistencia/lectura y playback, con etapas, esperas, recursos y total, corrección del cuello dominante y repetición comparable. **Todavía no se completó ese recorrido.** Los resultados sintéticos de assignment no lo sustituyen.

Se creó rama/worktree **`perf/907-real-pipeline` desde `bd638ee`**, conservando el stack QA completo sin editar worktrees ni servicios existentes. Se verificó ausencia de proceso de conteo pyannote activo antes de los arranques; no se ejecutó Invesa. Original read-only: 400361891 bytes, duración completa **5654,853 s** (94m14,853s). Su hash se calculó antes/después de los dos arranques reales y se volvió a comparar al final: **igual en ambos y en el archivo actual**. No se modificaron reuniones, nombres, assignments ni resultados existentes.

Se reutilizaron exclusivamente pesos instalados, sin descargas ni APIs de pago: MLX whisper-large-v3-turbo snapshot `a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb`, pyannote3.1 snapshot `84fd25912480287da0247647c3d2b4853cb3ee5d`, MPS. Se conservó configuración de generación local `qwen2.5:14b`/900s, ASR/diarización3600s, presentación granular/atribución exclusiva/VAD activas. Las instrucciones de la solicitud histórica de resumen de esta grabación se leyeron mediante transacción **READ ONLY**, copiadas a scratch privado sin imprimirlas. No se suministró conteo esperado ni se cambiaron thresholds, modelos o texto de instrucciones.

El harness usa API/worker del código QA, PostgreSQL16/RabbitMQ3/RustFS reales y propios, identidades nuevas en una DB exclusiva y secretos sintéticos. Se preservan autenticación de usuario, firma de mensajes y autorización por grabación de motores HTTP propios. No hay proveedor de inferencia simulado. El adapter de diarización decodifica el original completo a PCM16/16kHz mono **en memoria**, sin crear WAV ni muestras de voz en disco. El downloader puede copiar temporalmente el original completo sin transformarlo; se elimina con el scratch de ejecución. El logging instrumental contiene únicamente etapas, tiempos, resultados categóricos, versiones, contadores y recursos, no audio/textos/prompts/respuestas/tokens de acceso.

## Intentos conservados

| Run / job / PID coordinador | Avance real observado | Resultado |
|---|---|---|
| `baseline-471bd8125e78`; `job_6ec5c057e6ef4532`; PID **3868** | API recibió el original completo, HTTP200, **5,091s**; broker publicó/confirmó y worker consumió; descarga nativa **5,985s**; VAD comenzó a35,281s desde arranque. VAD finalizó a80,801s e inferencia MLX llegó a iniciarse durante el cierre del proceso síncrono | Guard detectó presión de memoria nivel2 sostenida **30,21s**, canceló a64,361s; limpieza completó a88,366s. No salida ASR completa, diarización, resumen ni tiempo total válido. |
| `baseline-ccb0791d3a6c`; `job_9628cdb565ea43c8`; PID **6892** | Segundo recorrido real con carga diferida de diarización, callbacks de memoria de VAD, sincronización y liberación de caché **solo propia**; misma configuración acústica. VAD completó **5248/5646** ventanas antes del guard | Presión nivel2 sostenida **30,26s**; cancelado a76,054s; limpieza a100,582s. No baseline completo. La reducción de carga simultánea y vaciado de caché no resolvieron el bloqueo. |
| `baseline-3b624c3debdf`; `job_afa61f3e0d5a4313`; PID **9699** | Preparado un experimento de layout contiguo por lote, sin cambiar valores/orden/dtype/modelo. **No se ejecutó inferencia** | Rechazado por presión de memoria inicial nivel2; sin recursos creados. No es una prueba del experimento ni una corrección validada. |
| `baseline-06f0223f9638`; `job_0ce7c818d84c4238`; PID **10639** | Admisión esperó ventana estable de memoria normal; no se ejecutó inferencia ni se crearon contenedores | Presión nivel2 en todos los muestreos durante **>120s** (130,887s observados con overhead). Error: `Host memory warning prevents admission after 120 seconds`. El host seguía en nivel2 después de eliminar todos los procesos/recursos de estos runs. |

La primera versión del harness retornó exit0 aunque su manifest indicaba `status=failed`; se corrigió a exit1 para los siguientes. En el tercer intento, rechazado antes del hash inicial, un bug del campo de preservación comparó el hash actual contra `None` y registró `input_unchanged=false`; no demuestra cambio del original. Se conserva el manifest tal como salió, se corrigió el campo a “no evaluado” cuando no existe prehash y la comprobación independiente final confirmó igualdad con ambos arranques reales.

## Datos de memoria que sí se observaron

En el segundo intento, VAD usando los mismos pesos/dispositivo/parámetros:

| Tiempo desde arranque | Ventanas procesadas | Metal driver después de synchronize/empty_cache | Tensores activos PyTorch |
|---:|---:|---:|---:|
|43,853s|0/5646|561184768 bytes|5896192 bytes|
|49,011s|864/5646|3281043456 bytes|5896192 bytes|
|54,048s|1920/5646|4354785280 bytes|5896192 bytes|
|59,167s|2944/5646|5428527104 bytes|5896192 bytes|
|64,306s|3936/5646|6502268928 bytes|5896192 bytes|
|69,400s|4800/5646|7576010752 bytes|5896192 bytes|
|74,689s|5248/5646|8658141184 bytes|5896192 bytes|

Son métricas del proceso propio obtenidas de `torch.mps`, no atribución del consumo global del host. **Hay retención/crecimiento observable de memoria del driver correlacionada con VAD; no se demuestra todavía una causa única, un OOM ni defecto de modelo.** No se pudo identificar el cuello dominante del tiempo total porque falta un recorrido completo. No se habilitó CPU fallback, no se redujeron parámetros de calidad, no se eludió el guard, no se borró caché del dueño ni se descargaron modelos.

## Evidencia privada y limpieza

Raíz de evidencia de esta sesión:

`/var/folders/x6/96ywnlxd7kxfr4qns4c8_0hc0000gn/T/apx-scratch-d2296a21/th_c51fa10ada16421f/real-pipeline/`

Contiene `baseline-safe.log`, `baseline-2-safe.log`, `baseline-3-safe.log`, `baseline-4-safe.log`; cada directorio de run contiene `manifest.json` y `events.jsonl` seguros. Los manifests conservan SHA de código, entrada, configuración y script; la versión actual copia el harness exacto al directorio del run después de admisión. `instructions-private.txt` y cualquier futura salida de contenido son privados y no se adjuntan a Git ni a este informe.

Los procesos propios se terminaron, los contenedores se eliminaron por sus **IDs exactos** con `docker rm -fv`, incluidos sus volúmenes anónimos, y el directorio temporal de originales descargados/decodificación se eliminó. Cada run informa `cleanup_verified=true`; consulta posterior por etiqueta `sauri.performance.run` vacía y ningún PID de sus servicios activo. No se paró proceso ajeno ni se cambió el entorno del dueño.

## Acción necesaria y estado honesto

**Bloqueo actual:** el host no ofrece una ventana de memoria normal aun sin cargas de estos runs, y los dos arranques reales previos alcanzaron el guard bajo VAD. La siguiente hipótesis técnica (materializar un layout contiguo antes de transferir lotes a MPS) quedó preparada, **no probada** por falta de admisión; no debe promoverse como arreglo.

**Recomendación a Ansel:** coordinar una ventana local con capacidad suficiente y sin inferencias simultáneas, manteniendo los controles; no detener servicios ajenos ni exigir pagos. Una vez disponible esa ventana, repetir la admisión y probar la hipótesis con el mismo original y configuración, verificar igualdad de valores del adapter y completar baseline/pipeline. Si la memoria vuelve a crecer, investigar el manejo de buffers Metal con esa evidencia antes de cambiar parámetros/modelo. No presentar las corridas abortadas como ganancia de velocidad.

La tarea **permanece abierta**. #912 ya está en main como `6302c48` (verificado por API/ancestría), pero ese merge técnico no acredita rendimiento total, instalación, precisión ni preservación de toda la UI QA. La política de validación local y la matriz de reparaciones se documentan por separado.
