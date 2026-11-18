# Requisitos — Sauri como app de escritorio para Mac con chip M

## Introducción

Hoy Sauri solo funciona en el Mac del dueño y exige un montaje de desarrollador. El portal, la API, el worker, PostgreSQL 16, RabbitMQ y el almacén S3 (RustFS, servicio `minio`) corren en Docker Desktop. Los motores de IA corren nativos en los puertos 8001–8005. Para instalarlos hacen falta Homebrew (`whisper-cpp`), Python 3.11, `uv`, `cmake` y `git`, porque `llama.cpp` se compila en el equipo, y Xcode CLT con Swift 6, porque Parakeet también se compila (`docs/operations/installation-notes.md:5-84`, `scripts/engines/install-*.sh`). Las credenciales se crean con un script en `~/.config/sauri/` y el primer usuario con `seed_admin` (`scripts/platform/compose-bringup.sh:66-67`). Compañeros del dueño con Mac quieren usar Sauri y no pueden hacer ese montaje. El dueño tampoco puede servirles desde su propio equipo.

Ya existen piezas que ayudan. La cola (`backend/app/infra/queue.py`) y el almacén de objetos (`backend/app/infra/object_store.py`) están detrás de interfaces. El portal ya detecta el equipo, recomienda modelos locales y los instala con un botón (`frontend/src/components/settings/LocalModelCard.tsx`, `backend/app/engines/local_router.py`). APX, que el dueño usa como referencia, ya distribuye una app Electron que lleva su núcleo dentro (`apx-v2-source/apps/desktop/electron-builder.json`, `apps/desktop/src/main/core-process.ts`, `updater.ts`).

**Idea fuerza:** quien tenga un Mac con chip M descarga Sauri desde la landing y lo abre. Sin terminal, sin Docker y sin cuentas, elige dónde guardar sus datos y graba su primera reunión. Todo se procesa en su Mac.

**Decisiones del dueño (conversación del 2026-11-18, issue #1199):** solo Mac con chip M; sin Docker; login desactivado por ahora (vuelve solo si se crea un servidor central); configuración inicial de rutas en disco; empaquetado al estilo de APX, sin firma ni notarización de Apple, descargado desde la landing con un instructivo; extensión publicada en Chrome Web Store y visible en búsquedas. Estas decisiones reemplazan la del 2026-11-12 de `local-platform-deployment` («servicios centrales en Docker»).

**Alcance:** la app de escritorio y su instalador; el núcleo sin Docker; el modo local sin login con su protección; la configuración inicial y el cambio de rutas; la puesta en marcha de los motores sin herramientas de desarrollador; las actualizaciones; el traslado único de los datos actuales del dueño; la extensión lista para Chrome Web Store; la sección de descarga de la landing.

**Fuera de alcance:** Windows, Linux y Mac con procesador Intel; servidor central, varios usuarios o acceso desde otros equipos; firma y notarización de Apple; reescritura nativa en Swift; cambios en la calidad de transcripción, hablantes o resúmenes; nuevos proveedores externos; telemetría de uso.

## Glosario

- **App_Sauri**: la aplicación de escritorio para macOS en Apple silicon que el usuario instala. Contiene la ventana del portal, el Núcleo_Local y los binarios de los motores, y supervisa sus procesos.
- **Núcleo_Local**: los procesos que hoy corren en Docker (API, worker, base de datos, cola y almacén de archivos), ejecutados como procesos locales del Mac sin Docker.
- **Motores_Nativos**: los motores de transcripción (ASR/Parakeet/Whisper), hablantes (Senko), resumen (llama.cpp) y gestión de modelos (`host-engine`).
- **Modo_Local**: modo de funcionamiento sin pantalla de login. Un único Usuario_Local es el dueño de todos los datos de esa instalación.
- **Usuario_Local**: la fila de `users` que representa a la persona que usa la instalación. Tiene los permisos que hoy da `is_sales`.
- **Origen_Autorizado**: el portal servido por la propia App_Sauri y la extensión publicada de Sauri (y su identificador de desarrollo). Ningún otro origen lo es.
- **Configuración_Inicial**: el asistente que se muestra la primera vez que se abre la App_Sauri.
- **Rutas_de_Usuario**: las carpetas que el usuario elige: Carpeta_de_Grabaciones (audio, video y miniaturas), Carpeta_de_Base_de_Datos y Carpeta_de_Modelos.
- **Rutas_Internas**: lo que el usuario no elige: credenciales, binarios, entornos de Python, archivos de proceso, registros, temporales y catálogos.
- **Paquete_de_Instalación**: el archivo descargable (`.dmg`, y `.zip` para actualizar) de una versión de la App_Sauri, con su suma SHA-256 publicada.
- **Lugar_de_Descarga**: el sitio público donde se publican la landing, los Paquete_de_Instalación y la política de privacidad.
- **Instalación_Docker_del_Dueño**: el proyecto de Compose `sauri` del dueño y sus volúmenes `sauri_pgdata`, `sauri_minio-data` y `sauri_rabbitmq-data`.

## Requisitos

### Requisito 1: Una app que se instala sin herramientas de desarrollador

**Historia de Usuario:** Como compañero del dueño con un Mac M, quiero instalar Sauri arrastrando una app a Aplicaciones, para usarlo sin saber de programación.

#### Criterios de Aceptación

1. THE Paquete_de_Instalación SHALL contener todo lo necesario para iniciar el Núcleo_Local y los Motores_Nativos: entorno de Python, base de datos, `ffmpeg` y los binarios de `whisper-cli`, `llama-server` y `fluidaudiocli` ya compilados para arm64.
2. WHEN se instala en un Mac nuevo sin Homebrew, Xcode CLT, Python, `uv`, `cmake`, `git`, Node ni Docker, THE App_Sauri SHALL iniciar el Núcleo_Local y los Motores_Nativos sin que el usuario abra la terminal.
3. THE App_Sauri SHALL NOT compilar código en el equipo del usuario ni ejecutar `brew`, `pip` contra Internet o `swift build` durante la instalación o el primer uso.
4. WHEN la App_Sauri descarga algo durante el primer uso (modelos o componentes pesados), THE App_Sauri SHALL comprobar la suma SHA-256 fijada en el catálogo antes de usarlo, como ya hace `host-engine` con los modelos.
5. THE Paquete_de_Instalación SHALL declarar su tamaño de descarga y el espacio que ocupa instalado, y ambos datos SHALL aparecer en la landing.

### Requisito 2: Comprobación del equipo

**Historia de Usuario:** Como usuario, quiero saber desde el principio si mi Mac sirve, para no perder tiempo con una instalación que no funcionará.

#### Criterios de Aceptación

1. WHEN se abre la App_Sauri por primera vez, THE App_Sauri SHALL comprobar la arquitectura arm64, la versión de macOS, la memoria y el espacio libre, con la detección de `backend/host-engine/hardware.py` y la recomendación de `recommend.py`.
2. IF el equipo no es arm64 o su macOS es anterior a la mínima que exigen los Motores_Nativos, THEN THE App_Sauri SHALL explicarlo en lenguaje simple y no continuar.
3. IF la memoria o el espacio libre están por debajo de lo que recomienda `recommend.py` para los modelos elegidos, THEN THE App_Sauri SHALL mostrar la advertencia y la cifra que falta, y dejar continuar con un modelo más liviano si existe.

### Requisito 3: Núcleo sin Docker

**Historia de Usuario:** Como usuario, quiero que Sauri funcione sin Docker Desktop, para no instalar ni mantener otro programa.

#### Criterios de Aceptación

1. THE Núcleo_Local SHALL ejecutar la API, el worker, la base de datos, la cola de trabajos y el almacén de archivos como procesos del Mac supervisados por la App_Sauri, sin Docker.
2. THE Núcleo_Local SHALL conservar las garantías de concurrencia que hoy dan PostgreSQL (bloqueos de fila, `SKIP LOCKED`, `RETURNING` y el turno único de motor de `engine_slot.py`) y la cola (reintentos con espera, aplazamiento, temas `.failed` y conteo de pendientes), o reemplazarlas por otras equivalentes cubiertas por pruebas.
3. THE Núcleo_Local SHALL aplicar la cadena de migraciones Alembic existente sobre la base de datos, sin un esquema paralelo.
4. THE Núcleo_Local SHALL guardar cada grabación, video y miniatura como un archivo normal dentro de la Carpeta_de_Grabaciones.
5. WHEN el portal reproduce o descarga una grabación, THE Núcleo_Local SHALL servirla con lecturas parciales (Range) mediante enlaces temporales autorizados, igual que hoy los enlaces firmados.
6. THE Núcleo_Local SHALL escuchar solo en `127.0.0.1` y en puertos fijos y documentados.
7. IF un puerto del Núcleo_Local o de los Motores_Nativos está ocupado por otro programa, THEN THE App_Sauri SHALL decir qué puerto es y no iniciar a medias.

### Requisito 4: Modo local sin login

**Historia de Usuario:** Como usuario de mi propio Mac, quiero entrar a Sauri sin usuario ni contraseña, porque soy la única persona que lo usa.

#### Criterios de Aceptación

1. WHERE el Modo_Local está activo, THE portal SHALL abrir directamente la biblioteca, sin pantalla de login, y la página `/settings/cuenta` SHALL mostrar el nombre del Usuario_Local sin botón de cerrar sesión.
2. WHERE el Modo_Local está activo, THE API SHALL atender a todas las rutas que hoy exigen usuario como el Usuario_Local, que existe como fila real en `users` con los permisos de `is_sales`.
3. WHEN la Configuración_Inicial termina en una instalación nueva, THE App_Sauri SHALL crear el Usuario_Local con el nombre que escriba el usuario, sin pedir correo ni contraseña.
4. THE App_Sauri SHALL crear y guardar sus credenciales internas (secreto de firma, claves entre servicios y motores) sin intervención del usuario. Las claves de proveedores externos SHALL seguir guardándose en el Llavero de macOS.
5. THE modo con contraseña SHALL seguir disponible solo por configuración, para desarrollo, pruebas y un futuro servidor central. THE App_Sauri SHALL NOT mostrarlo.

### Requisito 5: Protección del Núcleo_Local sin login

**Historia de Usuario:** Como usuario, quiero que ninguna página web que visite pueda leer ni cambiar mis grabaciones a escondidas, ahora que no hay contraseña.

#### Criterios de Aceptación

1. IF una petición llega con un encabezado `Host` distinto de `127.0.0.1` o `localhost` en el puerto de la API, THEN THE API SHALL rechazarla. Esto evita el «DNS rebinding».
2. IF una petición que lee o cambia datos no viene de un Origen_Autorizado, THEN THE API SHALL rechazarla, aunque sea una petición «simple» (formulario multipart o GET) que el navegador envía sin consulta previa.
3. THE API SHALL exigir en toda ruta de datos una credencial local que solo pueden obtener el portal de la App_Sauri y la extensión emparejada. Una página de otro sitio SHALL NOT poder obtenerla.
4. THE pruebas SHALL demostrar que una página servida desde otro origen en el mismo Mac no puede listar reuniones, subir una grabación, descargar un archivo ni cambiar un ajuste.

### Requisito 6: Configuración_Inicial

**Historia de Usuario:** Como usuario nuevo, quiero que la primera vez Sauri me pregunte lo justo para empezar, para quedar listo en pocos minutos.

#### Criterios de Aceptación

1. WHEN se abre la App_Sauri sin configuración previa, THE Configuración_Inicial SHALL guiar en este orden: comprobación del equipo, nombre del Usuario_Local, Rutas_de_Usuario, modelos recomendados y conexión de la extensión.
2. THE Configuración_Inicial SHALL proponer por defecto rutas dentro de la carpeta del usuario (por ejemplo `~/Sauri/Grabaciones`) y permitir elegir otras con el selector de carpetas de macOS, incluido un disco externo.
3. WHEN el usuario elige una carpeta, THE Configuración_Inicial SHALL mostrar el espacio libre de ese disco y rechazar carpetas sin permiso de escritura.
4. WHEN el usuario llega al paso de modelos, THE Configuración_Inicial SHALL ofrecer los modelos recomendados para su equipo con su tamaño, e instalarlos con el flujo existente de `LocalModelCard` (progreso, verificación y cancelación).
5. IF el usuario cierra la App_Sauri a mitad de la Configuración_Inicial, THEN THE App_Sauri SHALL retomarla en el paso pendiente al volver a abrirla.
6. THE Configuración_Inicial SHALL mostrar los textos en español, con inglés disponible, desde `frontend/src/locales/`.

### Requisito 7: Cambiar las rutas después

**Historia de Usuario:** Como usuario, quiero mover mis grabaciones o modelos a otro disco cuando se me llene el Mac, sin perder nada.

#### Criterios de Aceptación

1. THE ajustes del portal SHALL mostrar cada Ruta_de_Usuario con el espacio que ocupa y el espacio libre de su disco, y permitir cambiarla.
2. WHEN el usuario cambia una Ruta_de_Usuario, THE App_Sauri SHALL copiar los datos, verificar que la copia está completa y solo entonces empezar a usar la nueva ruta. La carpeta anterior SHALL quedar intacta hasta que el usuario decida borrarla.
3. IF hay reuniones procesándose, THEN THE App_Sauri SHALL NOT cambiar rutas y SHALL indicar cuántas faltan por terminar.
4. IF una Ruta_de_Usuario no está disponible al iniciar (por ejemplo, un disco externo desconectado), THEN THE App_Sauri SHALL decir qué carpeta falta y no iniciar el Núcleo_Local sobre una carpeta vacía.

### Requisito 8: Funcionamiento diario de la App_Sauri

**Historia de Usuario:** Como usuario, quiero que Sauri esté listo cuando grabo y que no se apague en mitad de una transcripción.

#### Criterios de Aceptación

1. WHEN se abre la App_Sauri, THE App_Sauri SHALL iniciar el Núcleo_Local y los Motores_Nativos, esperar a que respondan sus comprobaciones de salud y luego mostrar el portal en su ventana.
2. THE App_Sauri SHALL mostrar un ícono en la barra de menú con el estado (listo, procesando, con error). Cerrar la ventana SHALL dejar los servicios funcionando.
3. THE App_Sauri SHALL ofrecer en sus ajustes la opción de abrirse al iniciar sesión en el Mac, apagada por defecto.
4. WHEN el usuario elige salir con reuniones procesándose, THE App_Sauri SHALL avisar cuántas hay y pedir confirmación antes de detener los servicios.
5. IF un proceso del Núcleo_Local o de los Motores_Nativos se cae, THEN THE App_Sauri SHALL reiniciarlo con espera creciente, anotarlo en su registro y mostrar el error si no se recupera.
6. THE App_Sauri SHALL permitir una sola instancia abierta a la vez.
7. THE App_Sauri SHALL guardar sus registros en `~/Library/Logs/Sauri`, con rotación por tamaño, y ofrecer un botón para abrir esa carpeta.

### Requisito 9: Actualizaciones

**Historia de Usuario:** Como usuario, quiero recibir las versiones nuevas sin reinstalar ni perder mis reuniones.

#### Criterios de Aceptación

1. THE App_Sauri SHALL revisar el Lugar_de_Descarga cada pocas horas en busca de una versión más nueva, sin enviar datos del usuario ni de sus reuniones.
2. WHEN hay una versión nueva, THE App_Sauri SHALL descargarla, comprobar su SHA-256 y aplicarla al reiniciar, con confirmación del usuario.
3. WHEN una versión nueva trae migraciones de base de datos, THE App_Sauri SHALL hacer una copia de seguridad de la base de datos antes de migrar, y conservar la última copia.
4. IF la migración falla, THEN THE App_Sauri SHALL restaurar la copia, volver a abrir la versión anterior de los datos y mostrar el error.
5. THE ajustes SHALL permitir apagar la búsqueda automática de actualizaciones.
6. THE App_Sauri SHALL NOT actualizar ni reiniciar servicios mientras haya reuniones procesándose.

### Requisito 10: Desinstalar

**Historia de Usuario:** Como usuario, quiero quitar Sauri y decidir si me quedo con mis grabaciones.

#### Criterios de Aceptación

1. THE App_Sauri SHALL ofrecer en sus ajustes «Desinstalar Sauri», que detiene los servicios y borra los binarios, entornos y Rutas_Internas.
2. WHEN el usuario desinstala, THE App_Sauri SHALL preguntar por separado si borrar también las Rutas_de_Usuario, y mostrar su tamaño. Por defecto SHALL conservarlas.
3. THE landing SHALL explicar cómo desinstalar si la App_Sauri ya no abre.

### Requisito 11: Descarga desde la landing

**Historia de Usuario:** Como compañero del dueño, quiero entrar a la página de Sauri, descargar la app y seguir unos pasos cortos para abrirla aunque no esté firmada por Apple.

#### Criterios de Aceptación

1. THE landing SHALL tener una sección de descarga con un botón a la última versión, los requisitos (Mac con chip M, versión mínima de macOS, espacio necesario) y la suma SHA-256 del Paquete_de_Instalación.
2. THE landing SHALL incluir un instructivo de no más de cinco pasos, con capturas, para abrir una app sin firma en la versión vigente de macOS: abrir, ver el aviso y usar «Abrir de todos modos» en Ajustes del Sistema → Privacidad y seguridad.
3. THE landing SHALL enlazar la extensión en Chrome Web Store y la política de privacidad.
4. THE Lugar_de_Descarga SHALL ser público y gratuito, y SHALL NOT exponer el repositorio privado de código. Opción recomendada, pendiente de confirmación del dueño: un repositorio público de GitHub dedicado a la landing (GitHub Pages) y a las versiones (Releases).
5. THE Paquete_de_Instalación SHALL generarse con un comando reproducible que deje el `.dmg`, el `.zip` y sus sumas SHA-256, como `electron-builder` en APX.

### Requisito 12: Extensión lista para Chrome Web Store

**Historia de Usuario:** Como usuario, quiero instalar la extensión buscándola en Chrome Web Store y que se conecte sola a mi Sauri.

#### Criterios de Aceptación

1. THE extensión SHALL funcionar sin pantalla de login. WHEN la App_Sauri está abierta, THE extensión SHALL emparejarse con ella sin pedir correo ni contraseña.
2. IF la App_Sauri no está abierta, THEN THE extensión SHALL mostrar «Abre Sauri en tu Mac para grabar o ver tus reuniones», y SHALL conservar en cola las grabaciones pendientes de subir hasta que la App_Sauri responda.
3. THE extensión SHALL usar una sola dirección del Núcleo_Local, configurada en un solo lugar del código, en vez de las direcciones fijas repetidas de `core/api/client.ts:9`, `SidePanelApp.tsx` y `DetailApp.tsx`.
4. THE manifiesto SHALL declarar solo los permisos que el código usa. `notifications` SHALL quitarse mientras no exista una llamada a `chrome.notifications`.
5. THE entrega SHALL incluir, en español y en inglés, el texto de la ficha de la tienda, la justificación de cada permiso y de los accesos a `meet.google.com` y `localhost`, capturas reales y una política de privacidad publicada en el Lugar_de_Descarga. La política SHALL decir que el audio y las transcripciones no salen del Mac salvo que el usuario configure un proveedor externo.
6. THE API SHALL aceptar como Origen_Autorizado el identificador que asigne Chrome Web Store, además del identificador de desarrollo `ilnkkojmkfnbdilogldabpodoobfigce`.
7. THE cuenta de desarrollador de Chrome Web Store, su pago único y la publicación SHALL quedar a cargo del dueño. La entrega SHALL dejarle el paquete `.zip` de la extensión y los textos listos para subir.

### Requisito 13: Traslado de los datos actuales del dueño

**Historia de Usuario:** Como dueño, quiero pasar mis reuniones de la instalación con Docker a la app nueva sin perder ninguna.

#### Criterios de Aceptación

1. THE entrega SHALL incluir una herramienta de uso único que copie la base de datos y los archivos de la Instalación_Docker_del_Dueño a las Rutas_de_Usuario de la App_Sauri.
2. WHEN termina el traslado, THE herramienta SHALL comparar origen y destino: el número de filas por tabla, y el número de archivos con su tamaño y suma. SHALL informar cualquier diferencia.
3. THE fila del administrador actual SHALL pasar a ser el Usuario_Local, de modo que todas las reuniones, plantillas y ajustes de motores conserven su dueño.
4. THE herramienta SHALL NOT modificar ni borrar la Instalación_Docker_del_Dueño. Retirarla después SHALL requerir la autorización expresa del dueño.
5. IF hay reuniones procesándose en la Instalación_Docker_del_Dueño, THEN THE herramienta SHALL negarse a empezar.

### Requisito 14: Verificación y documentación

**Historia de Usuario:** Como dueño, quiero saber qué se probó de verdad antes de compartir Sauri con mis compañeros.

#### Criterios de Aceptación

1. THE pruebas del backend SHALL pasar contra el Núcleo_Local nuevo (base de datos, cola y almacén reales, no simulados), incluida una versión de `tests/integration/test_pipeline_e2e.py` que no toque datos del dueño.
2. THE entrega final SHALL incluir una instalación limpia en un usuario nuevo de macOS, sin herramientas de desarrollador: descarga desde el Lugar_de_Descarga, Configuración_Inicial, instalación de modelos recomendados y una reunión grabada con la extensión, transcrita, con hablantes y resumen.
3. THE documentación (`AGENTS.md`, `docs/architecture/overview.md`, `docs/operations/`) SHALL describir la arquitectura sin Docker, y dejar `local-platform-deployment` marcada como reemplazada.
4. THE entrega SHALL registrar por separado las pruebas automáticas, la instalación limpia, el traslado de datos del dueño y la aceptación del dueño. Ninguna de ellas sustituye a las otras.
