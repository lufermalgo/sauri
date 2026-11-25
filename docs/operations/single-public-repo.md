# Un solo repositorio público

Decisión del dueño (25-11-2026): `lufermalgo/sauri`, el repositorio de siempre, pasa a ser público con todo su historial, para que otras personas lo usen y lo mejoren. El repositorio de descargas `lufermalgo/sauri-app` se retira. Este documento es el plan y el orden de los pasos. Cada paso marcado **(dueño)** es un ajuste del repositorio o una acción irreversible que hace o aprueba el dueño.

## Lo que encontró la revisión (25-11-2026)

Se revisaron los 2222 commits que GitHub guarda (rama `main` y las referencias de los 646 PR), los 1211 issues y PR y sus 632 comentarios. Al hacerse público, todo eso queda visible.

- **Sin claves reales.** Solo valores de prueba (`synthetic-…`, `example.test`) y el archivo de ejemplo de configuración.
- **Sin contenido de reuniones reales** (ni audio, ni video, ni texto de transcripciones o resúmenes). Las capturas de la página son de una reunión de demostración inventada.
- **Nombres de grabaciones reales del dueño**, que dejan ver clientes y temas de trabajo. En los archivos actuales ya se reemplazaron por «grabación A…E» (rama de este cambio). Siguen en commits antiguos, que no se pueden borrar de GitHub (las referencias de PR son permanentes), y en versiones anteriores de 3 issues (#899, #1186, #1269), cuyo texto ya se corrigió el 25-11-2026. GitHub guarda esas versiones anteriores; el dueño puede borrarlas desde el menú «editado» de cada issue.
- **La empresa del dueño aparece en el historial** como dueña de la «plataforma interna» (specs antiguas, datos de prueba con su dominio de correo, maquetas de diseño con su marca).
- **Notas internas:** reglas de trabajo de los agentes (`AGENTS.md`, `CLAUDE.md`, `.claude/`, `.agents/`, `.spectra/`) y rutas de la carpeta personal del dueño. No tienen datos privados; quedan públicas como forma de trabajar del proyecto.
- **Sin licencia** al momento de la revisión; el dueño eligió Apache-2.0 (se agrega en este cambio). `THIRD_PARTY_NOTICES.md` ya cubre los modelos y componentes de terceros.
- **CI:** `ci.yml` usa `pull_request` (no `pull_request_target`) y no tiene secretos, así que es seguro recibir PR de otras personas. En un repositorio público, GitHub Actions es gratis.

## Qué depende hoy de `sauri-app`

- **Apps instaladas (0.1.0 a 0.2.3):** buscan actualizaciones en `api.github.com/repos/lufermalgo/sauri-app/releases` y bajan la app y el componente de hablantes (`diar-0.1.0`) de sus Releases. Revisan cada salto de una redirección contra una lista fija (`desktop/src/main/releases.ts`, `updater.ts`), así que **renombrar, trasladar o borrar `sauri-app` las dejaría sin actualizaciones**.
- **Página:** `https://lufermalgo.github.io/sauri-app/` (Pages desde `main` `/` de `sauri-app`, copiada de `landing/`). La página y la política de privacidad enlazan a sus Releases e issues («Ayuda»).
- **Chrome Web Store:** la ficha de la extensión apunta a la política de privacidad y a la ayuda en las direcciones de `sauri-app` (se cambian en el panel de la tienda).
- Descargas registradas: de 1 a 4 por versión.

## Orden de los pasos

1. Licencia: Apache-2.0, elegida por el dueño el 25-11-2026 (`LICENSE`, `NOTICE`). Texto de los issues corregido; **(dueño)** borrar las versiones anteriores de #899, #1186 y #1269 (menú «editado»).
2. **(dueño)** Hacer público `lufermalgo/sauri` (Settings → General → Danger Zone → Change visibility). Activar Pages con origen «GitHub Actions» y proteger `main` (sin push directo ni `--force`).
3. Fusionar este cambio. Desde ahí, la página se publica sola desde `landing/` con `.github/workflows/pages.yml` en `https://lufermalgo.github.io/sauri/`.
4. Copiar a las Releases de `lufermalgo/sauri` `v0.2.3` y `diar-0.1.0` (los mismos archivos y huellas), para que la página y la app tengan qué bajar desde el primer día.
5. **Versión puente** (p. ej. 0.2.4), la primera que busca en `lufermalgo/sauri`. Se publica en `lufermalgo/sauri` **y** en `sauri-app`, así las apps instaladas la encuentran donde miran hoy y, al actualizarse, pasan a mirar el repositorio público.
6. En `sauri-app` se reemplaza la página por un aviso con redirección automática a la dirección nueva y el README dice dónde vive ahora el proyecto.
7. **(dueño)** En el panel de Chrome Web Store, cambiar la política de privacidad a `https://lufermalgo.github.io/sauri/privacidad.html` y la ayuda a `https://github.com/lufermalgo/sauri/issues`.
8. **(dueño)** Archivar `sauri-app`: queda de solo lectura y sigue sirviendo la versión puente y la redirección. No se borra ni se renombra.

## Lo que ya está hecho en la rama `chore/single-public-repo`

- La app busca actualizaciones y componentes en `lufermalgo/sauri` (`desktop/src/main/releases.ts` y sus pruebas).
- La página y la política de privacidad enlazan al repositorio y a la dirección nuevos.
- Flujo de publicación de la página (`.github/workflows/pages.yml`).
- Nombres de grabaciones reales reemplazados en specs y documentos.
- Se retiraron las maquetas antiguas de `docs/design/stitch/` (inspiración visual ya cumplida, con marca de la empresa y nombres de clientes de ejemplo); siguen en el historial.
- Licencia Apache-2.0 (`LICENSE`, `NOTICE`, campos `license` de los paquetes, README).
