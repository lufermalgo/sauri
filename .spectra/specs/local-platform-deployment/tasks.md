# Plan de Implementación — Despliegue local integrado de Sauri

## Estado y autoridad

Requisitos aprobados por merge #819 (`392a958`); diseño aprobado por merge #820 (`9632bcd0d2c975b323875bf3ee69cebd452e93fb`, 12-11-2026 23:27 UTC). Issue padre #818; APX `task_9e74a2d278d648ad`. Plan aprobado por Fer mediante merge #825 (`3161afaaf991679abc1a77366ad4ebbe7e4ec5b3`, 12-11-2026 23:47 UTC). Ningún checkbox acredita integración ni aceptación de Fer. Los merges permanecen reservados a Fer.

Alcance: servir el portal construido con el núcleo Docker, conservar autenticación/API/S3 existentes, motores nativos y validación aislada con limpieza segura. No rediseñar UI, crear identidad nueva, modificar políticas, migrar datos, publicar en Internet ni descargar modelos. No ejecutar sobre el entorno personal del dueño.

## Resumen de Fases

| Fase | Descripción | Tareas | Dependencias |
|------|-------------|--------|--------------|
| 1 | Portal construido y proxy real | 1.1–1.3 | Aprobación de este plan |
| 2 | Arranque verificable sin tocar datos | 2.1–2.3 | 1.3 para integración |
| 3 | Herramienta QA con propiedad y limpieza | 3.1–3.3 | Independiente de 1–2 hasta prueba real |
| 4 | Conexiones, seguridad y navegador reales | 4.1–4.4 | 2.3, 3.3 |
| 5 | Documentación, integración y límites | 5.1–5.3 | Evidencias de 4 |

16 tareas: 9 de prueba/validación (1.1, 1.3, 2.1, 2.3, 3.1, 3.3, 4.1, 4.2, 4.3), 4 de implementación/documentación (1.2, 2.2, 3.2, 5.1), 3 de evaluación/entrega (4.4, 5.2, 5.3). Pruebas primero; RED no se integra como entrega terminada.

**Unidades de entrega:** U1 = fase 1; U2 = fase 2; U3 = fase 3; U4 = fase 4 + documentación operativa 5.1; U5 = 5.2–5.3. Crear o reutilizar issues vinculados a #818 al activar cada unidad y registrar aquí issue/commit/PR; no generar tarjetas duplicadas para cada control. Cada unidad usa rama/worktree aislados. U1/U2 se serializan en su arranque inicial; U3 puede delegarse a Nahuel cuando termine su encargo vigente: solo `_tools/validate-local-platform.py` y `_tools/test_validate_local_platform.py`, contrato de inventario del diseño, sin editar Compose ni arranque. Ansel conserva revisión, arquitectura, pruebas integradas y comunicación. Ninguna asignación de este plan se considera iniciada por redactarlo.

## Fase 1: Portal construido y proxy real

### Tarea 1.1: RED del contrato estático y proxy (P1, P3, P5)

- [x] RED observado por ausencia de `.dockerignore` y entrega Docker. Harness real en `_tools/test_portal_container.py`, #827; API doble explícita, no integración del backend.

**Archivo:** `_tools/test_portal_container.py` (crear).
**Acción:** Crear pruebas con librería estándar contra una imagen candidata y API de prueba explícita: `/` y ruta SPA válida entregan HTML construido, assets reales responden y asset inexistente devuelve 404; `/portal-health` responde local y `/api-health` reenvía `/health`; `/api/` conserva ruta/query/Authorization y códigos/cuerpos 401/403/404/422/500 sin fallback HTML 200. API no disponible produce 502/504, no éxito. Verificar configuración de buffering, límite de cuerpo y tiempos mediante `nginx -T`. Añadir inspección de runtime/dist y contexto excluido con una cadena privada sintética, nunca secretos reales. Dobles de API solo prueban el proxy y se etiquetan como tales.
**Criterio de Completado:** `python3 -m unittest _tools/test_portal_container.py` ejecuta casos positivos/negativos y falla por ausencia de imagen/configuración funcional antes de 1.2; guardar comando, resultado y causa RED sin omitir pruebas por defecto. Recursos de prueba inventariados y eliminados al finalizar, incluso con fallo.
**Dependencias:** Aprobación de este plan.

### Tarea 1.2: Construir y servir portal sin Vite (R1.1–1.3, R2.1–2.4)

- [x] Implementado y validado en rama #827: Node/Nginx con digests fijados, contexto default-deny, Compose loopback, proxy y health diferenciados. Cuatro pruebas Docker GREEN, `nginx -t/-T` e inspección de contexto/runtime. No integrado ni aceptado como producto.

**Archivo:** `frontend/Dockerfile`, `frontend/nginx.conf`, `.dockerignore`, `docker-compose.yml`.
**Acción:** Imagen multietapa Node 22 Alpine → Nginx stable Alpine; resolver digests reales y fijarlos antes de publicación. Usar contexto raíz, manifiestos de workspaces/lock, `npm ci`, fuentes frontend/shared-types y `VITE_API_BASE_URL='' npm run build --workspace frontend`; copiar solo dist/configuración al runtime. Excluir `.git`, `.worktrees`, `.apc`, `.env*`, node_modules, cachés, medios y QA del contexto sin excluir fuentes/manifiestos necesarios. Implementar `/portal-health`, `/api-health`, `/api/` sin URI final en proxy, `/assets/` con 404 y SPA con index no-cache. Mantener Authorization, HTTP/1.1, sin caché API ni directory listing, `client_max_body_size 0`, `proxy_request_buffering off`, connect 5s/read-send 3600s. Agregar servicio portal en sauri-net, depends_on api, publicación `127.0.0.1:${PORTAL_PORT:-5173}:80`, healthcheck estático cada 10s/timeout 3s/6 reintentos. No alterar servicios/volúmenes existentes ni `frontend/src/api.ts`; S3 conserva enlace firmado directo.
**Criterio de Completado:** Construcción real de imagen, `nginx -t` y pruebas 1.1 GREEN; runtime no contiene fuentes privadas/secretos/cachés. Compose incluye portal sin motores ni nuevos montajes persistentes.
**Dependencias:** 1.1.

### Tarea 1.3: Verificar build, tipos y límites de imagen (P1–P3, P5)

- [x] `npm ci`, frontend typecheck, 92 tests y build PASS; Compose config PASS con valores sintéticos. Suite Docker final: 4/4 PASS, limpieza verificada, 0 contenedores/volúmenes/cache al terminar (imagen base compartida del builder conservada). Navegador APX verificó login construido y recarga SPA; no autenticación backend ni reproducción. Avisos npm heredados: 10 en herramientas, 0 con `npm audit --omit=dev`. #827, pendiente publicación/integración.

**Archivo:** `_tools/test_portal_container.py`, `frontend/package.json`, `package-lock.json` (lectura de comandos/lock; no cambio de dependencias previsto).
**Acción:** Ejecutar `npm ci`, `npm run typecheck --workspace frontend`, `npm run test --workspace frontend`, `npm run build --workspace frontend`, pruebas 1.1 e inspección del build/contexto. Guardar digest, commit, comandos, diff y resultados sin variables privadas. Revisar composición efectiva para confirmar URLs nativas y controles existentes, no inferir GPU del nombre del servicio.
**Criterio de Completado:** Todos los controles pertinentes pasan contra el mismo candidato; P2/P5 tienen evidencia explícita, no solo build exitoso. Publicar U1 con issue y PR, sin merge automático.
**Dependencias:** 1.2.

## Fase 2: Arranque verificable sin tocar datos

### Tarea 2.1: RED de arranque y disponibilidad diferenciada (P2, P6)

- [ ] Pendiente.

**Archivo:** `_tools/test_compose_bringup.py`.
**Acción:** Extender harness existente para exigir portal en último paso, bucket y migraciones antes del arranque final, selección de COMPOSE_PROJECT_NAME/COMPOSE_FILE preservada incluso antes de stop, espera HTTP acotada a 60s y fallo no cero por bucket/migración/HTTP. Portal positivo con API caída no da éxito; mensaje final no acredita motores/inferencia. Ningún escenario borra datos, ejecuta prune o make clean.
**Criterio de Completado:** `python3 -m unittest _tools/test_compose_bringup.py` reproduce RED por comportamiento faltante y conserva los casos existentes. Los dobles de Docker no se reportan como integración real.
**Dependencias:** Aprobación de este plan; no requiere editar archivos de U1.

### Tarea 2.2: Integrar portal y espera HTTP al arranque (R1.1, R3.1–3.3)

- [ ] Pendiente.

**Archivo:** `_tools/compose-bringup.sh`.
**Acción:** Conservar credenciales → stop api/worker del proyecto seleccionado → infraestructura → bucket → migraciones → api/worker/portal. Añadir espera hasta 60s de `/portal-health` y `/api-health` usando puerto efectivo, fallar identificando etapa sin exponer secretos. Mantener errores/selección Compose y protecciones de credenciales. Mensaje de éxito limitado a portal/núcleo, inferencia por verificar aparte. No iniciar/parar motores ni recrear volúmenes.
**Criterio de Completado:** Tests 2.1 GREEN; `bash -n _tools/compose-bringup.sh` pasa; cada error impide pasos posteriores y no emite éxito.
**Dependencias:** 2.1; 1.3 antes de probar arranque real.

### Tarea 2.3: Verificar secuencia y configuración efectiva (P2, P6)

- [ ] Pendiente.

**Archivo:** `_tools/test_compose_bringup.py`, `docker-compose.yml` (verificación).
**Acción:** Ejecutar suite completa del script y `docker compose ... config --quiet` con valores sintéticos. Comprobar preservación de servicios, volúmenes, URLs/contratos de motores y ausencia de migraciones nuevas. Revisar diff y publicar U2 vinculado a U1/#818.
**Criterio de Completado:** Suite y configuración pasan sin arrancar entorno de Fer ni imprimir secretos. Disponibilidad de PostgreSQL/S3/cola/motores continúa pendiente de controles reales 4.x, sin marcado implícito.
**Dependencias:** 2.2, 1.3.

## Fase 3: Herramienta QA con propiedad y limpieza

### Tarea 3.1: RED de identidad, aislamiento y limpieza (P7–P8)

- [ ] Pendiente.

**Archivo:** `_tools/test_validate_local_platform.py` (crear).
**Acción:** Probar modos create/check/cleanup, runId de 12 hex y proyecto exacto, inventario schemaVersion 1, puertos libres y fallos por conflicto. Generar con unittest.subTest al menos 100 combinaciones de ID/etiqueta/proyecto: eliminar solo coincidencia de inventario Y etiqueta Compose; faltar inventario, etiqueta ajena o ID divergente rechazan sin borrado. Probar cleanup repetido, cancelación, fallo parcial durante create, secretos ausentes, override sin volúmenes externos/nombres fijos ni mounts del dueño. No admitir prune ni limpieza por prefijo. Usar dobles para estos límites, no para acreditar Docker.
**Criterio de Completado:** `python3 -m unittest _tools/test_validate_local_platform.py` ejecuta matrices y falla antes de implementación por comportamiento faltante, no por errores arbitrarios del harness.
**Dependencias:** Aprobación de este plan.

### Tarea 3.2: Implementar inventario QA y eliminación segura (R4.1–4.3)

- [ ] Pendiente.

**Archivo:** `_tools/validate-local-platform.py` (crear).
**Acción:** Librería estándar Python, modos create/check/cleanup sin proyecto principal por defecto. Crear runId aleatorio y carpeta temporal externa al repo con override, secretos sintéticos e inventario del diseño (commit, fecha, composeFiles, IDs, puertos, checks con capa/resultado/evidencePath). Reemplazar publicaciones, no sumarlas: portal 15173/API 18000/PG 15432/S3 19000/consola 19001/AMQP 15673/admin 15674, todas loopback; si ocupadas seleccionar bloque libre y registrarlo sin detener al ocupante. Selección `-p` y archivos explícitos en cada comando; verificar config antes de crear. Worker monta solo secretos sintéticos de esa ejecución. Inventariar recursos antes/después y también al fallar parcialmente. Registrar espacio antes/después, no tokens ni URLs firmadas completas. Cleanup verifica inventario y etiqueta exactos por ID antes de borrar contenedores/redes/volúmenes temporales; rechaza ambigüedad, es idempotente y no elimina imágenes compartidas/cache. Ejecutar cleanup en cierre normal, error e interrupción y permitir repetición explícita desde inventario persistido.
**Criterio de Completado:** 3.1 GREEN, ningún comando global ni borrado por nombre/prefijo. Config efectiva solo recursos propios y puertos registrados. Fallo deja diagnóstico suficiente para limpieza segura posterior, no una afirmación de limpieza ficticia.
**Dependencias:** 3.1.

### Tarea 3.3: Validar ciclo real y recursos residuales (P7–P8)

- [ ] Pendiente.

**Archivo:** `_tools/test_validate_local_platform.py`, `_tools/validate-local-platform.py`.
**Acción:** Ejecutar suite; ciclo real create/check/cleanup y repetir cleanup. Inventariar recursos ajenos antes y después sin cambiarlos; comprobar cero recursos QA residuales. Ensayar un fallo controlado de validación y verificar eliminación posterior. Comparar métricas Docker sin atribuir espacio global exclusivamente a Sauri.
**Criterio de Completado:** P7–P8 demostradas con IDs/etiquetas reales, sin residuos temporales incluso en fallo probado; suite pasa y PR U3 incluye evidencia. No arrancar motores ni entorno personal del dueño.
**Dependencias:** 3.2, 2.3 para ciclo de plataforma completo.

## Fase 4: Conexiones, seguridad y navegador reales

### Tarea 4.1: Comprobar núcleo y proxy con autenticación activa (P3, P6, P9)

- [ ] Pendiente.

**Archivo:** `_tools/validate-local-platform.py` (modo check), `backend/tests/infra/test_object_store_browser_endpoint.py` (reusar).
**Acción:** En proyecto QA generar dos identidades sintéticas y AUTH_DISABLED=false. Probar escritura/lectura PostgreSQL, objeto propio S3 y publicación/recepción/ack en cola aislada. Comparar API directa/proxy por ruta/query/identidad/código/cuerpo semántico, incluidos errores y usuario B/anónimo sin acceso a reunión de A. Reusar test de endpoint público de objetos. Mantener contratos de credenciales; no imprimir tokens. Cleanup siempre al cerrar ejecución, aunque un control falle.
**Criterio de Completado:** Comandos/resultados por capa y denegaciones registradas; `/health` no sustituye DB/S3/cola. Ninguna respuesta fallida se vuelve HTML 200 ni se comparte autorización entre usuarios.
**Dependencias:** 2.3, 3.3.

### Tarea 4.2: Comprobar medio real, firma y rangos (P4, P9)

- [ ] Pendiente.

**Archivo:** `backend/tests/meetings/test_playback_storage_integration.py` (reusar), `_tools/validate-local-platform.py` (check).
**Acción:** Crear/cargar medio audiovisual sintético por API real; usar fixtures explícitos de playback cuando sean necesarios sin acreditar procesamiento. Ejecutar test con S3 real y sus variables documentadas. Probar varios rangos válidos/iniciales/intermedios/finales: 206, bytes y Content-Range exactos, CORS del origen portal, firma inválida denegada. API B y anónima no obtienen manifiesto/medios de A; un enlace firmado válido conserva su política de capacidad temporal. No reescribir URL tras firmar ni abrir bucket/CORS global para pasar.
**Criterio de Completado:** Test real y matriz HTTP pasan; registrar valores no sensibles de origen/endpoint y estados. Incompatibilidad de política se informa antes de cambiarla. Si S3 no está disponible se corrige dentro de alcance o se marca fallo concreto, nunca skip presentado como éxito.
**Dependencias:** 4.1.

### Tarea 4.3: Recorrer portal Docker en navegador real (P1, P3–P4, P9)

- [ ] Pendiente.

**Archivo:** `_tools/validate-local-platform.py` (referencias a evidencias); capturas/logs en carpeta temporal de la ejecución, no en repositorio.
**Acción:** Con navegador permitido/Playwright abrir origen Docker, iniciar sesión existente, consultar biblioteca y detalle autorizado, recargar ruta y reproducir medio sintético. Comprobar errores API/medio ausente y separación A/B/anónimo. Guardar captura y errores de consola/red sin tokens/URLs privadas. No interceptar API/medios para fabricar éxito ni modificar UI para facilitar QA. La captura Chrome pertenece a chrome-recording-completion y no se acredita con este recorrido.
**Criterio de Completado:** Recorrido observable sobre portal construido, captura revisada y reproducción real; errores relevantes corregidos y recorrido repetido. Sin navegador funcional queda explícitamente no verificado, no entrega visual completa. Retirar recursos al finalizar.
**Dependencias:** 4.2.

### Tarea 4.4: Separar conectividad de motores e inferencia (P2, P6, P10)

- [ ] Pendiente.

**Archivo:** `_tools/validate-local-platform.py` (checks engines/inference), `docs/LOCAL_DEPLOYMENT.md` (matriz de resultados).
**Acción:** Comprobar desde worker acceso a motores nativos existentes si es posible sin alterar sus procesos; conservar HTTP/credenciales. Solo con entorno/modelos/credenciales disponibles y alcance autorizado, enviar medio sintético y observar transcripción, diarización y dispositivo realmente usado. No descargar modelos, gastar en proveedor cloud ni sustituir motores por dobles. Si no es posible, registrar causa exacta e intervención externa necesaria sin bloquear lectura de reuniones anteriores validada; inferencia permanece no verificada.
**Criterio de Completado:** Cada motor e inferencia tienen resultado y evidencia independientes; ninguna comprobación de proceso/health/build demuestra GPU ni transcripción. Un resultado no verificado no cierra validación de procesamiento de la tarea padre.
**Dependencias:** 4.1; no depende de que los motores estén activos para registrar el bloqueo real.

## Fase 5: Documentación, integración y límites

### Tarea 5.1: Documentar operación y recuperación sin borrar datos (P6, P10)

- [ ] Pendiente.

**Archivo:** `docs/LOCAL_DEPLOYMENT.md` (crear), `README.md`, `docs/ARCHITECTURE.md`.
**Acción:** Documentar Docker/Node de construcción, variables privadas sin valores, URL local, make up, proxy/API/S3, motores nativos, salud diferenciada, puertos/conflictos, procedimientos QA e inventario/cleanup, recuperación sin borrar volúmenes. Advertir que make clean elimina datos y no es parte del arranque. Contrastar estado actual de #703 y de esta entrega, no confundir spec con implementación ni fixtures con inferencia. Registrar comandos reales y límites de validación, sin secretos.
**Criterio de Completado:** Guía coincide con candidato y resultados 4.x; cada afirmación clasifica configuración/automatizadas/recorrido/inferencia/aceptación por separado. Revisar enlaces y comandos contra código, no solo redacción.
**Dependencias:** 4.1–4.4 (incluye sus bloqueos explícitos).

### Tarea 5.2: Revisar candidato y publicar entrega trazable (P10)

- [ ] Pendiente.

**Archivo:** `.spectra/specs/local-platform-deployment/tasks.md`, `docs/LOCAL_DEPLOYMENT.md`; issues/APX/PRs vinculados.
**Acción:** Revisar diff/seguridad y repetir validaciones pertinentes del candidato exacto, incluyendo frontend typecheck y pruebas/imagen/arranque/cleanup. Guardar commits, issues, PRs, comandos y resultados, y asociarlos a U1–U4 y esta spec. No bajar controles ni introducir cambios ajenos. Solicitar merge concreto a Fer con funcionalidad disponible, evidencia y límites; no cerrar como integrado por PR abierto.
**Criterio de Completado:** Candidato integrable y sin fallos relevantes pendientes dentro del alcance; matriz P1–P10 y requisitos cubierta o bloqueo externo explícito. PRs publicados, acción de Fer comunicada directamente; aceptación de producto separada.
**Dependencias:** 1.3, 2.3, 3.3, 4.1–4.4, 5.1.

### Tarea 5.3: Verificar merge y despliegue integrado (R5.1–5.2)

- [ ] Pendiente.

**Archivo:** `.spectra/specs/local-platform-deployment/tasks.md`, `docs/LOCAL_DEPLOYMENT.md`; tarea APX padre e issue #818.
**Acción:** Tras merges reservados a Fer, verificar SHA remoto integrado y repetir controles y recorrido pertinentes en QA aislado del candidato integrado. Ejecutar cleanup y comprobar ausencia de residuos. Comunicar qué puede hacer el usuario, qué pasó, qué no se verificó y aceptación pendiente. No migrar ni iniciar entorno personal de Fer sin coordinación y respaldo acordados. Sincronizar estados sin cerrar captura/inferencia u otras specs por asociación.
**Criterio de Completado:** Merge verificado, integración probada con captura y evidencias, limpieza comprobada. Cerrar esta entrega solo cuando sus criterios se cumplan; conservar abierta cualquier validación funcional o intervención externa pendiente. Ningún cierre documental sustituye aceptación de Fer.
**Dependencias:** 5.2 y merges de U1–U4.

## Cobertura y seguimiento

| Propiedad | Pruebas / evaluación |
|-----------|---------------------|
| P1 | 1.1, 1.3, 4.3 |
| P2 | 1.3, 2.1, 2.3, 4.4 |
| P3 | 1.1, 4.1, 4.3 |
| P4 | 4.2, 4.3 |
| P5 | 1.1, 1.3 |
| P6 | 2.1, 2.3, 4.1, 4.4, 5.1 |
| P7 | 3.1, 3.3 |
| P8 | 3.1, 3.3, 5.3 |
| P9 | 4.1–4.3 |
| P10 | 4.4, 5.1–5.3 |

| Unidad | Issue | PR / commit | Estado real |
|--------|-------|-------------|-------------|
| Plan | #818 | PR #825, merge `3161afa` | Aprobado e integrado |
| U1 | #827 | `feat/local-platform-portal` | Implementación y validación; no integrado |
| U2 | Al activar | — | No iniciada |
| U3 | Al activar | — | No iniciada |
| U4 | Al activar | — | No iniciada |
| U5 | #818 / APX padre | — | No iniciada |
