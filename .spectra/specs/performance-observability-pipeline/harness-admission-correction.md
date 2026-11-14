# Corrección acotada de admisión del harness — #907

## Autoridad y límites

APX `task_e2a1fd161b4d4910`; coordinación Sauri 13/11/2026 23:38–23:41Z. Corrige el admisor propio que inició `ef325040b85e` sin excluir suites transitorias. Trazabilidad: requisitos 3.2/3.4 (espera veraz/no modificar procesos ajenos), 4.3/4.4 (calidad/original), 5 (evidencia), 8 (validación) de `performance-observability-pipeline`.

**No es T9/producto:** no implementa un scheduler global ni una reserva GPU, no modifica ASR, diarización, Ollama, parámetros, modelos, dispositivos, dependencias, servicios ni UI. No introduce CPU como alternativa. No ejecuta inferencias ni reanuda una corrida. El objetivo de rendimiento completo sigue abierto.

## Hallazgo de la corrida retirada

Código/harness y SHA/configuración originales preservados. Logs de `baseline-ef325040b85e` en el scratch original de esta tarea:

- Coordinador15072; servicios ASR15279/diar15353/API15354/worker15369; entrada original400361891 bytes,5654,853s.
- Upload real HTTP200 en4,464s; worker consumió y ASR/VAD real comenzó.
- Presión nivel2 desde68,162s; a98,740s seguía nivel2. `run.failed` registra **RuntimeError a98,846s**. El código del guard vigente dispara ese error al sostenerse warning≥30s: ese es el fallo acreditado del coordinador, no un OOM acreditado.
- Log de diarización: `service.start` a18,738s; **cero `provider.diar.start`**. La preparación del motor era diferida: el recorrido no había solicitado inferencia de diarización. Coordinación observó15353 `defunct` antes de señalar procesos.
- **No se puede determinar la causa de salida de15353**: el harness descartaba stderr y no persistió exit code/señal en el momento de la caída. Un zombie/nivel2 no demuestra OOM, error del modelo ni que el guard haya terminado ese proceso. Tampoco autoriza reinstalar dependencias o cambiar modelo/dispositivo.
- El runner entró en limpieza y registró `KeyboardInterrupt` durante `process.wait(timeout=20)`. Coordinación reportó SIGINT al runner para retirar el solape. El evento Python solo no identifica emisor; ambos hechos se conservan sin inventar otra causa.
- Al reconciliar desde esta sesión a23:40:54Z, **todos esos PIDs y contenedores ya estaban ausentes**: no repetí su retirada ni maté otra GPU. Original hash nuevamente igual al prehash. Se agregó `reconciled.json` separado; manifiesto inicial y logs no se reescribieron.

La evidencia anterior de otro run `perf907-2ecb4725` pertenece a otra continuación de la misma tarea. No confundir sus965s/contadores con los de `ef325040b85e`. Su etiqueta antigua `transcription_committed` fue corregida por esa continuación a retorno del handler; no acredita una transcripción persistida.

## Cambio funcional

El admisor automático privado `real-pipeline/admit.py` quedó **desactivado de forma persistente** (no solo su PID): conserva fuente histórica en `admit.py.disabled-original.txt`, imprime categoría `admission.disabled` y sale2, sin iniciar proceso alguno. Se comprobó ejecutándolo sin modelos. No hay nuevo timer, observador automático ni reintento programado.

Nuevo `scripts/platform/pipeline_admission.py`: verificación **solo lectura**, sin opción `--run` ni launcher:

1. Requiere inventario explícito de contenedores persistentes por ID completo, recursos propios por ID **y** etiqueta de run, y servicios persistentes revisados por identidad PID+inicio+hash de comando. Nunca descubre persistencia por nombre o bajo consumo de CPU.
2. Observa procesos, contenedores corriendo, presión y swap en cuatro muestras continuas separadas10s (≥30s). Rechaza observaciones vacías, malformadas, inconsistentes, futuras, viejas o discontinuas. Fallas de Docker/ps/sysctl no equivalen a ausencia de trabajo.
3. Bloquea suites (pytest/Vitest/compilación/tipos) y trabajos de inferencia identificables **aunque marquen CPU0**, incluso si su identidad se colocó erróneamente en la lista de servicios idle. Conserva el umbral previo de10% para servicios; una reserva de proceso idle exige identidad exacta, no solo PID reutilizable.
4. Todo contenedor corriendo no excluido explícitamente bloquea. Un recurso propio con etiqueta de otro run tampoco pasa.
5. Conserva presión normal1 como condición, sin bajar ni cambiar el guard de warning sostenido de los runs existentes. Swap alto se registra, no se transforma en capacidad libre ni se inventa un nuevo umbral global. No pide cerrar aplicaciones ni mata/descarga procesos ajenos.
6. Aun si todas las exclusiones están claras, devuelve **`exclusions_clear_requires_manual_review` / `automatic_launch=false`**, no permiso ni lease GPU. La coordinación debe comprobar actividad real de servicios compartidos y capacidad antes de cualquier ejecución manual. Una foto de CPU baja o memoria normal no prueba que la GPU esté libre. Las observaciones también tienen carrera temporal: este check no reemplaza una reserva/fencing global ni la vigilancia durante una corrida.

Los errores/salidas contienen categorías y contadores/IDs operativos, no comandos completos, paths privados, environment values, audio, nombres, textos, prompts o respuestas. El collector solo ejecuta consultas `sysctl`, `ps`, `docker ps` y `docker inspect` **de etiquetas**; no lee Docker Env ni logs. No usa una plataforma nueva ni instala dependencias.

## Formato de inventario y uso técnico

El archivo se conserva privado, fuera de Git. Ejemplo mínimo válido (sin exenciones, por tanto no hará pasar recursos/procesos existentes):

```json
{"schema_version":1,"persistent_container_ids":[],"owned_container_ids":[],"owned_run_id":null,"idle_services":[]}
```

Cada servicio idle revisado se representa por `pid`, `started_at` y `command_sha256` tal como los captura `parse_processes`; no agregar suites ni inferencias a esa lista. IDs persistentes se toman solo de la lista de QA persistente **ya revisada**, no de todos los contenedores presentes en una foto.

Invocación técnica del check: `python scripts/platform/pipeline_admission.py --inventory /ruta/privada/inventory.json`. Exit2 significa rechazado/telemetría inválida. Exit0 significa solo exclusiones claras para **revisión manual**, nunca arranque autorizado. No encadenar esta salida con un launcher automático. Fer no tiene que ejecutar comandos para esta corrección.

## Validación observada

En `.worktrees/perf-907-admission-guard`, rama `fix/907-harness-admission`, base main6302c48; sin cambios en los otros worktrees:

- `backend/.venv/bin/python -m pytest -p no:cacheprovider -q scripts/tests/test_pipeline_admission.py`: **66 PASS**,0,65s. Son pruebas contractuales con fixtures, no benchmark ni calidad acústica.
- `backend/.venv/bin/ruff check --config backend/pyproject.toml scripts/platform/pipeline_admission.py scripts/tests/test_pipeline_admission.py`: **PASS**. Se corrigió una línea larga detectada en el primer pase.
- `backend/.venv/bin/mypy --strict scripts/platform/pipeline_admission.py scripts/tests/test_pipeline_admission.py`: **PASS,2 archivos**.
- `git diff --check`: **PASS**.
- Ejecución real **solo lectura** del nuevo CLI con seis IDs persistentes de QA y ninguna exención de procesos: **exit2**, cuatro muestras; motivos `memory_pressure`, `transient_suite_or_inference`, `unexcluded_running_containers`. Detectó el coordinador16196/ASR16714 del recorrido ya existente, tres contenedores no excluidos y otros servicios sin confirmación idle; no los detuvo ni modificó. Swap observado17229278085 bytes. No fue una admisión ni una inferencia nueva.
- Ejecución del admisor privado desactivado: **exit2, `admission.disabled`**, sin child/launcher.

No se cambió backend/frontend/extensión ni manifests de dependencias. No se ejecutaron suites amplias/builds que compitan con la GPU. La validación focal anterior corresponde al cambio Python de herramientas; los controles globales pendientes y deuda de main siguen declarados en #915. Antes de cualquier futura unidad funcional debe validarse su SHA exacto.

## Estado de entrega

Nahuel publica esta corrección para revisión de Ansel, **sin merge ni instalación**. No hay una solución MPS validada, pipeline completo terminado, comparación total antes/después ni mejora de precisión demostrada por este PR. La continuidad es verificar el resultado del recorrido GPU ya coordinado y completar el objetivo real sin duplicarlo. No repetir corridas por este cambio de admisión.
