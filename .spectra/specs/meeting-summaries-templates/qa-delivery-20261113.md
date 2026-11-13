# Integración QA de resúmenes — 2026-11-13

## Candidato, alcance y estado

Rama `feature/summary-qa-delivery`, worktree aislado `.worktrees/feature-summary-qa-delivery`.
Base `fff14b2` (escucha desde original, nombres e indicador), integrada con backend `dcbf452`, UI `ff5c938` y configuración de plantillas `887c2d9` (prerrequisito: la DB QA no tenía plantillas; no se creó default artificial).
Candidato funcional `6b9eed34c56566c65707df84cfcf3f3b60ee1937`.
No merge a main. No se tocó código ASR ni diarización; hashes SHA256 de ambos workers coinciden con el contenedor anterior.

**Entrega parcial, no lista para aceptación:** el portal APX t26 estaba en Sign in, no autenticado. `browser_use_my_login` no acepta IP como dominio; handoff de login venció sin completarse. Luego del despliegue se confirmó nuevamente Sign in en APX. No se tomaron tokens desde shell, ni se eludió login. No se generó todavía el resumen real de Fer ni se verificó visualmente la sección protegida. La imagen del snapshot muestra exclusivamente login; no demuestra el resumen.

## Runtime QA efectivamente actualizado a las 19:11Z

Proyecto Docker `sauri-local-qa-04d47768cad6`, mismos seis servicios; se reemplazaron solamente api, worker y portal.
- API / worker: `sauri-summary-api:d06a1f1` (backend sin cambios posteriores en la integración de plantillas).
- Portal: `sauri-summary-portal:templates` (contiene candidato `6b9eed3`).
- Endpoint portal `http://127.0.0.1:15273`, API `http://127.0.0.1:18100`.
- Migración aditiva `013_manual_recovery_persistence -> 014_meeting_summaries_templates` aplicada exitosamente mediante Alembic, sin borrar datos.
- Config original reutilizada con `qa.env`; script comprobó igualdad del entorno de api/portal. En worker cambiaron solamente `SUMMARIZATION_OLLAMA_URL=http://host.docker.internal:11434` y `SUMMARIZATION_OLLAMA_MODEL=qwen2.5:14b`.
- Ollama ya estaba activo y `api/tags` confirmó `qwen2.5:14b` instalado. No se descargó ni arrancó modelo/servicio personal.
- Logs worker: consumidores `transcribe`, `diarize`, `summarize`, `summarize.failed` registrados. No había procesamiento ASR en curso en los logs previos (última finalización 16:35Z).
- API `/health`: `{"status":"ok"}`; portal `/portal-health`: `ok`; portal healthy. Postgres, Minio y RabbitMQ conservaron contenedores/volúmenes, siete horas de uptime.
- Override de despliegue y script de comparación en temp del ejecutor: `summary-delivery.override.yml`, `summary-deploy.py`.

## Pruebas observadas

- `npm run typecheck --workspace frontend`: PASS.
- `npm test --workspace frontend`: 18 archivos / 173 pruebas PASS. Advertencias conocidas jsdom por `HTMLMediaElement.pause` no implementado, sin fallos.
- `npm run build --workspace frontend`: PASS. Build Docker backend y portal: PASS.
- `npm test --workspace @sauri/shared-types`: 2 pruebas PASS.
- Backend `PYTHONPATH=. pytest -q tests/summaries tests/templates tests/meetings/test_processing.py tests/speaker_review/test_generation_api.py --ignore=tests/summaries/test_worker_broker.py` con DB desechable `sauri_t11_summary_delivery`: **78 passed, 1 skipped**.
- Backend integración `PYTHONPATH=. pytest -q tests/integration/test_summary_pipeline.py` con DB desechable `sauri_t9_summary_delivery`: **9 passed, 6 skipped**.
- Intentos iniciales sin env PG y luego con prefijo T11 en suite T9 fallaron por guardas correctas de aislamiento; corregidos creando DBs con prefijos exigidos, sin debilitar pruebas.
- Broker real de agotamiento no ejecutado: exige broker exclusivamente desechable, no se usó cola QA compartida para inyectar fallos. Los skips requieren dependencias de integración dedicadas.
- `git diff --check fff14b2..HEAD`: PASS.
- No se declara CI GitHub pasada, ni calidad del resumen, ni aceptación de Fer.

## Paso necesario para completar

Completar login APX t26, configurar/seleccionar instrucciones personales desde Summary templates, abrir InvesaSegundaSesionTecnica.webm (meeting `185a7902-17d3-4a35-b220-7e671bcab62c` según logs runtime; confirmar título en UI), solicitar resumen, esperar estado y comprobar tema/puntos visibles más persistencia al recargar. Registrar captura y respuesta real. No inventar plantilla o calidad por defecto.
