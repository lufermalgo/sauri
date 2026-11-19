# Requisitos — Rediseño de Ajustes: modelos por proceso y proveedores (Sauri 0.2.0)

## Introducción

Hoy Ajustes muestra, para transcripción, hablantes y resumen, todos los modelos del catálogo (instalados o no) y, en «Motores y modelos», una tarjeta por cada tipo de proveedor aunque el usuario no lo use. El dueño pidió (19/11/2026) que Ajustes muestre solo lo que el usuario tiene y ofrezca «Agregar» para lo demás. Sauri corre en el Mac del usuario; hay dos formas de procesar: **local** (modelos que se descargan al equipo) y **remota** (proveedores que el usuario vincula).

**Idea fuerza:** ver solo lo instalado y lo vinculado; todo lo demás se agrega con un botón, con a lo sumo dos sugerencias según el hardware y una vía «Otro» acotada y verificada.

**Alcance:** vista por proceso de modelos locales instalados; diálogo «Agregar» (2 sugerencias + «Otro»); descarga de un modelo propio desde Hugging Face con verificación; pestañas Modelos/Plantillas en Resumen; «Motores y modelos» con tarjetas solo de proveedores vinculados + tarjeta «Agregar» con lista de proveedores y logos.

**No-alcance:** Windows y Linux (el diseño no debe impedirlos); cuentas, claves o inicio de sesión de Hugging Face; modelos con acceso restringido (gated); «Otro» para hablantes; ejecutar o importar código descargado; cambios a los contratos de los motores.

**Dependencias:** `model-engines` (catálogo, trabajos de instalación, `LocalModel`), `DESIGN.md` y la paleta Índigo, `local_models.py` del host-engine (`/local/models`, `/local/models/{id}/install|verify`, `/local/jobs/{id}`).

## Glosario

- **Proceso**: transcripción (`transcription`), hablantes (`diarization`) o resumen (`summary`).
- **Modelo_Instalado**: modelo local presente en disco (estado instalado, activo o por verificar).
- **Sugerido**: modelo del catálogo no instalado que el hardware detectado soporta; `recommended` primero.
- **Modelo_Propio**: modelo que el usuario descarga desde Hugging Face y que no está en el catálogo fijado.
- **Proveedor_Vinculado**: proveedor externo ya configurado por el usuario.

## Requisitos

### R1 — Vista por proceso: solo lo instalado

**Historia:** Como usuario quiero ver en cada proceso únicamente los modelos que tengo, para entender qué usa Sauri sin ruido.

1. WHEN el usuario abre Transcripción, Hablantes o Resumen→Modelos, THE Ajustes SHALL listar solo los Modelo_Instalado de ese proceso, cada uno con nombre, peso en disco y estado (Activo, Instalado, Verificando, Por verificar).
2. THE Ajustes SHALL NOT listar modelos no instalados ni componentes de soporte (motores gestionados, VAD) como filas del proceso.
3. WHEN un Modelo_Instalado no es el activo, THE fila SHALL ofrecer «Usar este», «Verificar» y «Quitar» (este último bloqueado, con motivo, si el modelo está en uso).
4. IF no hay ningún Modelo_Instalado para el proceso, THEN THE Ajustes SHALL mostrar un estado vacío con «Agregar» como acción principal.
5. WHEN un modelo cambia entre «Por verificar» y «Activo» tras una verificación, THE fila SHALL reflejarlo sin recargar la página.

### R2 — Agregar un modelo

**Historia:** Como usuario quiero agregar un modelo con un botón, viendo solo opciones razonables para mi equipo.

1. THE Ajustes SHALL mostrar un botón «Agregar» por proceso que abre un diálogo.
2. THE diálogo SHALL mostrar a lo sumo dos Sugerido, ordenados con el recomendado primero, cada uno con nombre, peso, motivo de la recomendación y «Instalar».
3. WHERE el proceso es transcripción o resumen, THE diálogo SHALL ofrecer además «Otro»; para hablantes SHALL NOT ofrecerlo.
4. WHILE un modelo se descarga, THE diálogo/fila SHALL mostrar progreso y permitir cancelar; al terminar, el modelo aparece como Modelo_Instalado sin cerrar sesión ni recargar.
5. IF no hay Sugerido que el hardware soporte, THEN THE diálogo SHALL decirlo y dejar solo «Otro» (si aplica).
6. THE descarga de modelos del catálogo y de Hugging Face público SHALL NOT requerir cuenta, clave ni inicio de sesión.

### R3 — «Otro»: modelo propio desde Hugging Face

**Historia:** Como usuario avanzado quiero traer otro modelo, sin poner en riesgo mi equipo.

1. THE campo de «Otro» SHALL aceptar un repositorio (`owner/repo`) o una URL de `huggingface.co`/`hf.co` (repo, `blob` o `resolve`); cualquier otro host SHALL rechazarse con un mensaje claro.
2. WHEN el usuario confirma, THE Servicio_Anfitrión SHALL resolver el repositorio a una revisión (commit) fija y listar los archivos compatibles con el proceso: `.gguf` para resumen; `ggml-*.bin` para transcripción. Si hay varios, el usuario elige uno viendo su peso.
3. THE Servicio_Anfitrión SHALL tomar el SHA-256 y el tamaño del archivo de los metadatos LFS de Hugging Face, verificar el archivo descargado contra ese SHA-256 y descartarlo si no coincide.
4. IF el repositorio es privado o restringido (401/403) o no tiene archivos compatibles, THEN THE diálogo SHALL decirlo con un motivo simple y no ofrecer descarga.
5. THE Servicio_Anfitrión SHALL NOT ejecutar, importar ni cargar como código nada descargado; solo archivos de pesos, tratados como datos.
6. THE descarga SHALL comprobar espacio libre antes de empezar y respetar el mismo tope de trabajo único que las demás instalaciones.
7. WHEN el Modelo_Propio queda instalado, THE fila SHALL mostrar la etiqueta «Personalizado» y su origen (repositorio y revisión); IF el usuario lo activa y el motor no logra cargarlo, THEN THE sistema SHALL volver al modelo activo anterior y mostrar el motivo.
8. THE Modelo_Propio SHALL persistir en un registro de usuario junto a los modelos y sobrevivir a actualizaciones de Sauri; THE «Quitar» SHALL borrar el archivo y su registro.

### R4 — Resumen: pestañas Modelos y Plantillas

1. THE sección Resumen SHALL tener dos pestañas: «Modelos» (R1–R3 para resumen y la elección local/remota existente) y «Plantillas» (el contenido actual de plantillas y categorías).
2. THE pestaña elegida SHALL conservarse al navegar dentro de Ajustes durante la sesión; la inicial SHALL ser «Modelos».
3. THE pestañas SHALL ser navegables con teclado y anunciarse a lectores de pantalla (`role=tablist`).

### R5 — Motores y modelos: solo lo vinculado

**Historia:** Como usuario quiero ver mis proveedores y agregar otros cuando los necesite.

1. THE vista SHALL mostrar tarjetas únicamente de Proveedor_Vinculado, más una tarjeta «Agregar».
2. WHEN el usuario pulsa «Agregar», THE Ajustes SHALL abrir una lista de los proveedores compatibles, cada uno con su logo y nombre, y al elegir uno SHALL abrir el diálogo de configuración existente.
3. THE tarjetas «Sin configurar» (punteadas, una por tipo) SHALL eliminarse.
4. THE lista SHALL mostrar un logo para cada tipo; IF no existe marca oficial utilizable, THEN SHALL usar un glifo neutro y reconocible (no iniciales ni letras sueltas). Las marcas solo identifican al proveedor (uso nominativo) y no se inventan ni se redibujan.
5. WHEN no hay Proveedor_Vinculado, THE vista SHALL explicar en una frase que todo se procesa en el Mac y mostrar «Agregar».

### R6 — No funcionales

1. THE textos SHALL estar en español e inglés, sin tecnicismos, con voz Sauri; THE controles SHALL cumplir WCAG 2.1 AA (foco visible, nombres accesibles, contraste con los tokens Índigo).
2. THE cambios SHALL funcionar en claro y oscuro y a 600 px de ancho mínimo de ventana.
3. THE capa visual SHALL usar los tokens de `DESIGN.md`; SHALL NOT agregar colores sueltos.
4. THE backend nuevo SHALL tener pruebas unitarias (resolución de URL, rechazo de hosts, verificación de hash, espacio insuficiente) sin acceso a Internet (servidor simulado).

## Criterios de aceptación globales

- Un usuario con un solo modelo de resumen instalado ve exactamente una fila en Resumen→Modelos y un botón «Agregar».
- «Agregar» en resumen muestra ≤ 2 sugerencias + «Otro»; en hablantes, ≤ 2 sugerencias sin «Otro».
- Pegar `https://huggingface.co/<owner>/<repo>` de un repo GGUF público descarga, verifica y deja el modelo como «Personalizado»; pegar cualquier otro dominio falla con mensaje claro.
- «Motores y modelos» sin proveedores muestra solo la tarjeta «Agregar»; con uno vinculado, esa tarjeta más la del proveedor.
