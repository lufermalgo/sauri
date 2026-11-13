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

La pieza de atribución T1–T3 fue encargada después de esa revisión; aún no se recibió entrega de implementación. Se mantiene explícitamente pendiente, sin fabricar commit ni declarar ahorro de tiempo total del resumen ni mejora de precisión acústica.
