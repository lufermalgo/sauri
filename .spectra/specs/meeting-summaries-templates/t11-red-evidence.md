# T11 / #279 — Evidencia RED del consumidor de resúmenes

Fecha: 2026-11-13. Spec y fases aprobadas: `meeting-summaries-templates`; contratos D4/D9/D15. Dependencias preservadas: paquete T2/T8 #866 y T9 #867.

- Candidato anterior a implementación: `1688b76`.
- Commit de pruebas: `7a7183b75d86049c957a624e6708aabf5186306b`.
- Archivo: `backend/tests/summaries/test_worker.py`.
- Responsable: Ansel; Fer conserva merge. No implementación del consumidor ni cambios de producción.

## Ejecución observada

PostgreSQL `postgres:16-alpine`, contenedor exclusivamente temporal `sauri-t11-pg-96549`, base `sauri_t11_96549`, puerto local efímero 50033. Variable `SAURI_QA_POSTGRES_URL` apuntando a esa base. Cada prueba crea su propio esquema UUID con tablas reales y datos sintéticos. La fixture rechaza bases fuera de `sauri_t11_*` y elimina solo su esquema.

Comando desde la raíz del worktree:

```bash
SAURI_QA_POSTGRES_URL="$DISPOSABLE_PG_URL" PYTHONPATH=backend /opt/homebrew/bin/pytest backend/tests/summaries/test_worker.py -q
```

Resultado repetido antes de implementar: **6 failed in 0.91s**. Todos los fallos son `Failed: T11 RED: summary consumer app.summaries.worker is absent`. No errores de setup/colección, skips ni servicios inaccesibles. El fallo se produce después de crear y poblar la base real.

Casos preparados:

1. Snapshot de instrucciones y linaje sobrevive edición de plantilla y cambio del predeterminado; `running` durable antes de generar, `succeeded` junto con resultado y claim; no modifica estado de reunión.
2. Evento ya confirmado no regenera ni modifica resultado.
3. Entrega concurrente produce un solo resultado confirmado.
4. Error reintentable se propaga; conserva `running`, sin claim/resultado; reintento posterior puede completar.
5. Trigger PostgreSQL rechaza el write `succeeded`: claim, resultado y éxito deben revertirse juntos; quitado el trigger, reintento completa.
6. Consumidor terminal registrado en startup marca solo el evento agotado como `failed`, tolera redelivery y conserva el éxito anterior.

Se captura `start_worker(queue, session_factory)` y sus handlers mediante un doble de `JobQueue`. Como la interfaz actual solo ofrece `subscribe` y no callback de agotamiento, el test captura un consumidor terminal adicional sin imponer el nombre del topic DLQ. El enganche de factory usa el símbolo `create_summarization_engine` del módulo worker, igual al patrón del worker de transcripción. El doble de motor entrega `topic` y `key_points`; no invoca Ollama. T12 deberá verificar además el wiring operativo del dead-letter en el broker real: estos dobles no certifican transporte, retries del broker ni disponibilidad de proveedor.

## Controles estáticos

- `uv tool run --offline ruff check backend/tests/summaries/test_worker.py`: PASS.
- `uv tool run --offline ruff format --check backend/tests/summaries/test_worker.py`: PASS.
- Desde backend: `uv tool run --offline --python /opt/homebrew/bin/python3 --with pydantic mypy --python-executable /opt/homebrew/bin/python3 tests/summaries/test_worker.py --follow-imports=silent`: **Success, 1 source file**. Usa configuración estricta del proyecto; no afirma mypy global limpio.
- `git diff --check`: PASS.

El primer launcher cacheado de mypy Python3.13 falló por firma de un módulo compilado. Se resolvió usando el intérprete Python3.14 instalado y paquete cacheado compatible, sin modificar firmas ni permisos; se agregó pydantic al entorno aislado de herramienta para cargar el plugin configurado.

## Limpieza y límites

La consulta a `pg_namespace` tras las seis pruebas devolvió **0 esquemas `t11_*`**. `docker rm -fv sauri-t11-pg-96549` eliminó contenedor y volumen anónimo; comprobación por etiqueta `sauri.qa=t11-96549` no devolvió contenedores. No se tocaron los recursos T10 de Nahuel ni servicios personales.

Esto certifica la etapa RED, no funcionalidad disponible, generación real, exactitud, integración ni aceptación. T12 depende de T10 además de este RED; debe conservar el commit de pruebas y entregar sus aserciones GREEN sin debilitarlas.
