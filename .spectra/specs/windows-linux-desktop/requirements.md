# Requisitos — Sauri como app de escritorio para Windows y Linux

## Introducción

Hoy Sauri es una app de escritorio solo para Mac con chip M (spec `mac-desktop-app`, versión 0.2.2). El dueño la usa a diario y quiere compartirla con compañeros. Muchos usan Windows y algunos Linux. El inventario del código del 19/11/2026 muestra que lo exclusivo de Mac está concentrado en tres sitios:

- **La construcción del runtime.** `desktop/scripts/build-runtime.sh` exige Darwin arm64 y compila con Metal. Reubica bibliotecas Mach-O y bloquea dependencias para `aarch64-apple-darwin`.
- **El proceso principal de Electron.** Usa rutas en `~/Library`, sockets Unix para PostgreSQL y grupos de procesos POSIX. Su actualizador reemplaza la `.app` con `ditto` y `plutil`, y su desinstalador solo acepta rutas de `~/Library`.
- **Los motores con Core ML.** Son Senko (hablantes) y Parakeet vía FluidAudio (transcripción rápida).

El backend FastAPI, el portal web, la cola sobre PostgreSQL y la extensión de Chrome son casi portables. Aun así, hay fallos que rompen Windows desde el arranque: `fcntl` en `chatgpt_login.py`, `os.O_NOFOLLOW` y `os.fchmod` en descargas y secretos, `os.killpg` y `loop.add_signal_handler` en procesos, `uvloop` sin marcador de plataforma, y un entorno de procesos sin `SYSTEMROOT` ni `USERPROFILE`.

La investigación de motores del mismo día ofrece un camino sin torch para todas las piezas:

- **Transcripción y resúmenes.** whisper.cpp y llama.cpp se compilan con un backend por biblioteca (CUDA, Vulkan y CPU) y eligen el disponible al arrancar.
- **Parakeet.** whisper.cpp ya trae `parakeet-cli` con pesos GGUF oficiales; sherpa-onnx es la alternativa madura en CPU.
- **Hablantes.** Senko corre en Windows y Linux, pero su ruta de GPU arrastra torch (unos 3,4 GB). Los dos modelos que usa existen en ONNX: la segmentación pyannote 3.0 y CAM++ `sv_zh_en_16k-common_advanced`. Por eso puede correr con onnxruntime en CPU conservando su agrupación y el ajuste `mer_cos 0.78` (PR #1269).

Para firmar el instalador, el servicio barato de Microsoft (Artifact Signing) no está disponible en Colombia, así que firmar exige un certificado OV de US$150–300 al año. Windows 11 con Smart App Control encendido bloquea por completo las apps sin firma.

**Idea fuerza:** un compañero con Windows o Linux descarga Sauri desde la misma landing, lo instala sin permisos de administrador ni herramientas de desarrollador y graba su primera reunión. Todo se procesa en su equipo, con la tarjeta gráfica que tenga, y la calidad es la misma que en Mac.

**Decisiones del dueño (conversación del 19/11/2026):**
- Windows primero y Linux después.
- Sin firma de código por ahora. Se revisa antes de abrir Sauri a más gente.
- No se sabe cuántos compañeros usan cada sistema, así que se planea con Windows como el más usado.
- Los paquetes se construyen y prueban en las máquinas Windows y Linux de GitHub, como hace APX.
- La verificación con tarjeta NVIDIA se hace en el PC real de un compañero, que será el primer probador.
- La app detecta si el equipo tiene NVIDIA u otra tarjeta (AMD o Intel) y se adapta.

**Alcance:**
- La app de escritorio para Windows 10/11 x64 y Linux x64 (Ubuntu 22.04 y 24.04), con las mismas funciones que la de Mac: portal, extensión, ajustes, modelos locales, proveedores externos, actualizaciones y desinstalación.
- La detección del equipo y el nivel de aceleración: NVIDIA, Vulkan o solo CPU.
- Los motores sin Core ML ni torch.
- La construcción reproducible de los paquetes y sus pruebas automáticas en GitHub.
- La landing con descarga por sistema.
- La extensión sin textos que asuman Mac.
- Que la versión de Mac no empeore en nada.

**Fuera de alcance:**
- Windows o Linux en procesadores ARM.
- Mac con procesador Intel.
- Distribuciones distintas de Ubuntu 22.04 y 24.04, aunque pueden funcionar sin garantía.
- Paquetes AppImage, RPM, Flatpak, Snap y Microsoft Store/MSIX.
- La firma de código en Windows y la firma GPG de un repositorio APT.
- torch, CUDA para la detección de hablantes y DirectML.
- Servidor central o varios usuarios.
- Cambios en la calidad de transcripción, hablantes o resúmenes más allá de igualar la de Mac.
- Telemetría de uso.

## Glosario

- **Plataforma_Destino**: Windows 10 22H2 o Windows 11 en x64, o Ubuntu 22.04 o 24.04 en x64.
- **App_Sauri_Windows** y **App_Sauri_Linux**: la aplicación de escritorio para cada Plataforma_Destino, con el mismo código de Electron, portal, núcleo y motores que la de Mac, salvo las capas por plataforma.
- **App_Sauri_Mac**: la app actual para Mac con chip M (spec `mac-desktop-app`).
- **Paquete_Windows**: el instalador `.exe` (NSIS) por usuario, sin administrador, con su suma SHA-256 publicada.
- **Paquete_Linux**: el paquete `.deb` para Ubuntu 22.04 y 24.04, con su suma SHA-256 publicada.
- **Runtime_por_Plataforma**: el conjunto de binarios y entornos que la app lleva dentro para una Plataforma_Destino: Python, PostgreSQL, ffmpeg, whisper.cpp, llama.cpp y las dependencias de Python bloqueadas para esa plataforma. Lleva un manifiesto con versiones y sumas.
- **Nivel_de_Aceleración**: cómo usa el equipo su tarjeta gráfica para transcribir y resumir:
  - **NVIDIA_CUDA**: tarjeta NVIDIA con driver compatible y memoria de video suficiente.
  - **Vulkan**: tarjeta AMD o Intel, o NVIDIA sin driver compatible, con soporte Vulkan.
  - **Solo_CPU**: sin tarjeta utilizable.
- **Motor_de_Hablantes_ONNX**: la detección de hablantes de Senko con su VAD, su subsegmentación y su agrupación (`mer_cos 0.78`), cuya inferencia corre con onnxruntime en CPU en lugar de Core ML o torch.
- **Almacén_de_Secretos**: dónde guarda la app las claves de proveedores externos y sus credenciales internas. Es el Llavero en Mac, un archivo cifrado con DPAPI en Windows y libsecret en Linux.
- **Máquinas_de_CI**: las máquinas Windows y Linux que GitHub Actions aloja (sin GPU), donde se construyen los paquetes y corren las pruebas automáticas.
- **Probador_con_NVIDIA**: el compañero del dueño que prueba las versiones de Windows en su PC con tarjeta NVIDIA antes de publicarlas.
- **Conjunto_de_Referencia**: las grabaciones que se usan para comparar calidad entre plataformas, con hablantes conocidos:
  - CharlaSupplyChain_1: 4 personas.
  - Kelyn: 2 personas.
  - Nutresa-Pozuelo: 4 grupos.
  - Las dos de Argos Centroamérica: 2 personas cada una.
  - ArgosOKRs.
  - La grabación corta de una persona del 19/11/2026.

  Viven en la carpeta privada del dueño y nunca entran al repositorio ni a las Máquinas_de_CI.
- **Grabación_Sintética**: un audio corto generado para pruebas automáticas con voces sintéticas de dos hablantes. No contiene datos de personas y sí puede vivir en el repositorio o en las Máquinas_de_CI.

## Requisitos

### Requisito 1: Instalar sin herramientas de desarrollador ni permisos de administrador

**Historia de Usuario:** Como compañero del dueño con Windows o Linux, quiero instalar Sauri con un instalador normal, para usarlo sin saber de programación.

#### Criterios de Aceptación

1. THE Paquete_Windows SHALL instalar la App_Sauri_Windows para el usuario actual en `%LOCALAPPDATA%`, sin pedir permisos de administrador, y SHALL crear su acceso en el menú Inicio.
2. THE Paquete_Linux SHALL instalarse con el instalador de software de Ubuntu o con `apt install ./archivo.deb`. Es el único paso que pide la contraseña del sistema, que Ubuntu exige para cualquier `.deb`.
3. WHEN se instala en un equipo sin Python, Node, Visual Studio, compiladores, CUDA Toolkit, Docker ni WSL, THE App_Sauri_Windows y THE App_Sauri_Linux SHALL iniciar su núcleo y sus motores sin abrir una terminal.
4. THE App_Sauri_Windows y THE App_Sauri_Linux SHALL NOT compilar código, ejecutar `pip` contra Internet ni instalar drivers en el equipo del usuario.
5. WHEN la app descarga algo durante el primer uso (modelos o componentes), THE App_Sauri SHALL comprobar la suma SHA-256 fijada en el catálogo antes de usarlo, igual que en Mac.
6. THE Runtime_por_Plataforma SHALL NOT incluir torch.
7. THE landing SHALL mostrar el tamaño de descarga y el espacio instalado de cada paquete.

**Restricciones:**
- Windows tiene un límite de 260 caracteres por ruta. La ruta más larga dentro de la instalación, desde `%LOCALAPPDATA%`, SHALL caber en 200 caracteres, y una prueba en las Máquinas_de_CI SHALL comprobarlo.

### Requisito 2: Las mismas funciones que en Mac

**Historia de Usuario:** Como usuario de Windows o Linux, quiero las mismas funciones que tiene el dueño en su Mac, para no tener una versión de segunda.

#### Criterios de Aceptación

1. THE App_Sauri_Windows y THE App_Sauri_Linux SHALL ofrecer las funciones de la App_Sauri_Mac 0.2.2:
   - configuración inicial con carpetas propias;
   - portal sin login;
   - grabación con la extensión;
   - subida de archivos;
   - transcripción, hablantes y resúmenes locales;
   - proveedores externos;
   - modelos propios de Hugging Face;
   - revisión de hablantes;
   - ventana «Acerca de» con el estado de los servicios;
   - ícono en la bandeja;
   - actualizaciones;
   - desinstalación.
2. THE textos de la app, del portal y de la extensión SHALL NOT nombrar Mac, macOS, Finder, Llavero ni la barra de menús cuando la app corre en Windows o Linux, y SHALL usar los nombres de cada sistema (Explorador de archivos, Papelera de reciclaje, bandeja del sistema).
3. THE cambios para Windows y Linux SHALL NOT alterar el comportamiento ni la calidad de la App_Sauri_Mac. Su suite de pruebas SHALL seguir en verde, y su paquete SHALL procesar el Conjunto_de_Referencia con los mismos números de hablantes que la 0.2.2.

### Requisito 3: Comprobación del equipo y Nivel_de_Aceleración

**Historia de Usuario:** Como usuario, quiero saber desde el principio si mi equipo sirve y qué tan rápido irá, para no perder tiempo con una instalación que no funcionará.

#### Criterios de Aceptación

1. WHEN la app se abre por primera vez, THE App_Sauri SHALL comprobar el sistema operativo y su versión, la arquitectura x64, la memoria, el espacio libre y las tarjetas gráficas.
2. WHERE hay una tarjeta NVIDIA, THE App_Sauri SHALL leer su nombre, su memoria de video, la versión del driver y su capacidad de cómputo, sin depender de que `nvidia-smi` esté en el PATH.
3. WHERE hay una tarjeta AMD o Intel, THE App_Sauri SHALL leer su nombre y su memoria de video, y comprobar que tiene soporte Vulkan.
4. THE App_Sauri SHALL elegir el Nivel_de_Aceleración así:
   - NVIDIA_CUDA si la tarjeta NVIDIA tiene driver compatible con la versión de CUDA empaquetada;
   - si no, Vulkan si hay un dispositivo Vulkan utilizable;
   - si no, Solo_CPU.
5. THE configuración inicial SHALL explicar en lenguaje simple el Nivel_de_Aceleración elegido y qué esperar. Por ejemplo: «Tu tarjeta NVIDIA hará que una reunión de una hora esté lista en pocos minutos».
6. IF la tarjeta es NVIDIA pero su driver es más antiguo que el mínimo, THEN THE App_Sauri SHALL decir qué versión de driver hace falta y continuar con el siguiente Nivel_de_Aceleración disponible.
7. IF el Nivel_de_Aceleración es Solo_CPU, THEN THE App_Sauri SHALL avisar que procesar será lento, con una estimación por hora de grabación, y ofrecer seguir en modo lento o configurar un proveedor externo.
8. IF el sistema no es una Plataforma_Destino (por ejemplo Windows de 32 bits, Windows en ARM o Windows anterior a 10 22H2), THEN THE App_Sauri SHALL explicarlo y no continuar.
9. WHERE la distribución de Linux no es Ubuntu 22.04 ni 24.04, THE App_Sauri SHALL avisar que no está probada y dejar continuar.

### Requisito 4: Modelos recomendados según el equipo

**Historia de Usuario:** Como usuario, quiero que Sauri me proponga los modelos que mi equipo puede mover bien, para no tener que entender de modelos.

#### Criterios de Aceptación

1. THE catálogo de modelos SHALL poder declarar por entrada para qué sistemas y Niveles_de_Aceleración sirve, y cuánta memoria de video necesita, sin romper las entradas que hoy existen para Mac.
2. THE recomendación SHALL tener en cuenta la memoria de video (además de la memoria del sistema) en NVIDIA_CUDA y Vulkan, y SHALL elegir el modelo de resúmenes más completo que quepa:
   - Qwen3.5-9B con al menos 8 GB de memoria de video;
   - Qwen3.5-4B con menos.
3. WHERE el Nivel_de_Aceleración es NVIDIA_CUDA o Vulkan, THE recomendación SHALL proponer para transcripción el mismo modelo que en Mac (large-v3-turbo q5_0), y no el modelo pequeño que hoy se elige sin Metal.
4. THE ajustes de cada proceso SHALL mostrar el Nivel_de_Aceleración con el que corre cada motor.
5. THE componentes que se descargan por separado (como el de hablantes) SHALL tener una variante por Plataforma_Destino en el catálogo, con su suma SHA-256.

### Requisito 5: Transcripción en Windows y Linux

**Historia de Usuario:** Como usuario, quiero que la transcripción funcione igual de bien que en el Mac del dueño, para confiar en lo que leo.

#### Criterios de Aceptación

1. THE motor de transcripción SHALL usar whisper.cpp en el mismo commit fijado que en Mac, con un solo juego de binarios que lleva los backends CUDA, Vulkan y CPU, y elige el adecuado al arrancar.
2. THE motor de transcripción SHALL usar en Windows y Linux el mismo modelo, el mismo detector de voz y los mismos parámetros que en Mac.
3. WHEN se transcribe el Conjunto_de_Referencia en NVIDIA_CUDA, THE texto SHALL coincidir palabra por palabra en al menos el 97 % con el de la App_Sauri_Mac sobre el mismo audio, una vez normalizada la puntuación.
4. WHERE el equipo usa NVIDIA_CUDA, THE transcripción de una hora de grabación SHALL tardar como máximo 10 minutos en el PC del Probador_con_NVIDIA.
5. WHERE hay una implementación de Parakeet para Windows y Linux, THE App_Sauri SHALL ofrecerla como opción rápida solo si cumple dos condiciones: tiempos por palabra equivalentes a los de FluidAudio en Mac, y diferencia de coincidencia en el Conjunto_de_Referencia no mayor de 2 puntos frente a Parakeet en Mac. Si no, Parakeet SHALL NOT aparecer en esas plataformas.
6. IF la tarjeta se queda sin memoria al transcribir, THEN THE motor SHALL reconocer el error de CUDA o Vulkan (hoy solo reconoce el de Metal), reintentar una vez con el procesador y mostrar la causa en lenguaje simple.

### Requisito 6: Hablantes sin torch y con la misma calidad

**Historia de Usuario:** Como usuario, quiero que Sauri distinga a las personas igual de bien que en Mac, para saber quién dijo qué.

#### Criterios de Aceptación

1. THE Motor_de_Hablantes_ONNX SHALL correr en el procesador en Windows y Linux, con los mismos modelos de segmentación (pyannote 3.0) y de huellas de voz (CAM++ `sv_zh_en_16k-common_advanced`) que Senko, en formato ONNX.
2. THE Motor_de_Hablantes_ONNX SHALL usar la misma subsegmentación, el mismo detector de voz con los mismos parámetros y la misma agrupación de Senko, con `mer_cos 0.78`.
3. WHEN se compara con la App_Sauri_Mac sobre el mismo audio, THE Motor_de_Hablantes_ONNX SHALL producir huellas de voz con similitud de coseno de al menos 0,999 y el mismo número de hablantes en cada grabación del Conjunto_de_Referencia.
4. THE Motor_de_Hablantes_ONNX SHALL procesar una hora de grabación en un máximo de 6 minutos en una máquina Linux de las Máquinas_de_CI de 4 núcleos. El tiempo SHALL quedar registrado en el informe de la prueba.
5. THE Motor_de_Hablantes_ONNX SHALL NOT requerir tarjeta gráfica.

### Requisito 7: Resúmenes en Windows y Linux

**Historia de Usuario:** Como usuario, quiero resúmenes de mis reuniones en mi equipo, aunque no tenga la tarjeta más potente.

#### Criterios de Aceptación

1. THE motor de resúmenes SHALL usar llama.cpp (`llama-server`) en un commit fijado, con backends CUDA, Vulkan y CPU, y los mismos modelos GGUF que en Mac.
2. THE motor de resúmenes SHALL cargar en la tarjeta tantas capas del modelo como quepan en su memoria de video, y el resto en el procesador.
3. WHERE el Nivel_de_Aceleración es Solo_CPU, THE App_Sauri SHALL proponer el modelo 4B y sugerir un proveedor externo para reuniones largas.
4. THE resumen de una reunión del Conjunto_de_Referencia en NVIDIA_CUDA SHALL cumplir las plantillas existentes (formato JSON válido y secciones completas) en las mismas pruebas que se usan en Mac.

### Requisito 8: Núcleo local portable

**Historia de Usuario:** Como usuario, quiero que Sauri arranque, trabaje y se detenga con orden en mi sistema, sin perder reuniones.

#### Criterios de Aceptación

1. THE núcleo SHALL conectarse a su PostgreSQL embebido por TCP en `127.0.0.1` con contraseña, en las tres plataformas, o por socket Unix solo en Mac y Linux, según decida el diseño.
2. THE App_Sauri SHALL detener PostgreSQL con su apagado ordenado (`pg_ctl stop -m fast`), nunca matando el proceso, para que no tenga que recuperarse al siguiente arranque.
3. THE App_Sauri SHALL detener cada motor junto con los procesos que ese motor lanzó:
   - en Windows, con Job Objects u otro mecanismo equivalente que no deje procesos huérfanos;
   - en Linux, con grupos de procesos.
4. THE worker SHALL terminar ordenadamente en las tres plataformas: termina o devuelve a la cola la tarea en curso dentro del tiempo de gracia actual, también en Windows, donde no existen las señales POSIX.
5. THE procesos que lanza la App_Sauri SHALL recibir el entorno mínimo que cada sistema necesita: en Windows `SYSTEMROOT`, `USERPROFILE`, `TEMP` y `PATHEXT`, con las rutas unidas con el separador del sistema. Sin consolas visibles en Windows.
6. WHILE hay reuniones procesándose, THE App_Sauri SHALL impedir que el equipo entre en reposo:
   - en Windows, con `SetThreadExecutionState`;
   - en Linux, con un bloqueo de systemd-logind (`systemd-inhibit` o su equivalente por D-Bus).
7. THE App_Sauri SHALL guardar sus datos internos y registros en las carpetas estándar de cada sistema:
   - Windows: `%APPDATA%` y `%LOCALAPPDATA%`;
   - Linux: `~/.config`, `~/.local/share` y `~/.local/state` según XDG.

   Las Rutas_de_Usuario las sigue eligiendo el usuario.
8. THE código del backend y de los motores SHALL importarse y arrancar en Windows. No debe usar `fcntl`, `os.killpg`, `os.fchmod`, `os.O_NOFOLLOW` ni `loop.add_signal_handler` sin alternativa para Windows, y `uvloop` SHALL quedar fuera de Windows.

### Requisito 9: Puertos locales sin choques

**Historia de Usuario:** Como usuario, quiero que Sauri arranque siempre, aunque mi equipo use puertos para otras cosas.

#### Criterios de Aceptación

1. THE bloque de puertos de la App_Sauri SHALL quedar fuera del rango dinámico de cada Plataforma_Destino: 49152–65535 en Windows, 32768–60999 por defecto en Linux y 49152–65535 en Mac.
2. WHEN la App_Sauri arranca en Windows, THE App_Sauri SHALL comprobar que su bloque no cae en los rangos que Windows reserva (por ejemplo los de Hyper-V y WSL).
3. IF un puerto del bloque está ocupado o reservado, THEN THE App_Sauri SHALL decir qué puerto es y no iniciar a medias.
4. THE extensión SHALL encontrar la app en las tres plataformas sin configuración del usuario, y solo SHALL aceptar respuestas firmadas por Sauri, como hoy.
5. IF cambiar el bloque obliga a una versión nueva de la extensión, THEN esa versión SHALL seguir encontrando a la App_Sauri_Mac 0.2.x mientras sus usuarios actualizan, y su publicación SHALL esperar el OK del dueño.

### Requisito 10: Claves guardadas de forma segura

**Historia de Usuario:** Como usuario, quiero que mis claves de proveedores externos estén protegidas en mi equipo, igual que en el Llavero del Mac.

#### Criterios de Aceptación

1. WHERE la plataforma es Windows, THE Almacén_de_Secretos SHALL cifrar cada clave con DPAPI ligada al usuario de Windows, sin el límite de tamaño del Administrador de credenciales. Las claves de hasta 16 KB SHALL guardarse y leerse sin error.
2. WHERE la plataforma es Linux, THE Almacén_de_Secretos SHALL usar el llavero del escritorio (libsecret o KWallet).
3. IF en Linux no hay llavero disponible, THEN THE App_Sauri SHALL avisarlo y SHALL NOT guardar claves de proveedores externos en texto plano ni con una contraseña fija.
4. THE credenciales internas de la App_Sauri en Windows SHALL quedar en archivos accesibles solo para el usuario, con las ACL de Windows y no con permisos POSIX.
5. THE desinstalación SHALL ofrecer borrar las claves guardadas.

### Requisito 11: Integración con el sistema

**Historia de Usuario:** Como usuario, quiero que Sauri se comporte como una app normal de mi sistema.

#### Criterios de Aceptación

1. THE App_Sauri_Windows y THE App_Sauri_Linux SHALL mostrar un ícono en la bandeja del sistema, visible en temas claros y oscuros, con el mismo menú y estados que en Mac. Al pulsarlo, abren la ventana.
2. WHERE el escritorio de Linux no muestra íconos de bandeja (GNOME sin la extensión de AppIndicator), THE App_Sauri_Linux SHALL seguir funcionando y SHALL ofrecer abrir y salir desde su ventana.
3. THE opción de abrirse al iniciar sesión SHALL funcionar en Windows (elemento de inicio del usuario) y en Linux (archivo de inicio automático de XDG), apagada por defecto.
4. THE ventanas del portal y de «Acerca de» SHALL usar en Windows y Linux la barra de título del sistema, con botones de cerrar, minimizar y maximizar. La barra superior del portal SHALL usar su modo nativo.
5. THE App_Sauri SHALL permitir una sola instancia abierta y SHALL traer al frente la ventana existente si se abre otra vez.
6. THE App_Sauri_Linux SHALL abrirse en Ubuntu 24.04 sin desactivar la protección de procesos de Chrome (sandbox). Para eso instala lo que AppArmor exige.

### Requisito 12: Actualizaciones

**Historia de Usuario:** Como usuario, quiero recibir las versiones nuevas sin reinstalar ni perder mis reuniones.

#### Criterios de Aceptación

1. THE App_Sauri_Windows SHALL buscar, descargar y aplicar versiones nuevas publicadas en el mismo lugar que las de Mac, comprobando su SHA-256, con confirmación del usuario y sin pedir permisos de administrador.
2. THE App_Sauri_Linux SHALL avisar de versiones nuevas y descargarlas. Instalarlas SHALL pedir la contraseña del sistema solo en ese momento, como cualquier `.deb`.
3. WHEN una versión nueva trae migraciones de base de datos, THE App_Sauri SHALL hacer una copia de seguridad antes de migrar y restaurarla si la migración falla, como en Mac.
4. WHILE hay reuniones procesándose, THE App_Sauri SHALL NOT aplicar una actualización y SHALL decir cuántas faltan.
5. THE publicación de cada versión SHALL contener los paquetes de las plataformas que estén listas, y cada app SHALL buscar solo el paquete de su propia plataforma.

### Requisito 13: Desinstalación

**Historia de Usuario:** Como usuario, quiero poder quitar Sauri por completo, o dejar mis grabaciones si quiero conservarlas.

#### Criterios de Aceptación

1. THE App_Sauri_Windows SHALL aparecer en «Aplicaciones instaladas» de Windows y desinstalarse desde ahí o desde sus ajustes.
2. THE App_Sauri_Linux SHALL desinstalarse con el instalador de software de Ubuntu o con `apt remove`, y desde sus ajustes.
3. WHEN se desinstala desde los ajustes, THE App_Sauri SHALL dejar elegir si se borran las Rutas_de_Usuario, y SHALL borrar sus datos internos en las carpetas de cada sistema. Usa las comprobaciones de marcador y enlaces simbólicos que ya existen.
4. THE desinstalación SHALL NOT borrar nada fuera de las carpetas propias de Sauri y de las Rutas_de_Usuario que el usuario confirmó.

### Requisito 14: Instalación sin firma, explicada

**Historia de Usuario:** Como compañero del dueño, quiero saber qué hacer cuando Windows me advierte sobre Sauri, para instalarlo con confianza.

#### Criterios de Aceptación

1. THE landing SHALL explicar, con capturas, cómo continuar cuando Windows muestra «Windows protegió su PC» («Más información» y «Ejecutar de todas formas»).
2. THE landing SHALL explicar que con Smart App Control encendido Windows 11 no deja instalar Sauri por ahora, y cómo saber si está encendido.
3. THE landing SHALL mostrar la suma SHA-256 de cada paquete y cómo comprobarla en Windows (`certutil` o PowerShell) y en Linux (`sha256sum`).
4. THE decisión de firmar SHALL revisarse con el dueño antes de abrir Sauri a personas fuera de su equipo cercano. Hasta entonces, THE paquetes SHALL publicarse sin firma.

### Requisito 15: Landing con descarga por sistema

**Historia de Usuario:** Como visitante, quiero descargar la versión de mi sistema sin equivocarme.

#### Criterios de Aceptación

1. THE landing SHALL ofrecer descargas para Mac, Windows y Linux, cada una con sus requisitos (sistema, memoria, tarjeta gráfica y espacio), su tamaño y su suma.
2. WHEN un visitante abre la landing, THE landing SHALL destacar la descarga de su sistema, sin ocultar las otras.
3. WHILE una plataforma no tiene versión publicada, THE landing SHALL mostrarla como «Próximamente».
4. THE landing SHALL tener una guía de primer uso por sistema y una pregunta frecuente sobre la tarjeta gráfica y los tiempos esperados.

### Requisito 16: Extensión en Windows y Linux

**Historia de Usuario:** Como usuario de Windows o Linux, quiero grabar mis reuniones de Google Meet igual que en Mac.

#### Criterios de Aceptación

1. THE extensión SHALL grabar, subir y abrir el progreso de la reunión en Chrome para Windows y Linux, con las mismas funciones que en Mac.
2. THE textos de la extensión y de su ficha en la tienda SHALL NOT asumir Mac. Por ejemplo, la ayuda del permiso de micrófono SHALL explicar cada sistema.
3. THE publicación de una versión nueva de la extensión SHALL esperar el OK del dueño.

### Requisito 17: Construcción y pruebas en las Máquinas_de_CI

**Historia de Usuario:** Como dueño, quiero que los paquetes de Windows y Linux se construyan y prueben solos, porque nadie en el equipo de desarrollo tiene esos sistemas.

#### Criterios de Aceptación

1. THE Máquinas_de_CI SHALL construir el Runtime_por_Plataforma y el paquete de cada Plataforma_Destino desde commits y versiones fijadas, con un manifiesto de versiones y sumas igual al de Mac.
2. THE Máquinas_de_CI SHALL construir el runtime de Linux sobre Ubuntu 22.04, para que funcione en 22.04 y 24.04.
3. THE Máquinas_de_CI SHALL correr en Windows y Linux las pruebas del backend, del escritorio, del portal y de la extensión que no necesitan hardware especial.
4. THE Máquinas_de_CI SHALL instalar el paquete construido en una máquina limpia de cada plataforma y procesar de punta a punta la Grabación_Sintética en Solo_CPU: arranque, transcripción, hablantes, resumen con el modelo pequeño y apagado ordenado. SHALL fallar si algún paso falla.
5. THE Máquinas_de_CI SHALL comprobar que el paquete no incluye torch, que la ruta más larga cabe en el límite del Requisito 1 y que todos los binarios coinciden con el manifiesto.
6. THE construcción SHALL caber en los minutos gratuitos de GitHub Actions del plan actual. IF un mes va a superarlos, THEN THE equipo SHALL avisar al dueño antes de seguir, porque es un gasto.
7. THE Máquinas_de_CI SHALL NOT recibir el Conjunto_de_Referencia, audios reales ni transcripciones.

### Requisito 18: Verificación con tarjeta NVIDIA en un equipo real

**Historia de Usuario:** Como dueño, quiero que alguien pruebe Sauri en un PC real con NVIDIA antes de compartirlo, porque las máquinas de GitHub no tienen tarjeta gráfica.

#### Criterios de Aceptación

1. BEFORE publicar una versión de Windows, THE Probador_con_NVIDIA SHALL seguir una lista de comprobación escrita para alguien que no es desarrollador:
   - instalación;
   - configuración inicial;
   - Nivel_de_Aceleración detectado;
   - una grabación con la extensión;
   - una subida de archivo;
   - un resumen;
   - una actualización;
   - una desinstalación.
2. THE lista SHALL registrar los tiempos de cada etapa para una grabación de prueba de duración conocida, y el informe SHALL guardarse en `docs/history/` sin datos de la reunión.
3. THE criterios de calidad de los Requisitos 5 y 6 SHALL comprobarse con el Conjunto_de_Referencia en un equipo con NVIDIA. Esa prueba la corre el equipo de desarrollo, con permiso del dueño, en un equipo prestado o en uno alquilado con costo aprobado antes. Las grabaciones nunca salen del control del dueño.
4. IF no hay Probador_con_NVIDIA disponible, THEN THE versión de Windows SHALL publicarse solo como prueba cerrada y con el aviso de que el modo NVIDIA no está verificado.

### Requisito 19: Privacidad igual que en Mac

**Historia de Usuario:** Como usuario, quiero que mis reuniones no salgan de mi equipo salvo que yo elija un proveedor externo.

#### Criterios de Aceptación

1. THE App_Sauri_Windows y THE App_Sauri_Linux SHALL escuchar solo en `127.0.0.1` y aplicar la misma protección local que la App_Sauri_Mac: Host, origen autorizado y credencial local.
2. THE App_Sauri SHALL NOT enviar telemetría de uso ni datos de reuniones. Sus únicas conexiones de red sin intervención del usuario SHALL ser:
   - la búsqueda de versiones nuevas;
   - las descargas de modelos y componentes desde los lugares fijados en el catálogo.
3. THE registros SHALL NOT contener audio, transcripciones, resúmenes ni claves.

### Requisito 20: Orden de entrega

**Historia de Usuario:** Como dueño, quiero ver avances usables pronto, empezando por Windows.

#### Criterios de Aceptación

1. THE trabajo SHALL entregarse en este orden:
   - (1) base portable del núcleo y los motores, probada en las Máquinas_de_CI de Linux y Windows en Solo_CPU;
   - (2) App_Sauri_Windows con NVIDIA_CUDA y Vulkan;
   - (3) App_Sauri_Linux;
   - (4) Parakeet en Windows y Linux, si cumple el Requisito 5.5.
2. WHEN una plataforma cumple sus requisitos y la verificación del Requisito 18, THE equipo SHALL pedir el OK del dueño antes de publicarla en la landing y en las versiones públicas.
3. THE App_Sauri_Mac SHALL seguir recibiendo actualizaciones durante todo el trabajo, sin esperar a Windows ni a Linux.
