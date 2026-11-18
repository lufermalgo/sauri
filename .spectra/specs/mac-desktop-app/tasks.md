# Plan de Implementación — Sauri como app de escritorio para Mac con chip M

## Estado y contrato

El trabajo se ejecuta por unidades de entrega, de U1 a U12. Cada unidad tiene su issue (se crea al iniciarla y enlaza a #1199), su rama y su worktree desde `origin/main` en `.worktrees/`. La implementa Codex, con el protocolo de `~/Proyectos/sauri-orchestration/`, o un subagente; Claude se reserva U6, U11 y U12. Después, Claude revisa el diff, ejecuta las pruebas por su cuenta e integra.

Una unidad se cierra solo cuando se cumple todo esto:
- Pruebas pertinentes en verde.
- `ruff` y `mypy` sin diagnósticos nuevos en lo tocado.
- `npm run typecheck`, `npm run test` y `npm run i18n:check` si toca TypeScript.
- `python3 scripts/dev/check_english_only.py` sobre lo staged.
- Diff revisado y PR integrado.

Documentación terminada no es implementación ni aceptación. La aceptación es del dueño, después de U12.

**Reglas transversales**
- El proyecto Docker `sauri` y sus volúmenes no se usan ni se tocan hasta U11. Las pruebas con PostgreSQL usan instancias desechables: `sauri_qa_*` en Docker hasta que U6 entregue `scripts/tests/pg-disposable.sh`, y desde entonces ese script.
- Nada se despliega ni se reinicia en el Mac del dueño mientras haya reuniones procesándose (`scripts/platform/deploy-guard.sh`).
- Los textos de usuario van solo en `frontend/src/locales/` y `extension/src/locales/`, en español y en inglés. Los identificadores van en inglés.
- Ningún archivo, registro, evidencia ni commit contiene claves, audio ni transcripciones.
- Publicar en el Lugar_de_Descarga o en Chrome Web Store es contenido público: solo con el OK expreso del dueño en cada ocasión.

## Resumen de Fases

| Fase | Unidades | Descripción | Dependencias |
|------|----------|-------------|--------------|
| 1 | U1, U2, U3, U4, U6 | Núcleo sin Docker (cola, almacén, portal), Modo_Local con protección, runtime empaquetable | Ninguna entre sí. U3 y U4 tocan `app/main.py`: se integra U3 primero |
| 2 | U5, U7 | Extensión sin login y emparejada; app Electron con supervisor y configuración fase A | U5 depende del contrato de U4; U7 depende de U6 |
| 3 | U8, U9, U10, U11 | Bienvenida y almacenamiento; empaquetado, actualizaciones y desinstalación; landing y tienda; traslado de datos del dueño | U8: U4 y U7. U9: U7. U10: decisión D13 del dueño. U11: U1, U2 y U7 |
| 4 | U12 | Verificación final, retiro de Docker, RabbitMQ y S3, documentación | Todas |

---

## Fase 1

### Unidad U1: Cola sobre PostgreSQL (Codex, `deep`)

#### Tarea U1.1: Tabla y cola
**Archivo:** `backend/alembic/versions/030_job_messages.py`, `backend/app/infra/models.py`, `backend/app/infra/queue_postgres.py`, `backend/app/infra/queue.py`
**Acción:**
- Crear la tabla `job_messages` (diseño, «Modelos de Datos»).
- Implementar `PostgresJobQueue` con el ciclo de consumo del diseño (componente 2), con los mismos valores por defecto de reintento y espera que `queue_rabbitmq.py:32-48`.
- Despertar a los consumidores con `LISTEN/NOTIFY` sobre una conexión dedicada de `asyncpg`, con sondeo cada 2 s.
- Hacer que la fábrica elija según `QUEUE_KIND` (`rabbitmq` por defecto hasta U12).

**Criterio de Completado:**
- `uv run --extra dev pytest tests/infra/test_queue_postgres.py` en verde sobre PostgreSQL desechable, con las Propiedades 1 y 2 en Hypothesis: N consumidores, caídas simuladas y `DeferDelivery`.
- La prueba de conformidad existente (`tests/infra/test_adaptadores_conformidad_property.py`) pasa también con la implementación nueva.

**Dependencias:** Ninguna

#### Tarea U1.2: Worker y barredor con la cola nueva
**Archivo:** `backend/app/worker.py`, `backend/app/infra/orphan_sweeper.py`, pruebas de cada uno
**Acción:**
- Con `QUEUE_KIND=postgres`, el worker se suscribe a los cinco temas.
- `pending_count` alimenta al barredor de huérfanos.
- La salida ordenada respeta la gracia de 540 s.
- El tema `join`, que no tiene consumidor (`meetings/service.py:374,399`), se documenta en el PR con el número de filas que acumula. No se cambia su publicación en esta unidad.

**Criterio de Completado:** `test_pipeline_e2e.py`, en su variante parametrizada con `QUEUE_KIND=postgres` y sobre servicios desechables, procesa una reunión de punta a punta con motores simulados.
**Dependencias:** U1.1

### Unidad U2: Almacén en carpetas y ruta de medios (Codex, `deep`)

#### Tarea U2.1: `FilesystemObjectStore`
**Archivo:** `backend/app/infra/object_store_fs.py`, `backend/app/infra/object_store.py`, `backend/app/infra/ensure_bucket.py`, `backend/tests/infra/test_object_store_fs.py`
**Acción:**
- Implementar el componente 3 del diseño, con escritura atómica y confinamiento de rutas.
- Hacer que la fábrica elija según `OBJECT_STORE_KIND`.
- Con `filesystem`, `ensure_bucket` crea la carpeta raíz.

**Criterio de Completado:** Propiedades 3 y 4 en Hypothesis, incluidos enlaces simbólicos que salen de la raíz y escrituras interrumpidas.
**Dependencias:** Ninguna

#### Tarea U2.2: Tokens y `GET /api/v1/media/{token}`
**Archivo:** `backend/app/media/router.py`, `backend/app/media/tokens.py`, `backend/app/main.py` (solo el `include_router`), `backend/tests/media/`
**Acción:**
- Crear el token firmado con `recording_capability_key`.
- Implementar la ruta con `FileResponse` y `content_disposition_type`.
- Hacer que `temporary_read_url` y `temporary_download_url` del almacén nuevo devuelvan esta ruta.

**Criterio de Completado:**
- Propiedad 5: rangos aleatorios devuelven `206` con bytes exactos.
- Un token vencido, alterado o con la clave de otra reunión devuelve `403`.
- Reproducir y descargar desde el portal funciona en el navegador integrado con el almacén nuevo.

**Dependencias:** U2.1

#### Tarea U2.3: Lectura local en motores y miniaturas
**Archivo:** `backend/asr-engine/native_main.py`, `backend/diar-engine/native_main.py`, `backend/app/thumbnails/service.py`, `backend/engine-common/sauri_engine_common/local_media.py`, sus pruebas
**Acción:**
- Con `SAURI_RECORDINGS_DIR` definida, leer `audio_ref` como archivo local, con la misma validación de ruta de la Propiedad 4 y sin boto3.
- Las miniaturas pasan la ruta local a `ffmpeg`.

**Criterio de Completado:** las pruebas de los motores pasan en ambos modos. Una ruta fuera de la raíz se rechaza con código de error y sin abrir el archivo.
**Dependencias:** U2.1

### Unidad U3: Portal servido por la API (Codex, `standard`)

#### Tarea U3.1: Estáticos, SPA y cabeceras
**Archivo:** `backend/app/portal/static.py`, `backend/app/portal/csp.py`, `backend/app/main.py`, `backend/tests/portal/`
**Acción:**
- Implementar el componente 4 del diseño.
- Calcular la CSP al iniciar con la misma regla de hash que `scripts/platform/inline-script-hash.mjs`, y añadir una prueba que compare ambos resultados sobre el `index.html` construido.
- Reproducir las cabeceras de `frontend/security-headers.conf` (HSTS solo si es HTTPS, así que aquí nunca).

**Criterio de Completado:**
- Con `SAURI_PORTAL_DIR` apuntando al build de `frontend` (`VITE_API_BASE_URL=''`), el portal carga en `http://localhost:8000/`.
- Recargar `/meetings/<id>` y `/settings/motores` sirve `index.html`.
- `/assets/*` sale con la caché inmutable.
- La consola no muestra errores de CSP.
- Recorrido en el navegador integrado con captura.

**Dependencias:** Ninguna

### Unidad U4: Modo_Local y protección (Codex, `deep+`; revisión de seguridad de Claude)

#### Tarea U4.1: Usuario_Local y modo de autenticación
**Archivo:** `backend/app/auth/dependencies.py`, `backend/app/auth/local.py`, `backend/app/auth/router.py`, `backend/app/local/bootstrap.py`, `backend/app/local/inflight.py`, `backend/app/local/router.py`, pruebas
**Acción:**
- Con `SAURI_AUTH_MODE=local`, `get_current_user` devuelve la fila de `SAURI_LOCAL_USER_ID`, y la API no exige `JWT_SECRET` al iniciar.
- Crear `bootstrap --name`, que funciona como `seed_admin` pero sin contraseña.
- Crear `GET /api/v1/local/status`, con la consulta de `scripts/platform/pipeline_admission.py` trasladada, y `POST /api/v1/local/pair`.
- El modo `password` no cambia.

**Criterio de Completado:**
- Propiedad 7 recorriendo `app.routes`.
- Las pruebas existentes de autenticación siguen en verde en modo `password`.
- `deploy-guard.sh` usa el mismo módulo trasladado y sigue funcionando.

**Dependencias:** Ninguna

#### Tarea U4.2: `LocalGuardMiddleware`
**Archivo:** `backend/app/infra/http_security.py`, `backend/app/main.py`, `backend/tests/infra/test_local_guard.py`
**Acción:** Implementar el componente 5: `Host`, cookie `sauri_local` con `Sec-Fetch-Site`, y Bearer con `Origin` en `SAURI_EXTENSION_ORIGINS`.
**Criterio de Completado:**
- Propiedad 6 enumerando `app.routes`.
- Una prueba de navegador real, en el navegador integrado: una página servida en `http://127.0.0.1:9999` intenta un `fetch` simple, un `<form>` multipart y un `<img>` contra la API. Las tres fallan, y las mismas acciones desde el portal funcionan.

**Dependencias:** U4.1

#### Tarea U4.3: Portal sin login
**Archivo:** `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/session-user.ts`, `frontend/src/components/settings/AccountSettings.tsx`, `frontend/src/locales/{es,en}/*.json`, pruebas
**Acción:**
- En Modo_Local (`/api/v1/local/status` responde), no se muestra `LoginScreen` ni se envía Bearer.
- El nombre del usuario sale de la API, no del JWT.
- La cuenta no tiene botón de cerrar sesión.

**Criterio de Completado:** `npm run test` en verde y recorrido sin login en el navegador integrado.
**Dependencias:** U4.1

### Unidad U6: Runtime empaquetable (Claude, con un subagente para los scripts)

#### Tarea U6.1: `build-runtime.sh`
**Archivo:** `desktop/scripts/build-runtime.sh`, `desktop/runtime-manifest.json`, `desktop/runtime/.gitignore`
**Acción:**
- Descargar y verificar por SHA-256 CPython 3.11 (python-build-standalone, arm64, `install_only`) y el código fuente de PostgreSQL 16.x.
- Compilar PostgreSQL con prefijo reubicable y ajustar `install_name_tool` a `@loader_path`.
- Compilar `ffmpeg` LGPL mínimo, `whisper.cpp` con Metal, `llama.cpp` y `fluidaudiocli` en los commits que ya fijan los instaladores actuales.
- Construir las carpetas `--target` de `core`, `host-engine`, `asr-engine`, `llm-engine` y `diar-engine` con requisitos fijados.
- Escribir el manifiesto con versión y SHA-256 de cada pieza.

**Criterio de Completado:**
- Con la carpeta `runtime/` copiada a otra ruta, `pg_ctl initdb/start` funciona y cada motor responde `/health` con los binarios de `runtime/`, sin Homebrew en `PATH` (`env -i PATH=/usr/bin:/bin`).
- Medir y anotar el tamaño de cada pieza.

**Dependencias:** Ninguna

#### Tarea U6.2: PostgreSQL desechable para pruebas
**Archivo:** `scripts/tests/pg-disposable.sh`, `Makefile` (`test-pg`), `scripts/tests/test_pg_disposable.sh`
**Acción:**
- Crear un clúster temporal en `mktemp -d` con socket propio.
- Imprimir `SAURI_QA_POSTGRES_URL`.
- Borrarlo con `trap` al salir.

**Criterio de Completado:**
- `make test-scripts` en verde.
- Las pruebas de `test_migration.py` contra PostgreSQL pasan usándolo.

**Dependencias:** U6.1

---

## Fase 2

### Unidad U5: Extensión sin login y emparejada (Codex, `standard`)

#### Tarea U5.1: Una dirección, emparejamiento y aviso sin app
**Archivo:** `extension/src/core/backend.ts`, `extension/src/core/local-pairing.ts`, `extension/src/core/api/*`, `extension/src/background.ts`, `extension/src/panel/*`, `extension/src/detail/*`, `extension/src/locales/{es,en}/*.json`, pruebas
**Acción:** Implementar el componente 7 del diseño:
- Una sola constante de dirección.
- `ensureLocalToken`.
- Retirar `AuthView`, `session-refresh.ts` y sus claves, con una migración de almacenamiento que las limpie.
- Aviso «Abre Sauri en tu Mac…» cuando `/health` no responde.
- La cola de subidas sigue intacta.

**Criterio de Completado:**
- `npm run test -w extension` en verde, incluida una prueba en la que la app está apagada, se graba, se enciende la app y la subida sale sola.
- `grep` muestra una sola aparición de `localhost:8000` en `extension/src`, fuera de pruebas y manifiesto.

**Dependencias:** contrato de U4.1 (`/api/v1/local/pair`, `/health`)

#### Tarea U5.2: Manifiesto y material de la tienda
**Archivo:** `extension/manifest.json`, `extension/src/manifest.test.ts`, `extension/public/_locales/{es,en}/messages.json`, `extension/store/{es,en}/listing.md`, `extension/store/{es,en}/permissions.md`
**Acción:**
- Quitar `notifications`.
- Revisar que la descripción del manifiesto esté en español en `es`.
- Redactar la ficha y una justificación por permiso y por acceso de host, en lenguaje claro, con la skill `chrome-extensions` (sección de publicación).

**Criterio de Completado:**
- `manifest.test.ts` actualizado y en verde.
- Cada permiso del manifiesto tiene su justificación.
- `npm run build -w extension` produce el `.zip` listo para subir.

**Dependencias:** U5.1

### Unidad U7: App Electron (Codex, `deep+`)

#### Tarea U7.1: Esqueleto, configuración y supervisor
**Archivo:** `desktop/package.json`, `desktop/tsconfig.json`, `desktop/src/main/{main,config,paths,services,supervisor,ports,status,tray,autostart}.ts`, sus pruebas, `package.json` raíz (workspace)
**Acción:**
- Implementar el componente 1 del diseño. El supervisor sigue el patrón de `apx-v2-source/apps/desktop/src/main/core-process.ts`: `/health`, reinicio de 1 s a 30 s, registro rotado a 20 MB.
- Arrancar en el orden del diagrama, con instancia única y bandeja.
- Al salir, comprobar `GET /api/v1/local/status` y mostrar el diálogo de trabajos en curso.
- Crear los secretos internos en `secrets/` la primera vez.

**Criterio de Completado:**
- Pruebas unitarias del supervisor (caída y reinicio, backoff, rotación) y de `config` (ida y vuelta, versión de esquema).
- `npm run desktop:dev` abre el portal real con el runtime de U6 en `~/Library/Application Support/Sauri-dev`.

**Dependencias:** U6.1. Usa U3 y U4 si ya están integradas; si no, modo `password` y portal de Vite.

#### Tarea U7.2: Configuración inicial, fase A
**Archivo:** `desktop/src/setup/*`, `desktop/src/main/setup.ts`, `desktop/src/locales/{es,en}.json`, pruebas
**Acción:**
- Comprobar el equipo (arm64, macOS mínimo, memoria y espacio con `fs.statfs`).
- Pedir el nombre y las tres carpetas, con valores por defecto, selector de macOS, espacio libre, permiso de escritura y marcador `.sauri-folder`.
- Ejecutar `initdb` y `bootstrap --name`, y guardar `localUserId`.
- Retomar en el paso pendiente si se interrumpe.

**Criterio de Completado:**
- Recorrido completo en una carpeta de datos vacía, con capturas.
- Matar la app a mitad del recorrido y reabrirla retoma el paso.
- Una carpeta sin permiso de escritura se rechaza con un mensaje claro.

**Dependencias:** U7.1, U4.1

---

## Fase 3

### Unidad U8: Bienvenida y almacenamiento en el portal (subagente)

#### Tarea U8.1: `/bienvenida`
**Archivo:** `frontend/src/router.ts`, `frontend/src/components/welcome/*`, `frontend/src/locales/{es,en}/welcome.json`, pruebas
**Acción:**
- Mostrar los modelos recomendados con `LocalModelCard`, incluido el runtime de hablantes como Componente_Descargable (U9.2).
- Mostrar la conexión de la extensión: enlace a la tienda y estado del emparejamiento, leído de `/api/v1/local/status`.
- Al terminar, marcar `setupStep: done` mediante el preload.

**Criterio de Completado:** recorrido en el navegador integrado y pruebas de componentes.
**Dependencias:** U7.2

#### Tarea U8.2: `/settings/almacenamiento` y `relocate`
**Archivo:** `frontend/src/components/settings/StorageSettings.tsx`, `frontend/src/router.ts`, `desktop/src/main/relocate.ts`, `desktop/src/preload.ts`, pruebas
**Acción:**
- Mostrar el tamaño de cada carpeta y el espacio libre de su disco.
- «Cambiar» se niega si hay trabajos en curso. Si no, detiene los servicios, copia, verifica con la Propiedad 9, cambia la configuración, reinicia y ofrece borrar la carpeta anterior.

**Criterio de Completado:** la Propiedad 9 en pruebas de `relocate` y un recorrido moviendo grabaciones a otra carpeta con una reunión real de prueba.
**Dependencias:** U7.1, U4.1

### Unidad U9: Empaquetado, componentes, actualizaciones y desinstalación (Codex, `deep`; Claude verifica en hardware)

#### Tarea U9.1: `make package`
**Archivo:** `desktop/electron-builder.json`, `desktop/scripts/stage.ts`, `Makefile`, `THIRD_PARTY_NOTICES.md`
**Acción:**
- Generar el `.dmg` y el `.zip` arm64 con `identity: "-"` y sus `.sha256`.
- Escribir el inventario de licencias de todo lo que se distribuye: CPython, PostgreSQL, `ffmpeg` LGPL con su enlace al código, `whisper.cpp`, `llama.cpp`, FluidAudio, Senko, Electron y las licencias de los modelos del catálogo. Se verifica cada licencia en su repositorio; no se supone ninguna.

**Criterio de Completado:**
- El `.dmg` se instala y abre en el Mac del dueño.
- Se anotan los tamaños de descarga e instalado (Requisito 1.5).
- Ninguna dependencia con licencia incompatible con la distribución queda sin resolver.

**Dependencias:** U7.2

#### Tarea U9.2: Runtime de hablantes como Componente_Descargable
**Archivo:** `scripts/engines/model-catalog.json`, `backend/host-engine/local_models.py`, pruebas
**Acción:**
- Crear una entrada de catálogo para el runtime de `diar-engine`, con URL del Lugar_de_Descarga y SHA-256.
- Ampliar la lista de hosts permitidos (`local_models.py:100-126`) solo con ese host y su redirección de descarga.
- Tras instalarlo, el supervisor inicia `diar-engine`.

**Criterio de Completado:** pruebas de la lista de hosts (otro host se rechaza) e instalación real desde una Release de prueba en un repositorio desechable del dueño, o servida en `127.0.0.1` si el Lugar_de_Descarga aún no existe.
**Dependencias:** U9.1

#### Tarea U9.3: Actualizador
**Archivo:** `desktop/src/main/updater.ts`, `desktop/src/main/update-menu.ts`, pruebas
**Acción:** Implementar la decisión D12 y el Requisito 9: revisión cada 6 h, interruptor en los ajustes, ninguna actualización con trabajos en curso, migración antes del cambio, y copia y restauración de `pgdata`.
**Criterio de Completado:** la Propiedad 10 con una versión de prueba cuya migración falla a propósito, y una actualización real entre dos builds locales.
**Dependencias:** U9.1

#### Tarea U9.4: Desinstalar
**Archivo:** `desktop/src/main/uninstall.ts`, ajustes de la app, pruebas
**Acción:** Implementar el Requisito 10. Por defecto conserva las Rutas_de_Usuario y muestra su tamaño.
**Criterio de Completado:** después de desinstalar no queda nada en `~/Library/Application Support/Sauri`, `~/Library/Logs/Sauri` ni `/Applications/Sauri.app`, y las carpetas del usuario siguen intactas.
**Dependencias:** U7.1

### Unidad U10: Landing, instructivo, privacidad y publicación (subagente; publicar requiere el OK del dueño)

#### Tarea U10.1: Sección de descarga e instructivo
**Archivo:** `landing/index.html`, `landing/styles.css`, `landing/privacidad.html`, `landing/assets/install/*`
**Acción:**
- Antes, integrar `feature/landing-indigo`, con las capturas rehechas en Índigo.
- Añadir la descarga, los requisitos, el SHA-256, el instructivo de cinco pasos con capturas reales de la versión vigente de macOS («Abrir de todos modos» en Privacidad y seguridad), el enlace a la tienda y la política de privacidad.
- Explicar cómo desinstalar si la app no abre (Requisito 10.3).

**Criterio de Completado:** recorrido en el navegador integrado en escritorio y en móvil, y el instructivo probado de verdad con el `.dmg` de U9.1 en un usuario nuevo de macOS.
**Dependencias:** U9.1 y la decisión D13 del dueño

#### Tarea U10.2: `publish-release.sh`
**Archivo:** `scripts/package/publish-release.sh`, `scripts/tests/test_publish_release.sh`
**Acción:** Comprobar las sumas y crear la Release con `gh release create` en el repositorio que confirme el dueño. Sin `--force` y sin reemplazar Releases existentes.
**Criterio de Completado:** prueba en modo `--dry-run`. La primera publicación real solo con el OK del dueño.
**Dependencias:** U10.1

### Unidad U11: Traslado de los datos del dueño (Claude)

#### Tarea U11.1: `migrate-from-docker`
**Archivo:** `scripts/migrate-from-docker/migrate.py`, `scripts/migrate-from-docker/README.md`, pruebas con datos sintéticos
**Acción:** Implementar la decisión D14 y comprobar la Propiedad 8.
**Criterio de Completado:**
- Ensayo completo sobre una copia desechable: un Compose `sauri_qa_*` con datos sintéticos.
- Después, ejecución real con el dueño presente: informe sin diferencias, reuniones visibles en la app y una reunión reproducida.

**Dependencias:** U1, U2, U7.2

---

## Fase 4

### Unidad U12: Verificación final y retiro (Claude)

#### Tarea U12.1: Instalación limpia de punta a punta
**Archivo:** evidencias en la carpeta privada del dueño, `docs/history/` (informe sin datos de reuniones)
**Acción:** Seguir el Requisito 14.2 en un usuario nuevo de macOS, sin herramientas de desarrollador: descarga, configuración inicial, modelos, extensión desde la tienda (o su `.zip` mientras no esté publicada) y una reunión real con transcripción, hablantes y resumen.
**Criterio de Completado:** cada paso con evidencia. Lo no ejecutado se marca `NO VERIFICADO`.
**Dependencias:** U1–U11

#### Tarea U12.2: Retiro de Docker, RabbitMQ y S3, y documentación
**Archivo:** `docker-compose.yml`, `backend/app/infra/queue_rabbitmq.py`, `backend/app/infra/object_store_s3.py`, `frontend/Dockerfile`, `frontend/nginx.conf`, `backend/Dockerfile`, `scripts/platform/compose-bringup.sh`, `AGENTS.md`, `CLAUDE.md`, `docs/architecture/overview.md`, `docs/operations/*`, `.spectra/README.md`
**Acción:**
- Retirar lo que ya no usa nadie, después del traslado aceptado.
- Volver `QUEUE_KIND=postgres` y `OBJECT_STORE_KIND=filesystem` los únicos valores.
- Actualizar la documentación a la arquitectura sin Docker.
- Marcar `local-platform-deployment` como reemplazada.
- Los volúmenes Docker del dueño solo se borran con su autorización expresa.

**Criterio de Completado:**
- Pruebas completas en verde.
- `grep` sin referencias a `aio_pika`, boto3 (fuera de `migrate-from-docker`) ni `docker compose` en el código de la app.

**Dependencias:** U12.1 y aceptación del traslado por el dueño
