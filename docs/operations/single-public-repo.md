# Un solo repositorio público

Decisión del dueño (25-11-2026): Sauri queda público en un solo repositorio, `lufermalgo/sauri`, y se retira el repositorio de descargas `lufermalgo/sauri-app`. Este documento es el plan y el orden de los pasos. Cada paso marcado **(dueño)** es una acción irreversible o un ajuste del repositorio que hace o aprueba el dueño.

## Lo que encontró la revisión (25-11-2026)

Se revisaron los 2222 commits que GitHub guarda (rama `main` y las referencias de los 646 PR, que GitHub no deja borrar), los 1211 issues y PR y sus 632 comentarios.

- **Sin claves reales.** Solo valores de prueba (`synthetic-…`, `example.test`) y el archivo de ejemplo de configuración.
- **Sin contenido de reuniones reales** (ni audio, ni video, ni texto de transcripciones o resúmenes). Las capturas de la página son de una reunión de demostración inventada.
- **Sí hay nombres de grabaciones reales del dueño**, que revelan clientes y temas de trabajo, en documentos de specs, en el historial y en 6 issues. En la rama de este cambio ya se reemplazaron por «grabación A…E» en los archivos actuales; el historial y los issues los conservan.
- **La empresa del dueño aparece en todo el historial** como dueña de la «plataforma interna» (specs antiguas, datos de prueba con su dominio de correo, maquetas de diseño con su marca).
- **Notas internas:** reglas de trabajo de los agentes (`AGENTS.md`, `CLAUDE.md`, `.claude/`, `.agents/`, `.spectra/`), rutas de la carpeta personal del dueño y su correo de contacto (este ya es público en la política de privacidad).
- **Sin licencia:** no hay archivo `LICENSE`. Sin él, el código público se puede leer pero nadie tiene permiso de usarlo. `THIRD_PARTY_NOTICES.md` ya cubre los modelos y componentes de terceros.
- **Peso:** 23 MB, sin archivos grandes.

## Qué depende hoy de `sauri-app`

- **Apps instaladas (0.1.0 a 0.2.3):** buscan actualizaciones en `api.github.com/repos/lufermalgo/sauri-app/releases` y bajan la app y el componente de hablantes (`diar-0.1.0`) de sus Releases. Revisan cada salto de una redirección contra una lista fija (`desktop/src/main/releases.ts`, `updater.ts`), así que **renombrar o trasladar `sauri-app` las dejaría sin actualizaciones**: la redirección de GitHub no pasa esa lista.
- **Página:** `https://lufermalgo.github.io/sauri-app/` (Pages desde `main` `/` de `sauri-app`, copiada de `landing/`). `landing/index.html` y `landing/privacidad.html` enlazan a sus Releases e issues («Ayuda»).
- **Chrome Web Store:** la ficha de la extensión apunta a la política de privacidad y a la ayuda en las direcciones de `sauri-app` (se cambian en el panel de la tienda; el repositorio no las guarda).
- Descargas registradas: de 1 a 4 por versión, así que casi nadie más que el dueño tiene la app instalada.

## Recomendación: repositorio nuevo con historia limpia

Publicar `lufermalgo/sauri` tal como está expone para siempre el historial, los nombres de clientes, los 1211 issues y las referencias de PR (GitHub no permite borrarlas; reescribir la historia no las quita). Por eso se recomienda:

1. El repositorio privado actual pasa a llamarse `lufermalgo/sauri-archive` y sigue **privado**, con todo su historial, issues y PR. **(dueño)**
2. Se crea un repositorio público nuevo `lufermalgo/sauri` con **un solo commit**: los archivos de `main` en ese momento, generados con `scripts/platform/public-snapshot.sh` (revisa que no haya claves ni las palabras privadas de una lista guardada fuera del repositorio). **(dueño: crear y hacerlo público)**
3. Desde ahí se trabaja solo en el repositorio público: issues, PR, ramas y worktrees. Los clones locales cambian su `origin` al nuevo y guardan el archivo como segundo remoto.

*Alternativa descartada:* reescribir el historial para limpiarlo. Exige instalar `git-filter-repo`, rompe los números de issue de cada commit (`#1278` apuntaría a otra cosa en el repo nuevo) y no ofrece nada que el dueño necesite; el historial sigue disponible en el archivo privado.

## Antes de publicar (decisiones del dueño)

- **Permiso de la empresa:** el historial describe Sauri como plataforma interna de esa empresa. Confirmar que el dueño puede publicar el código. Si no es claro, conviene limpiar también las menciones en los archivos actuales (descripciones del backend, datos de prueba, `docs/design/stitch/`, `docs/product/`).
- **Licencia:** elegir una. Para un proyecto que se quiere abierto, MIT o Apache-2.0 (permite todo uso, incluido el comercial). AGPL-3.0 obliga a quien lo modifique y lo ofrezca a publicar sus cambios. Sin licencia, solo se puede leer.
- **Notas de los agentes:** se pueden publicar (no tienen datos privados tras la limpieza) o dejar fuera. Se recomienda publicarlas: son la forma de trabajar del proyecto.

## Orden de los pasos

1. **(dueño)** Renombrar el privado a `sauri-archive`.
2. **(dueño)** Crear `lufermalgo/sauri` público y vacío; activar Pages con origen «GitHub Actions»; protección de `main` (sin push directo ni `--force`).
3. Fusionar la rama de este cambio en el `main` del archivo (no antes del paso 2: la próxima versión buscaría actualizaciones en un repositorio que aún no existe), generar el commit único con `public-snapshot.sh` desde ese `main` y subirlo (con el OK del dueño: es contenido público).
4. Pasar los clones locales al repo nuevo (`origin` = `lufermalgo/sauri`, `archive` = `lufermalgo/sauri-archive`).
5. Copiar a las Releases del repo nuevo `v0.2.3` y `diar-0.1.0` (los mismos archivos y huellas), para que la página y la app tengan qué bajar desde el primer día.
6. **Versión puente** (p. ej. 0.2.4): ya busca en `lufermalgo/sauri`. Se publica en el repo nuevo **y** en `sauri-app`, así las apps instaladas la encuentran donde miran hoy y, al actualizarse, pasan a mirar el repo nuevo.
7. La página se publica sola desde `landing/` con `.github/workflows/pages.yml` en `https://lufermalgo.github.io/sauri/`. En `sauri-app` se reemplaza la página por un aviso con redirección automática a la dirección nueva.
8. **(dueño)** En el panel de Chrome Web Store, cambiar la política de privacidad a `https://lufermalgo.github.io/sauri/privacidad.html` y la ayuda a `https://github.com/lufermalgo/sauri/issues`.
9. **(dueño)** Archivar `sauri-app` (queda de solo lectura y sigue sirviendo la versión puente y la redirección). No se borra: las apps viejas que nunca se actualizaron seguirían sin poder encontrar la puente.

## Lo que ya está hecho en la rama `chore/single-public-repo`

- La app busca actualizaciones y componentes en `lufermalgo/sauri` (`desktop/src/main/releases.ts` y sus pruebas).
- La página y la política de privacidad enlazan al repo y a la dirección nuevos.
- Flujo de publicación de la página (`.github/workflows/pages.yml`).
- Nombres de grabaciones reales reemplazados en specs y documentos.
- `scripts/platform/public-snapshot.sh` para generar el commit único.
