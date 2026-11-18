# Traslado único de Docker a la app de escritorio

Esta herramienta copia **una sola vez** tus reuniones de la instalación con Docker a la app Sauri nueva: la base de datos (reuniones, transcripciones, hablantes, plantillas, ajustes) y los archivos de grabación (audio, video, miniaturas).

**Qué no hace nunca:** no borra, no detiene y no cambia nada de Docker. Solo lee. Si algo sale mal, Docker sigue exactamente como estaba y puedes seguir usándolo. Retirar Docker es un paso aparte que se hace después, solo con tu autorización.

**Cuándo se niega a empezar:** si hay una reunión procesándose, si el `api` o el `worker` de Docker siguen encendidos, si no hay espacio libre suficiente o si la base de la app ya tiene reuniones.

## Antes de empezar

1. Espera a que no haya ninguna reunión procesándose en Sauri (todas en «Completada» o «Fallida»).
2. Cierra la app Sauri nueva (desde la barra de menú, «Salir»).
3. Detén solo las partes de Docker que escriben datos. La base de datos, el almacén de archivos y la cola siguen encendidos porque la herramienta los lee:

   ```bash
   cd ~/Proyectos/sauri
   docker compose -p sauri stop api worker portal
   ```

4. Enciende solo la base de datos de la app (sin abrir la app). Ajusta `DB_FOLDER` si elegiste otra carpeta en la configuración inicial:

   ```bash
   APP="$HOME/Library/Application Support/Sauri"
   DB_FOLDER="$HOME/Sauri/Base de datos"
   REC="$HOME/Sauri/Grabaciones"
   PG_BIN="<carpeta pg/bin del runtime de la app>"   # en desarrollo: $HOME/Library/Caches/sauri-runtime-build/runtime-current/pg/bin
   "$PG_BIN/pg_ctl" -D "$DB_FOLDER/pgdata" -l "$HOME/Library/Logs/Sauri/postgres-traslado.log" \
     -o "-c listen_addresses= -k '$APP/run' -p 5432" -w start
   ```

5. Prepara la conexión a esa base (la clave la lee de su archivo; no se muestra en pantalla):

   ```bash
   export DATABASE_URL="postgresql+asyncpg://sauri@/sauri?host=$APP/run"
   export DATABASE_PASSWORD_FILE="$APP/secrets/database_password"
   export PG_BIN
   ```

## Paso 1: ensayo sin cambios (`--dry-run`)

```bash
cd ~/Proyectos/sauri/backend
uv run python ../scripts/migrate-from-docker/migrate.py --dry-run --recordings "$REC" --config "$APP/config.json"
```

Qué revisar en lo que imprime:
- La lista de tablas con su número de filas (por ejemplo, `public.meetings: 120`).
- `Objects:` cuántos archivos y cuánto ocupan.
- Cada línea `Space for ...` debe terminar en `ok`.
- `Result: ready` significa que todo está listo. Si aparece `PROBLEM:`, la línea dice qué falta; no sigas hasta resolverlo.

Si ya completaste la configuración inicial de la app (aunque no hayas grabado nada), el ensayo dirá que la base «holds a freshly set-up app». Es normal: en el paso 2 añade `--replace-fresh-app-db`. La herramienta solo reemplaza una base **sin reuniones** y con un usuario como máximo; una base con reuniones no la reemplaza nunca.

## Paso 2: traslado (`--run`)

```bash
uv run python ../scripts/migrate-from-docker/migrate.py --run --recordings "$REC" --config "$APP/config.json"
# si el paso 1 lo pidió:  ... --run --replace-fresh-app-db ...
```

Hace, en orden: comprueba otra vez que no hay nada en curso; saca una copia de la base de Docker (solo lectura); la restaura en la base de la app y la actualiza al esquema nuevo; copia cada archivo comprobando su tamaño y su huella MD5; compara las filas de cada tabla y el conjunto de archivos; y escribe en `config.json` tu usuario de siempre (`admin@sauri.local`) como usuario de la app, para que todas tus reuniones, plantillas y ajustes conserven su dueño.

Qué revisar al final:
- `Result: ok` y ninguna línea `DIFFERENCE:`.
- `Objects: N (...) -> N (...)`: el mismo número y tamaño a ambos lados.
- `Local user id (SAURI_LOCAL_USER_ID): ...`: el id de tu usuario.
- `Report: ...`: la ruta del informe JSON en `~/Library/Logs/Sauri/`. Guárdalo en tu carpeta privada de evidencias. El informe no contiene texto, audio ni títulos de reuniones, solo conteos, tamaños, claves de archivo y el id del usuario.

Si sale `Result: differences` o `Result: error`, el código de salida no es cero y el informe dice qué tabla o qué archivo no coincide. Docker sigue intacto. Para repetir después de corregir la causa, usa `--replace-unfinished`: la herramienta reconoce su propio intento a medias y solo reemplaza ese.

Para volver a comprobar más tarde que la app sigue igual a Docker (sin cambiar nada): `--verify` en lugar de `--run`.

## Después

```bash
"$PG_BIN/pg_ctl" -D "$DB_FOLDER/pgdata" -w stop
```

Abre la app Sauri: deben aparecer tus reuniones. Reproduce una para confirmar que el audio y el video se ven. Mientras no confirmes, Docker sigue ahí: para volver a él basta `docker compose -p sauri start api worker portal`.

## Opciones

| Opción | Para qué |
|---|---|
| `--source-container` | Contenedor de PostgreSQL de Docker (por defecto `sauri-postgres-1`). |
| `--rabbitmq-container` | Cola cuyas tareas pendientes deben ser cero (por defecto `sauri-rabbitmq-1`). Sus mensajes no se copian. |
| `--writer-containers` | Contenedores que deben estar detenidos (por defecto `sauri-api-1,sauri-worker-1`). |
| `--s3-endpoint`, `--s3-bucket` | Almacén de archivos de Docker (por defecto `http://127.0.0.1:9000`, `sauri-recordings`). Las claves se leen de `~/.config/sauri/object_store_*_key`. |
| `--target-url` | Base de la app, si no usas `DATABASE_URL`. |
| `--work-dir` | Dónde se guarda la copia temporal de la base (por defecto `~/Library/Caches/Sauri/migrate-from-docker`, solo para ti). Se borra al terminar salvo `--keep-dump`. |
| `--report` | Otra ruta para el informe. |

## Ensayo con datos de prueba

`rehearsal/rehearse.sh` repite todo el proceso sobre contenedores desechables `sauri-qa-mig-*` con datos inventados, incluidos los casos de fallo (trabajo en curso, poco espacio, archivo dañado, intento a medias). No toca el proyecto `sauri` y borra todo lo que crea al terminar.
