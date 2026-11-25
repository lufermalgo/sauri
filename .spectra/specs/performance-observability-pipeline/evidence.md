# Evidencia — Primera entrega de rendimiento y observabilidad

## Identidad y alcance

- Pedido recibido 13/11/2026 17:10 (22:10Z); ventana inicial hasta 22:40Z.
- Issue: https://github.com/lufermalgo/sauri/issues/907 . APX: `task_e2a1fd161b4d4910`.
- Base instalada previamente: QA #902 `178f893551405774bc5d9006d0eb90cd4c33f586`; no main.
- Worktree de integración: `.worktrees/perf-pipeline-observability`, rama `perf/pipeline-observability`.
- Primer commit propio `8b17a86`: spec de tres fases y contadores seguros de Ollama.
- Sin cambios a grabación original, DB del dueño, nombres, modelos ni parámetros acústicos. No se disparó inferencia GPU/LLM para la primera medición de etapa. No se tocó el checkout raíz ni se limpiaron worktrees ajenos.

## Tres fases SDD

`requirements.md`, `design.md` y `tasks.md` elaborados a pedido explícito de Fer, con metadata `.config.spectra`. Relacionados con specs de despliegue nativo, resúmenes, revisión de hablantes y playback. La documentación completa no declara la reescritura completa ni aceptación de producto.

Referencias MeetMemo, ghostmeet y meetily revisadas en README, arquitectura y, para ghostmeet, código incremental real. El diseño separa patrones aplicables de afirmaciones no verificadas, restricciones de privacidad, diferencias CUDA/Metal y legado no soportado. Heads públicos registrados en design.md.

## Observabilidad inicial implementada

`OllamaSummarizationEngine` conserva contrato/payload/deadline y emite un evento JSON seguro con timestamp UTC, duración monotónica, outcome (`succeeded|error|timeout|cancelled`), proveedor y contadores numéricos permitidos del sobre Ollama. Convierte nanosegundos a segundos, preserva ausencias y rechaza bool/negativos/no finitos/tipos inválidos. No registra texto de reunión, instrucciones, respuesta, thinking, contexto, URL, modelo libre ni excepciones arbitrarias. No agrega llamadas al motor. Un fallo de logging no convierte un resultado válido en reintento.

**Límite:** esto es instrumentación inicial de una etapa, no la observabilidad integral instalada. Las garantías de lista positiva probadas corresponden al nuevo evento del motor, no a una auditoría de todos los logs preexistentes/dependencias. OTel, correlación distribuida, sanitización transversal, recursos CPU/RAM/I/O/Metal, paneles, cuotas y admisión global están diseñados y en backlog T6–T11, no desplegados.

## Validaciones ejecutadas por Ansel antes de incorporar atribución optimizada

Entorno: macOS, Python 3.13 del venv existente `backend/.venv`; Python mínimo del proyecto 3.11. Comandos ejecutados desde el worktree con el Python absoluto del venv, sin instalar dependencias.

1. `python -m pytest backend/tests/summaries/test_engine_usage.py backend/tests/summaries/test_engine_timeout.py -q`: **33 passed**, 0,13 s tras incluir prueba de timeout.
2. `ruff check backend/app/summaries/engine.py backend/tests/summaries/test_engine_usage.py`: PASS.
3. Desde backend: `mypy app/summaries/engine.py tests/summaries/test_engine_usage.py`: PASS, 2 archivos.
4. Suite `python -m pytest backend/tests/summaries backend/tests/diarization -q` con PostgreSQL y RabbitMQ reales temporales: **182 passed, 1 skipped**, 9,87 s, 5 warnings de deprecación sqlite. La frontera de inferencia está simulada en estas pruebas; PostgreSQL y el broker no.
5. `ruff check backend`: 3 errores de imports preexistentes; mismo resultado en base `178f893`.
6. `cd backend && mypy .`: 82 errores en 8 archivos preexistentes; comparación de conjuntos `error:` con base `178f893`: **0 errores nuevos, 0 removidos**. El candidato agregó un archivo verificado sin errores. No se ocultó deuda ni se desactivaron checks.
7. `git diff --check`: PASS.

### Fallos de preparación corregidos

La primera ejecución de resúmenes sin variables de QA produjo 10 errores de setup (DB/broker exclusivos no configurados), no fallos de aserciones del código cambiado. Se crearon dos contenedores exclusivos temporales y se repitió.

El primer nombre de DB (`sauri_t11_perf907`) satisfacía los tests de resumen pero no el guard de backfill, que requiere también `sauri_qa`. Esa pasada obtuvo 180 passed/1 skipped/1 fallo de guard. Se cambió el nombre a `sauri_t11_sauri_qa_perf907`, sin debilitar tests, y la suite completa pasó como arriba.

Contenedores exclusivos `sauri-perf-907-pg` y `sauri-perf-907-rabbit`, etiquetados `sauri.qa=issue907`, publicados solo en loopback y con límites de memoria. PostgreSQL usó autenticación trust únicamente en esta base descartable sin datos de producto; no se modificó seguridad del entorno del dueño. Ambos se eliminaron con `docker rm -fv` después de cada prueba, incluidos volúmenes anónimos. Verificación posterior `docker ps -a --filter label=sauri.qa=issue907`: vacío. No se crearon redes propias ni se borraron recursos persistentes del dueño.

## Comunicación

Aviso directo solicitado por canal configurado: primer intento con canal explícito devolvió `bad_request: Owner has no address on Telegram Ansel`. Reintento con resolución por defecto `message_contact(to="me")` devolvió envío confirmado a Owner en Telegram Ansel y final de chat. No se dio el primer intento por entregado.

## Muestra de recursos (lectura, no atribución causal)

A las 22:31Z se observaron `docker stats --no-stream`, `memory_pressure -Q` y `sysctl vm.swapusage`, sin alterar procesos. Contenedores del entorno: worker85,32MiB, API105,1MiB, portal7,836MiB, MinIO191,4MiB, PostgreSQL36,13MiB y RabbitMQ148,7MiB. Son muestras del runtime previo, no del candidato ni perfiles máximos. Red acumulada API3,33GB recibidos y30MB enviados; no equivale a una sola reunión ni a throughput instantáneo. Host24GiB; memory_pressure reportó53% libre y swap17.204,50MiB usado. El swap ocupado puede ser histórico: esta muestra no demuestra presión instantánea ni permite atribuir toda la memoria a Sauri. GPU/Metal y energía por proceso no medidos. Estos límites justifican separar alcance host/proceso/contenedor en T7.

## Estado remoto y bloqueo de CI

PR borrador https://github.com/lufermalgo/sauri/pull/908 apilado sobre `qa/combined-899-900` (#902). GitHub Actions run `43519584965`: ambos jobs fallaron **antes de iniciar**, sin steps ni logs. Se consultaron jobs/check-runs/annotations por API después de que `gh run view --log-failed` devolviera `log not found`.

Anotación exacta en ambos: `The job was not started because recent account payments have failed or your spending limit needs to be increased. Please check the 'Billing & plans' section in your settings`.

No es una prueba fallida del candidato. No se cambió facturación, límite de gastos ni controles. PR permanece borrador y no se declara listo para integrar. Requiere que el dueño revise facturación/límite de GitHub y luego reejecutar los controles del candidato final. Aviso directo por `message_contact(to="me")` confirmado a Owner en Telegram Ansel.

## Resultado de velocidad

Lectura DB explícitamente `BEGIN READ ONLY`: la reunión objetivo conserva1519 turnos, rango0–5.650.000ms, revisión1/ocho hablantes y `prepared_result`/`presentation` nulos. Las1517 asignaciones mencionadas en diagnóstico no son1517 segmentos acústicos originales. Esos segmentos no están disponibles en persistencia para replay fiel; no se reconstruyen a partir de asignaciones y se presentan como originales.

La revisión READ ONLY de Nahuel entregó dos benchmarks sobre datos reales existentes, sin implementación ni inferencia nueva:

| Subcamino | Base mediana | Variante mediana | Muestras | Límite |
|---|---:|---:|---:|---|
| Construcción+serialización payload de60849 caracteres, schema recalculado vs cacheado |0,289291ms|0,213396ms|100 por variante, alternadas|Ahorro0,075895ms; irrelevante frente al resumen |
| Dos consultas GET transcript, engine nuevo vs compartido prewarm |14,907125ms|8,170ms|15 por variante, alternadas|Ahorro6,737125ms/45,2%; excluye HTTP, autorización, auditoría y respuesta |

Payloads idénticos en el primer caso. En el segundo se compararon1519 turnos completos (IDs/texto/intervalos/secuencia) en30 lecturas READ ONLY/rollback, sin imprimir contenido. Un primer harness falló con DetachedInstanceError después de rollback; se corrigió copiando meeting_id antes y la pasada posterior completó30/30. No se modificó DB ni código del runtime.

Fuente: informe `read-only-hotspots-178f893.md` en temporal del hilo, con evidencias tool jobs `job_6f7f4bb10a3248e0` (payload), `job_669cc508ba9446f2` (consultas corregidas), `job_6b43f6478fcc412b` (hashes/runtime). Son experimentos de candidato, **no mejoras implementadas/instaladas** ni benchmark de inferencia o UI. T13 agrega la implementación comprobable de pooling al backlog. No se incorpora el microcache solo para aparentar una mejora sustancial.

### Aceleración implementada y verificada antes de22:40Z

Nahuel entregó T1–T3 en commit remoto `462886ed34ca6da850f797e9bd92c77d585fe81a`. Ansel revisó código/índice de cobertura y oracle independiente y lo incorporó mediante cherry-pick `e51e2ec265305b7de02b2f0fc42c7da56c739124` a este candidato. Se mantienen orden, objetos Speaker originales, desempates, multiplicidad acumulada y unión exclusiva; no cambia clustering ni modelos.

Ansel repitió el benchmark con `PYTHONPATH=$PWD/backend /Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python scripts/dev/benchmark-assignment.py`. Incluye construcción del índice, warmup1 y7 muestras por variante alternadas. Entrada **sintética** anónima determinista seed907:1500turnos/2154segmentos/4hablantes; no audio, no datos inventados presentados como reales. Salidas idénticas en ambos modos. Archivo durable `assignment-benchmark.json` conserva versiones, hash, entorno y todas las muestras.

| Modo | Mediana base | Mediana indexada | Aceleración de etapa | Reducción |
|---|---:|---:|---:|---:|
| Acumulado |178,867ms|4,632ms|38,62x|97,41%|
| Exclusivo |178,207ms|4,356ms|40,91x|97,56%|

Un primer comando de Ansel omitió PYTHONPATH y cargó el backend del checkout raíz desde el venv editable: TypeError en `require_exclusive`. No se usó esa ejecución como medición; se corrigió PYTHONPATH al worktree y se obtuvo la comparación de arriba.

Validación final de Ansel en el candidato integrado: **195 passed,1 skipped**,10,27s, suites completas summaries+diarization con PostgreSQL/RabbitMQ temporales reales. Recursos exclusivos eliminados con `docker rm -fv`; consulta por etiqueta vacía después. Además167passed/1skipped focales y Ruff de los5 archivos de código/test/benchmark cambiados PASS; Mypy de4 archivos de código/tests cambiados PASS. El oracle diferencial genera400 ejemplos en ambos modos e inputs degenerados sin mutación. Sin cambios TS/Rust ni pantallas.

**Límite funcional:** mejora CPU de `assign_turns`, usada en el camino sin `prepared_result`; la ruta preparada reutiliza otra salida y no recibe esta aceleración. No se ha medido mejora del tiempo total de transcripción/resumen, ni precisión acústica. La ganancia absoluta de esta carga es aproximadamente174ms, no minutos. El candidato está publicado, no instalado ni integrado en main; CI sigue bloqueado por facturación de GitHub. No se declara reescritura completa.

## Reconciliación verificable de #908 hacia main

La evidencia anterior corresponde al candidato QA original. #908 fue fusionado en `qa/combined-899-900` (`bd638ee`), **no en main**. La entrega de Nahuel en `perf/907-main-delivery` parte de main `ea1dd2a`, preserva todos los archivos de #908 y reconcilia solo los prerrequisitos backend aprobados para que la telemetría de Ollama tenga request/outbox/worker/read reales. Inventario, commits de origen, comandos y límites en `main-delivery.md`.

- Diff candidato: **32 archivos**, sin TS/Rust/UX, sin cambios acústicos ni datos del dueño. Comparación del índice staged con `bd638ee` confirma sin diferencias assignment, módulos summaries completos, oracle, benchmark, pruebas de uso, requirements, design y JSON original del benchmark. Tasks/evidence agregan únicamente trazabilidad de esta reconciliación.
- Backend: **408 passed**, 34,86 s; integración de resúmenes PostgreSQL/RabbitMQ reales: **15 passed**, 7,76 s. Sin skips en ambas ejecuciones finales. Motor doblado explícitamente en pruebas; no se ejecutaron modelos.
- Ruff focal PASS; mypy focal PASS (25 archivos). Full conserva **3 errores Ruff y 82 mypy/8 archivos** del baseline main, con **0 diagnósticos nuevos ni eliminados**. No equivale a checks full verdes.
- Una prueba adicional de playback storage carece de `OBJECT_STORE_ENDPOINT`; la misma falla está reproducida en baseline main. Se excluye solo ese contrato ajeno de la suite ampliada; no se accede al storage del dueño.
- Repetición CPU sintética con baseline preoptimización `178f893`: acumulado **38,44x**, exclusivo **43,31x**, salidas iguales e índice incluido. No es benchmark acústico ni mejora end-to-end. Se conserva el JSON original de #908 sin reemplazarlo por esta repetición.
- Recursos propios `sauri-perf907-pg` y `sauri-t10-mq-90720261113` eliminados mediante `docker rm -fv`; consulta posterior de ambos nombres vacía. Sus volúmenes anónimos se eliminaron en la misma operación. No se detuvieron servicios del dueño.
- `git diff --cached --check` PASS. Hooks conservados. No se integra main en esta tarea: **Ansel revisa e integra**, sin saltar protecciones. El run previo `43521042915` confirma bloqueo de facturación; publicación y checks del nuevo PR se verifican por separado.

### Publicación de la reconciliación

Código y evidencia publicados en commit `e7e70a66c16bc723b67c195617ebf9556b4cb814`, PR **[#912](https://github.com/lufermalgo/sauri/pull/912)**, base **main**, rama `perf/907-main-delivery`. `git diff bd638ee HEAD --` para los archivos funcionales de #908 mencionados arriba devuelve vacío; `git diff origin/main...HEAD --check` PASS y checkout limpio después del commit. El único cambio posterior de entrega es documentación de publicación, sin modificar código probado.

GitHub responde `mergeable=MERGEABLE`, `mergeStateStatus=CLEAN`: **sin conflictos Git**, no una certificación de CI. En la consulta posterior a publicar, `statusCheckRollup=[]`, sin run Actions para esta rama; hay una suite externa Cursor queued, sin resultado. No hay checks verdes que declarar. Se conserva además evidencia del bloqueo de facturación en los runs previos. Consultar protección de main devuelve HTTP403 “Upgrade to GitHub Pro or make this repository public to enable this feature”; no se modifica la configuración ni se deduce una autorización para integrar. Ansel debe verificar los controles actuales al revisar. Este era el estado al publicar: PR para revisión técnica, **no integrado ni instalado**. Queda superado respecto de CI y criterio de cierre por la actualización siguiente.

### Política y objetivo vigentes (13/11/2026 17:55–18:02)

Fer aprobó desactivar Actions y reemplazarlo por validación local obligatoria previa a cada merge, ligada al SHA exacto: pruebas, tipos, compilación y seguridad pertinentes. Ansel aplicó `actions/permissions enabled=false`, confirmado también mediante GET por Nahuel. No hay que pagar ni aumentar límites; checks fallidos históricos no se declaran aprobados. La facturación **ya no es un bloqueo pendiente**; faltan los equivalentes locales pertinentes y su evidencia antes de integración.

Fer aclaró además que el benchmark sintético no acredita rendimiento total. #912 queda preservado como candidato técnico. **La tarea sigue abierta** para ejecutar el pipeline completo real con el original de la grabación E en recursos aislados, medir etapas/esperas/recursos/total, corregir el cuello dominante y repetir comparable. Se autorizó inferencia para ese recorrido; no modificar originales, nombres, assignments ni el entorno del dueño. La nueva ejecución va en rama/worktree aislados `perf/907-real-pipeline` desde `bd638ee`, sin instalar ni fusionar #912 por parte de Nahuel.

### Resultado real y estado posterior de main

Se verificó por API que #912 fue mergeado a main a23:05:13Z como `6302c485adbcb540edc6eb1312346d8d30aece08`; su head `a279aea` es ancestro de `origin/main`. Nahuel no hizo ese merge. La validación local sustitutiva se inventaría en `local-validation-policy.md` (incluye 27 contratos APX PASS reportados en revisión de Ansel sobre `a279aea`); los faltantes se mantienen explícitos, no se considera todo verde.

La matriz solicitada de todas las reparaciones QA, commits/PRs, pruebas y estado frente a main y #912 está en `qa-preservation-matrix.md`. Reparaciones no transportadas permanecen identificadas y preservadas en QA; no se declara que main ya sea equivalente a ese entorno.

**Dos arranques completos de infraestructura con el original real llegaron a API/almacenamiento/broker/worker/descarga/VAD e inicio de ASR real, pero fueron detenidos por presión de memoria sostenida.** Otras dos admisiones rechazaron memoria ya elevada antes de inferir. Detalle, PIDs/jobs/runs, medición de crecimiento Metal, alternativas intentadas, preservación, limpieza y acción necesaria en `real-pipeline-attempts.md`. Original verificado intacto; todos los recursos propios eliminados; no se mataron procesos ajenos. **No hay baseline total completo ni antes/después comparable, y la tarea sigue abierta.**
