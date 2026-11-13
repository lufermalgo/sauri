# Validación local obligatoria antes de merge

## Decisión vigente

Fer aprobó el 13/11/2026 17:55 **desactivar GitHub Actions y reemplazarlo por validación local obligatoria**, no eliminar controles. Ansel aplicó la API de permisos; GET `repos/lufermalgo/sauri/actions/permissions` confirmó `enabled=false` y Nahuel lo volvió a verificar. No pagar GitHub, aumentar límites, contratar servicios ni instalar runners permanentes. Los checks históricos fallidos siguen fallidos; no son un bloqueo de facturación pendiente ni se declaran verdes.

Antes de cada merge, Ansel verifica pruebas, tipos, compilación y seguridad pertinentes sobre **el SHA exacto a integrar**, conserva comandos/resultados/entorno y baseline de fallos globales. Un SHA que agrega solo documentación no cambia el código probado, pero esa relación debe comprobarse con diff; no extrapolar pruebas a cambios funcionales posteriores. No usar `--no-verify`, deshabilitar hooks, inventar checks aprobados ni presentar cero tests descubiertos como cobertura.

## Inventario de `.github/workflows/ci.yml`

La clasificación blocking/non-blocking de la workflow se conserva como referencia histórica; no autoriza ocultar nuevas regresiones. Desactivar Actions no vuelve aprobadas sus suites.

| Control definido | Equivalente local / requisito | Evidencia en candidato inicial #912 |
|---|---|---|
| Checkout del candidato | Worktree aislado en rama, `git rev-parse HEAD`, diff y estado; preservar cambios ajenos | Código `e7e70a6`, documentación posterior sin código. Diff/backend comparado con main y QA. |
| Entorno backend Python3.11 + instalar `backend[dev]` | Entorno del proyecto con dependencias verificadas; registrar versión y cualquier diferencia del runner | Se usó `.venv` del backend con Python3.13; no se atribuye ejecución a Python3.11. Para inferencia se usa venv nativo instalado Python3.11.12. |
| Contratos APX single-handoff (`python -m unittest discover -s .apc/routines -p 'test_*.py'`) | Ejecutar en el candidato, informar cantidad descubierta y fallos | **27 PASS** en revisión de Ansel sobre `a279aea`, sesión de revisión APX de esta tarea. No se alteraron instrucciones/APX como parte de #912. |
| Ruff full (deuda #228, non-blocking en workflow) | `cd backend && ruff check .`; comparar diagnósticos con baseline main | Ejecutado: **3 errores** en main y candidato, sin nuevos. Focal de archivos cambiados **PASS**. |
| Mypy full (deuda #228, non-blocking) | `cd backend && mypy .`; comparar diagnósticos exactos | Ejecutado: **82 errores / 8 archivos** en ambos, 0 nuevos/0 eliminados. Focal **PASS, 25 archivos**. |
| S3 compatible desechable + bucket/CORS y playback Range (blocking #505) | Recursos propios, bucket exclusivo, fixture sintética; ejecutar `pytest tests/meetings/test_playback_storage_integration.py::test_signed_playback_source_supports_range_and_frontend_cors -q`; limpiar y comprobar | **Pendiente**. Se comprobó la misma falta de `OBJECT_STORE_ENDPOINT` en baseline y candidato; no se declara PASS ni se usa storage del dueño. La regresión ampliada inicial excluyó solo ese contrato. |
| Backend completo `pytest --continue-on-collection-errors` (non-blocking por deuda) | Ejecutar full y baseline, sin ocultar errores de colección ni reducir pruebas para cerrar | **Pendiente** full en la reconciliación final. Suites pertinentes ejecutadas: **408 PASS** + **15 integración PASS**, sin skips, PG16/RabbitMQ reales propios eliminados. |
| Node20 + `npm ci` | Instalación aislada de dependencias bloqueadas por lockfile; registrar versión, no alterar `node_modules` ajeno | **Pendiente** si requiere preparar entorno final. #912 no cambia TS/package-lock. |
| Frontend Vitest (non-blocking deuda #304) | `npm run test --workspace=sauri-frontend`; preservar baseline explícito | **Pendiente**, no se presenta como verde por no tocar UI. |
| Frontend typecheck (non-blocking deuda #304/#189) | `npm run typecheck --workspace=sauri-frontend` | **Pendiente**, no se modifica TS en #912 inicial. Si se transporta QA frontend, es obligatorio antes de declarar listo. |
| Frontend build (blocking) | `npm run build --workspace=sauri-frontend` | **Pendiente** en la validación local final. |
| Extensión Vitest (blocking) | `npm run test --workspace=sauri-extension` | **Pendiente** en la validación local final; no se cambia extensión. |
| Extensión typecheck (blocking) | `npm run typecheck --workspace=sauri-extension` | **Pendiente** en la validación local final. |
| Extensión build (blocking) | `npm run build --workspace=sauri-extension` | **Pendiente** en la validación local final. |
| Seguridad documentada en workflow (`npm audit --omit=dev`) y revisión pertinente al diff | Audit de dependencias sin instalación de servicios, revisión de secretos/auth/privacidad/rutas/confirmaciones; no confundir comentario histórico con audit actual | Revisión acotada de código: eventos Ollama allowlisted y adversariales, auth owner-scoped, firma de topics y confirmaciones cubiertas por tests. **Audit actual y cierre completo pendientes**. |

Los jobs cloud no se invocan para completar esta tabla. La prioridad actual es el recorrido real exigido por Fer 18:02; compilación/suites amplias no deben competir con esa inferencia y alterar su medición. Al terminar o detenerse el recorrido, se completan validaciones pertinentes de este inventario y se registra el SHA final. **#912 aún no se declara una entrega integral de rendimiento ni una sustitución del stack QA.** Ver `qa-preservation-matrix.md` para todas las reparaciones pendientes de reconciliar.
