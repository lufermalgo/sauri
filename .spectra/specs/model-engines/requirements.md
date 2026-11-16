# Requisitos — Motores y modelos: proveedores externos por proceso y gestión de modelos locales

## Introducción

Sauri procesa cada grabación con tres motores nativos que corren en el Mac del dueño, fuera de Docker (`docs/architecture/overview.md`): transcripción (whisper.cpp, puerto 8001), detección de hablantes (Senko, puerto 8002) y resumen (Qwen3.5-9B sobre llama.cpp, puerto 8003). Hoy el motor es fijo: no hay forma de elegir otro modelo, de usar un servicio externo salvo editando variables de entorno (`SUMMARIZATION_BASE_URL`, `SUMMARIZATION_API_KEY_FILE`, que solo cubren el resumen) ni de instalar un modelo local distinto desde la interfaz. `core-speech-pipeline` (R9.1) dejó esa configuración fuera de alcance a la espera de «una spec posterior con referencia del dueño». El portal tiene ya una consola de configuración (PR #1049) con cuatro categorías planas (Cuenta, Apariencia, Resúmenes, Grabación).

El 16/11/2026 el dueño pidió replicar la sección «Motores y modelos» de APX: cada proceso principal usa los modelos locales por defecto y, una vez que el usuario vincula proveedores externos, elige por proceso qué motor y modelo usar (por ejemplo, redactar los resúmenes con Codex mediante su plan de ChatGPT). Sauri corre en la máquina del propio usuario, así que también debe ayudarlo a elegir un modelo local según su hardware e instalarlo con un botón. El menú de configuración se reorganiza como el de APX, con grupos y un buscador. El dueño decidió: (1) la privacidad se gestiona **por proceso**, con un aviso explícito de qué sale de la máquina y hacia quién, y todo permanece local hasta que el usuario cambie un proceso; (2) el usuario vincula **sus propios** proveedores (Codex con plan de ChatGPT, OpenAI, Anthropic, Gemini, OpenRouter, Ollama o LM Studio locales y cualquier servicio compatible con OpenAI); (3) el almacenamiento de claves lo decide el orquestador; (4) para detectar hablantes se sugieren proveedores especializados (AssemblyAI, Deepgram y similares) y se agrega el método para conectarse a ellos.

**Idea fuerza:** el core sigue siendo local y hexagonal; un proveedor externo es solo otro adaptador detrás de los mismos contratos, que el usuario activa proceso por proceso, sabiendo qué sale de su máquina, con las claves fuera del alcance de Docker, del portal y de los registros.

**Alcance:** vínculo y administración de proveedores; almacenamiento seguro de claves; catálogo de modelos de cada proveedor y prueba de conexión; selección de motor y modelo por proceso con aviso de privacidad y consentimiento; adaptadores externos de transcripción, hablantes y resumen que cumplen los contratos existentes; confiabilidad (errores clasificados, tiempos, cancelación, respaldo local); recomendación, instalación y verificación de modelos locales; reorganización del menú de configuración con buscador; transparencia sobre qué motor produjo cada resultado; vínculo del plan de ChatGPT por la vía oficial de OpenAI, condicionado a una verificación legal.

**No-alcance:** el chat con la grabación (Fase 2 del baseline): solo se reserva su lugar (proceso `chat` oculto hasta que exista su spec); multiusuario y política de acceso; facturación, topes de gasto o precios dentro de Sauri; despliegue en la nube; reconocimiento de identidades entre grabaciones; entrenamiento o ajuste fino de modelos; ejecutar modelos locales en Docker; reemplazar la arquitectura hexagonal o los contratos v2 de los motores.

**Dependencias:** conserva los contratos v2 de ASR y diarización, el resumen con esquema JSON estricto y citas, el bloqueo de un solo trabajo pesado (`engine_slot`) y la autenticación por token de motor de `core-speech-pipeline`; la confiabilidad del resumen sigue lo que resuelva el issue #1045; reutiliza la consola de configuración del PR #1049 y el sistema de diseño de `DESIGN.md`.

## Glosario

- **Proceso**: función de Sauri que usa un modelo. Valores: `transcription` (transcripción), `diarization` (detección de hablantes), `summary` (resumen) y `chat` (futuro, oculto hasta que exista su spec).
- **Motor_Local**: implementación nativa que corre en el Mac del usuario (whisper.cpp, Senko, llama.cpp), sin salida de datos.
- **Proveedor_Vinculado**: servicio externo que el usuario registró en Sauri (tipo, nombre, URL base, clave opcional). Puede estar en Internet (OpenAI, Anthropic…) o ser un servicio local de otra aplicación (Ollama, LM Studio).
- **Ruta_de_Proceso**: elección vigente de un Proceso: Motor_Local o Proveedor_Vinculado, modelo y respaldo local. Se resuelve al inicio de cada intento de procesamiento.
- **Matriz_de_Compatibilidad**: tabla versionada que indica qué tipos de proveedor cumplen el contrato de cada Proceso; un proveedor que no lo cumple no se ofrece para ese proceso.
- **Aviso_de_Privacidad**: texto por Proceso y proveedor que dice qué datos salen de la máquina, hacia quién y bajo qué condiciones ajenas a Sauri; tiene una versión.
- **Consentimiento**: registro con fecha de que el usuario aceptó una versión del Aviso_de_Privacidad para un Proceso y un proveedor concretos.
- **Almacén_de_Secretos**: almacenamiento de claves y tokens de proveedor en el equipo anfitrión (llavero de macOS, con archivo 0600 como alternativa), fuera de PostgreSQL, Docker, el portal y los registros.
- **Referencia_de_Secreto**: nombre opaco con el que la configuración apunta a un secreto sin contenerlo.
- **Servicio_Anfitrión**: proceso nativo local (`host-engine`) que administra secretos, pruebas de conexión, catálogo de modelos e instalación de modelos locales.
- **Catálogo_Local**: lista versionada de modelos locales instalables, con tamaño, SHA-256, revisión fija y requisitos de memoria.
- **Recomendación**: modelo local sugerido para un Proceso a partir del hardware detectado.
- **Procedencia**: dato de qué motor y modelo (local o externo) produjo un resultado.
- **Error_Clasificado**: fallo de proveedor reducido a una clase cerrada (`provider_auth`, `provider_quota`, `provider_rate_limited`, `provider_timeout`, `provider_unavailable`, `provider_bad_request`, `provider_invalid_output`, `provider_context_exceeded`, `provider_unsupported`, `audio_too_large`, `consent_missing`, `secret_unavailable`, `origin_mismatch`) con indicador de reintento.

## Requisitos

### Requisito 1: Todo es local hasta que el usuario cambie un proceso

**Historia de Usuario:** Como dueño, quiero que Sauri no envíe nada fuera de mi Mac mientras yo no lo decida, para mantener la promesa de privacidad del producto.

#### Criterios de Aceptación

1. THE Core_de_Voz SHALL usar el Motor_Local de cada Proceso cuando no exista una Ruta_de_Proceso externa guardada, incluso si hay Proveedores_Vinculados registrados.
2. WHEN el usuario registra o edita un Proveedor_Vinculado sin asignarlo a un Proceso, THE sistema SHALL NOT enviar a ese proveedor audio, transcripciones ni resúmenes; solo las llamadas de prueba, listado de modelos y verificación de la clave que el usuario solicite.
3. THE sistema SHALL NOT enviar a un proveedor externo datos de una reunión salvo mediante una Ruta_de_Proceso con Consentimiento vigente para ese Proceso y ese proveedor.
4. THE sistema SHALL mantener el comportamiento actual (motores en los puertos 8001–8003, contratos v2, `engine_slot`) para todo Proceso en Motor_Local, sin pasos de configuración nuevos para quien no use proveedores externos.
5. FOR ALL reuniones ya procesadas, cambiar la Ruta_de_Proceso SHALL afectar solo al procesamiento posterior y a los reintentos; THE sistema SHALL NOT reprocesar ni modificar resultados existentes.

### Requisito 2: Procesos y compatibilidad de proveedores

**Historia de Usuario:** Como usuario, quiero que Sauri solo me ofrezca para cada proceso los proveedores que realmente funcionan con él, para no configurar algo que luego falla.

#### Criterios de Aceptación

1. THE sistema SHALL ofrecer la Ruta_de_Proceso de tres Procesos visibles (transcripción, hablantes, resumen) y reservar `chat` en el modelo de datos y la Matriz_de_Compatibilidad sin mostrarlo en la interfaz.
2. THE Matriz_de_Compatibilidad SHALL declarar, por tipo de proveedor y Proceso, si lo soporta, la evidencia (documentación oficial consultada con fecha) y las restricciones; un par sin evidencia se declara `no verificado` y no se ofrece.
3. IF una petición asigna a un Proceso un proveedor cuyo tipo no lo soporta, THEN THE API SHALL rechazarla con error de validación y THE pasarela del anfitrión SHALL rechazar una ruta equivalente con `provider_unsupported`.
4. WHERE el Proceso es transcripción, THE sistema SHALL ofrecer solo proveedores que devuelvan marcas de tiempo por palabra, porque el contrato v2 y la atribución por palabra las exigen.
5. WHERE el Proceso es resumen o chat, THE sistema SHALL ofrecer solo proveedores de chat capaces de salida JSON estricta; WHEN el usuario pulsa «Probar conexión», THE Servicio_Anfitrión SHALL comprobar esa capacidad con una petición mínima con esquema.
6. WHERE el Proceso es hablantes, THE sistema SHALL ofrecer Senko local y proveedores especializados que devuelvan etiquetas de hablante con tiempos (AssemblyAI y Deepgram como primeros; otros tipos similares se agregan a la Matriz_de_Compatibilidad con evidencia).

### Requisito 3: Vincular y administrar proveedores

**Historia de Usuario:** Como usuario, quiero vincular mis propios proveedores desde una pantalla de Motores y modelos, para usar mis cuentas y mis modelos.

#### Criterios de Aceptación

1. THE portal SHALL ofrecer una pantalla «Motores y modelos» con una tarjeta por Proveedor_Vinculado y una acción «Agregar proveedor» con los tipos: Codex (plan de ChatGPT), OpenAI, Anthropic, Gemini, OpenRouter, Ollama, LM Studio, compatible con OpenAI, AssemblyAI y Deepgram.
2. THE portal SHALL mostrar en cada tarjeta nombre, tipo, estado como texto (`Activo`, `Sin clave`, `Apagado`, `Sin configurar`) y los Procesos que usan ese proveedor; WHEN el usuario lo apaga o lo elimina, THE sistema SHALL devolver a Motor_Local los Procesos que lo usaban y avisar cuáles.
3. THE diálogo de proveedor SHALL permitir editar nombre, URL base (con valor predefinido por tipo), clave, estado activo y «Probar conexión», y SHALL mostrar qué Procesos admite ese tipo.
4. WHEN el usuario abre «Agregar proveedor», THE Servicio_Anfitrión SHALL detectar Ollama (`127.0.0.1:11434`) y LM Studio (`127.0.0.1:1234`) en el equipo y THE portal SHALL ofrecerlos como encontrados.
5. THE sistema SHALL exigir HTTPS para toda URL base no local y SHALL aceptar `http` únicamente para `127.0.0.1`, `localhost` y `::1`.
6. THE configuración de proveedores y de Procesos SHALL pertenecer al usuario (propietario) y SHALL NOT ser visible ni modificable por otro usuario.

### Requisito 4: Las claves nunca salen del equipo anfitrión

**Historia de Usuario:** Como dueño, quiero que mis claves queden guardadas de forma segura y nadie pueda leerlas después, para que un fallo del portal o de un contenedor no las exponga.

#### Criterios de Aceptación

1. THE sistema SHALL guardar claves y tokens de proveedor únicamente en el Almacén_de_Secretos del anfitrión, y la configuración en PostgreSQL SHALL contener solo la Referencia_de_Secreto, un indicador `key_set` y, si la clave tiene al menos 12 caracteres, sus últimos 4.
2. THE sistema SHALL NOT devolver el valor de una clave en ninguna respuesta de la API, del Servicio_Anfitrión ni del portal; el portal SHALL mostrar «Guardada ••••1234» y permitir solo reemplazarla o quitarla.
3. THE worker de procesamiento SHALL NOT recibir claves de proveedor; las pasarelas del anfitrión SHALL leerlas del Almacén_de_Secretos en el momento de la llamada.
4. THE sistema SHALL NOT escribir claves, tokens, encabezados de autorización ni contenido de reuniones en registros, errores, métricas o diagnósticos copiados.
5. THE Almacén_de_Secretos SHALL vincular cada clave al origen (`esquema://host:puerto`) para el que se guardó, y THE pasarela SHALL rechazar con `origin_mismatch` una ruta cuya URL base tenga otro origen.
6. IF el llavero no está disponible, THEN THE Almacén_de_Secretos SHALL usar un archivo con permisos 0600 en `~/.config/sauri/secrets/` y el portal SHALL indicarlo; IF ninguno funciona, THEN THE sistema SHALL informar `secret_unavailable` sin degradar a almacenamiento en base de datos.
7. THE canal de administración del Servicio_Anfitrión SHALL aceptar solo conexiones de `127.0.0.1` con un token de administración distinto del token de motor, disponible solo para la API y no para el worker.

### Requisito 5: Catálogo de modelos de cada proveedor y prueba de conexión

**Historia de Usuario:** Como usuario, quiero ver los modelos que mi proveedor ofrece y comprobar que la conexión funciona, para elegir con confianza.

#### Criterios de Aceptación

1. WHEN el usuario abre el selector de modelos de un Proceso con un proveedor activo, THE Servicio_Anfitrión SHALL pedirle al proveedor su lista de modelos, filtrar los que no sirven para ese Proceso, y THE sistema SHALL conservar el resultado 24 horas con una acción «Volver a pedir».
2. IF el proveedor no ofrece lista de modelos o falla, THEN THE portal SHALL permitir escribir el nombre del modelo a mano.
3. WHEN el usuario pulsa «Probar conexión», THE Servicio_Anfitrión SHALL informar «Responde» o «No responde» con la causa clasificada y el tiempo de respuesta, sin mostrar la clave.
4. THE sistema SHALL ofrecer un modelo inicial sugerido («Auto») por tipo de proveedor y Proceso, editable por el usuario.

### Requisito 6: Elegir motor y modelo por proceso

**Historia de Usuario:** Como usuario, quiero decidir para cada proceso si usa mi modelo local o un proveedor y modelo concretos, para equilibrar privacidad, calidad y costo.

#### Criterios de Aceptación

1. THE portal SHALL mostrar, en las categorías Transcripción, Hablantes y Resúmenes, un selector de motor y modelo con «Local (recomendado)» como primera opción y, a continuación, los modelos locales instalados y los de cada proveedor activo compatible.
2. WHEN el usuario cambia un Proceso a un proveedor externo, THE portal SHALL mostrar el Aviso_de_Privacidad y SHALL guardar el cambio solo después de que el usuario lo acepte.
3. WHEN el usuario vuelve un Proceso a Motor_Local, THE sistema SHALL guardarlo sin pedir confirmación y marcar el Consentimiento previo como revocado.
4. THE Ruta_de_Proceso SHALL incluir la opción «Si el proveedor falla, usar el modelo local»; THE sistema SHALL NOT encadenar un proveedor externo con otro ni pasar de un motor local a uno externo.
5. THE sistema SHALL aplicar un cambio de Ruta_de_Proceso al siguiente intento de procesamiento sin reiniciar contenedores ni motores.
6. THE resumen SHALL conservar las plantillas existentes: THE categoría Resúmenes SHALL mostrar la elección de motor y modelo antes de las plantillas.

### Requisito 7: Aviso de privacidad por proceso y consentimiento

**Historia de Usuario:** Como dueño, quiero que antes de enviar algo fuera de mi equipo el usuario sepa qué sale y a quién, para que decida informado.

#### Criterios de Aceptación

1. THE Aviso_de_Privacidad de transcripción y hablantes SHALL decir que se envía el **audio completo** de cada reunión (normalizado y comprimido) al proveedor nombrado; el de resumen y chat, que se envía el **texto de la transcripción** con etiquetas de hablante y las instrucciones de la plantilla (y, en chat, las preguntas del usuario); y todos SHALL nombrar al proveedor y su dirección, decir que el tratamiento posterior depende de las condiciones de ese proveedor y no de Sauri, y que lo que no pase por ese Proceso sigue local.
2. THE sistema SHALL registrar cada Consentimiento con propietario, Proceso, proveedor, versión del aviso y marca de tiempo, y SHALL exigir uno vigente para que una Ruta_de_Proceso externa se resuelva.
3. WHEN cambie el proveedor de un Proceso o la versión del Aviso_de_Privacidad, THE sistema SHALL pedir un Consentimiento nuevo; cambiar solo el modelo dentro del mismo proveedor SHALL NOT pedirlo.
4. IF falta el Consentimiento al resolver una ruta, THEN THE sistema SHALL detener el intento con `consent_missing` sin contactar al proveedor y THE reunión SHALL quedar en un estado reintentable.
5. THE portal SHALL mostrar de forma visible en cada categoría de Proceso si hoy usa un motor local o un proveedor externo y qué sale de la máquina.
6. THE aviso SHALL estar redactado en español, sin tecnicismos, y SHALL vivir en el módulo de textos del producto.

### Requisito 8: Transcripción externa que cumple el contrato

**Historia de Usuario:** Como usuario, quiero poder transcribir con un proveedor externo sin que cambie lo que muestra el portal, para comparar calidad y velocidad.

#### Criterios de Aceptación

1. THE adaptador externo de transcripción SHALL devolver el contrato v2 (segmentos, palabras con inicio, fin y probabilidad si existe, idioma, `engine` con proveedor y modelo y `diagnostics`), de modo que workers, atribución por palabra y portal no cambien.
2. IF el proveedor no devuelve marcas por palabra para un segmento con texto, THEN THE adaptador SHALL fallar con `no_word_timestamps` y SHALL NOT fabricar tiempos.
3. THE adaptador SHALL preparar el audio una sola vez (normalización existente), comprimirlo y, si el proveedor tiene límite de tamaño o duración, dividirlo en tramos en pausas de voz con la misma lógica de VAD del motor local, y corregir los tiempos de cada tramo con su desfase.
4. WHERE el proveedor procesa de forma asíncrona (envío y consulta), THE adaptador SHALL respetar el límite de 1200 s por llamada de motor (`ENGINE_CALL_TIMEOUT_S`) y cancelar el trabajo remoto al agotarse o al desconectarse el cliente cuando el proveedor lo permita.
5. THE adaptador SHALL aplicar el idioma configurado de Sauri (`es` por defecto, o `auto`) y SHALL persistir el idioma devuelto.
6. THE transcripción externa SHALL pasar las mismas pruebas de contrato que el motor local (palabras monótonas y dentro de la duración).

### Requisito 9: Detección de hablantes con proveedores especializados

**Historia de Usuario:** Como usuario, quiero poder usar un servicio especializado para identificar hablantes, para mejorar casos que el modelo local resuelve peor.

#### Criterios de Aceptación

1. THE adaptador externo de hablantes SHALL convertir la respuesta del proveedor (etiquetas por palabra o por tramo con tiempos) en segmentos `SpeakerSegment(raw_label, start_ms, end_ms)` del contrato v2, con `speaker_count` igual al número de etiquetas distintas, sin filtrar turnos breves.
2. THE adaptador SHALL descartar el texto que devuelva el proveedor y SHALL NOT persistirlo ni registrarlo; solo conserva etiquetas y tiempos.
3. WHEN el proveedor devuelva etiquetas distintas en cada llamada (A, B…), THE sistema SHALL tratarlas como etiquetas anónimas de esa diarización, sin identidad entre grabaciones.
4. IF el usuario asigna al mismo proveedor transcripción y hablantes, THEN THE portal SHALL advertir que el audio se enviará dos veces (una por Proceso) y que cada envío se cobra por separado.
5. THE portal SHALL advertir que la calidad de un proveedor externo no está validada contra Senko con las grabaciones del dueño y que Sauri no la garantiza.
6. THE adaptador SHALL aplicar las mismas reglas de preparación, división, tiempos y cancelación del Requisito 8.

### Requisito 10: Resumen y chat con proveedores de chat

**Historia de Usuario:** Como usuario, quiero redactar el resumen con el modelo de mi proveedor sin perder las citas ni la estructura, para que el borrador siga siendo verificable.

#### Criterios de Aceptación

1. THE pasarela de resumen SHALL aceptar la misma petición de chat compatible con OpenAI que hoy envía el worker y traducirla al transporte del proveedor (`openai-chat`, `anthropic-messages`, `chatgpt-responses`), devolviendo siempre una respuesta con la forma de chat compatible con OpenAI.
2. THE traducción SHALL conservar el esquema JSON estricto del resumen; WHERE el proveedor soporte solo un subconjunto del esquema (por ejemplo, sin `maxItems`), THE adaptador SHALL adaptarlo y THE sistema SHALL validar localmente la respuesta contra el esquema original y las citas existentes antes de aceptarla.
3. IF la respuesta no cumple el esquema o no tiene citas válidas, THEN THE sistema SHALL tratarla como `provider_invalid_output` sin guardar texto sin fuente.
4. THE resumen externo SHALL seguir marcándose como borrador pendiente de revisión y SHALL conservar la política de «sin truncar»: IF la transcripción no cabe en el contexto del modelo elegido, THEN THE sistema SHALL fallar con `provider_context_exceeded` sin recortar pasajes.
5. THE adaptador SHALL tratar el texto de la transcripción como datos no confiables, con las mismas instrucciones de sistema que el resumen local.
6. WHERE el Proceso es `chat` (futuro), THE diseño SHALL admitir respuestas en flujo por el mismo transporte sin cambiar los demás contratos.

### Requisito 11: Fiabilidad, cancelación y respaldo local

**Historia de Usuario:** Como usuario, quiero que un proveedor caído, una clave vencida o un límite de cuota me expliquen qué pasó y no dejen la reunión colgada ni cobros huérfanos.

#### Criterios de Aceptación

1. THE pasarelas SHALL clasificar todo fallo de proveedor en un Error_Clasificado con indicador `retryable` y, si el proveedor lo informa, `retry_after`; THE worker SHALL usar ese indicador para el reintento y para la causa que muestra el portal en lenguaje claro.
2. THE sistema SHALL aplicar tiempos máximos por Proceso (conexión, primer byte, silencio entre eventos y total) configurables por proveedor, siempre dentro de los límites existentes de espera del bloqueo (120 s) y de llamada (1200 s) y del consumo de la cola.
3. WHEN el worker cancele o cierre la conexión de una petición, THE pasarela SHALL cancelar la petición al proveedor y, si el proveedor lo permite, el trabajo remoto, de modo que no queden generaciones ni cobros huérfanos.
4. THE pasarela SHALL permitir una sola petición externa activa por Proceso y reunión, en línea con la solicitud única del resumen (#1045), y SHALL respetar `Retry-After` ante límites de tasa.
5. IF la Ruta_de_Proceso tiene «usar el modelo local si falla» y el fallo es transitorio (`provider_timeout`, `provider_unavailable`, `provider_rate_limited`, `provider_quota`) y el modelo local está instalado, THEN THE worker SHALL repetir el intento con el Motor_Local y registrar la Procedencia real.
6. IF el fallo es `provider_auth`, `consent_missing`, `origin_mismatch` o `secret_unavailable`, THEN THE reunión SHALL quedar en estado reintentable con una causa accionable («la clave fue rechazada», «falta aceptar el aviso») y SHALL NOT cambiar de motor en silencio.
7. THE sistema SHALL mantener intactos el fencing de generaciones, la idempotencia y el reintento existentes: reintentar con otro motor SHALL NOT duplicar transcripciones, hablantes ni resúmenes.

### Requisito 12: Gestión de modelos locales

**Historia de Usuario:** Como usuario, quiero que Sauri me sugiera un modelo local adecuado a mi equipo y lo instale con un botón, para no tener que compilar ni descargar a mano.

#### Criterios de Aceptación

1. THE Servicio_Anfitrión SHALL detectar el hardware (arquitectura, aceleración Metal si es macOS con Apple silicon, memoria total, núcleos y espacio libre en disco) y THE portal SHALL mostrarlo en lenguaje claro.
2. THE sistema SHALL calcular una Recomendación por Proceso con una función determinista del hardware y del Catálogo_Local, explicar el motivo («tu Mac tiene 24 GB: este modelo cabe holgado») y marcar si el modelo fue medido por el equipo o es una propuesta sin medir.
3. WHEN el usuario pulsa «Instalar» en un modelo del Catálogo_Local, THE Servicio_Anfitrión SHALL comprobar el espacio libre (tamaño × 1,2), descargar a un archivo parcial desde la revisión fija, verificar su SHA-256 contra el catálogo y solo entonces moverlo a su ubicación final; IF el hash no coincide, THEN SHALL borrar el parcial y reportar el fallo.
4. THE Servicio_Anfitrión SHALL ejecutar una sola descarga a la vez y reportar progreso real (bytes y total) al portal por consulta periódica, con acción «Cancelar» que deja el disco sin archivos parciales.
5. THE portal SHALL permitir ver los modelos instalados con tamaño y estado de verificación, elegirlos como modelo local de un Proceso, «Verificar» (recalcular el hash) y «Quitar» (con confirmación), sin quitar el modelo en uso por un Proceso sin avisar.
6. THE catálogo SHALL estar versionado en el repositorio con tamaño, SHA-256 y revisión de cada modelo; THE sistema SHALL NOT instalar modelos que no estén en el catálogo.
7. WHERE la instalación del motor (entorno Python o binario) requiere herramientas ausentes, THE portal SHALL mostrar qué falta y el comando para resolverlo en lugar de fallar a mitad de camino.
8. THE modelo local elegido para un Proceso SHALL aplicarse al siguiente intento sin reiniciar contenedores.

### Requisito 13: Menú de configuración reorganizado con buscador

**Historia de Usuario:** Como usuario, quiero encontrar rápido cada ajuste en un menú ordenado por grupos, para no recorrer una lista plana que ya crece.

#### Criterios de Aceptación

1. THE consola de configuración SHALL agrupar su navegación lateral en «General» (Cuenta, Apariencia), «Modelos» (Motores y modelos, Transcripción, Hablantes, Resúmenes y, cuando exista, Chat) y «Grabación» (Grabación).
2. THE navegación SHALL incluir un campo de búsqueda que filtre por nombre de categoría, grupo y palabras clave (por ejemplo «claves», «whisper», «privacidad»), con mensaje de resultado vacío.
3. THE rutas existentes (`/settings/cuenta`, `/settings/apariencia`, `/settings/resumenes`, `/settings/grabacion`) SHALL seguir funcionando; THE nuevas categorías tendrán rutas `/settings/<slug>` con slugs en español definidos en los textos del producto.
4. WHILE el ancho sea menor de 640 px, THE consola SHALL conservar el flujo de dos pasos (lista y detalle) con el buscador en la lista.
5. THE navegación SHALL cumplir `DESIGN.md`: foco visible, objetivo de 44 px, estado actual con `aria-current`, buscador con etiqueta accesible y sin desplazamiento horizontal a 320 px.

### Requisito 14: Interfaz de Motores y modelos

**Historia de Usuario:** Como usuario, quiero tarjetas y diálogos claros y consistentes con el resto del portal, para vincular y revisar proveedores sin confusión.

#### Criterios de Aceptación

1. THE tarjetas, diálogos, insignias de estado, interruptores y botones SHALL usar los componentes de `frontend/src/components/ui/` y los tokens `--ds-*`, sin colores, fuentes ni logos de marca propios; los proveedores se identifican con su nombre y un icono Lucide genérico.
2. THE estado de un proveedor SHALL comunicarse con texto además del color (regla 4 de accesibilidad de `DESIGN.md`, sección 10).
3. THE campo de clave SHALL ser de tipo contraseña, con etiqueta visible, SHALL NOT precargar el valor guardado y SHALL ofrecer «Reemplazar» y «Quitar clave».
4. THE interfaz SHALL mostrar estados de carga, error y vacío con la misma geometría y acciones de reintento que el resto de la consola, y SHALL anunciar los cambios de progreso de instalación con `role="status"`.
5. THE textos visibles SHALL residir solo en `frontend/src/copy/` y el código SHALL usar identificadores en inglés.

### Requisito 15: Transparencia de procedencia y costos

**Historia de Usuario:** Como usuario, quiero saber con qué motor se procesó cada reunión y que cualquier cobro es de mi proveedor, para no llevarme sorpresas.

#### Criterios de Aceptación

1. THE sistema SHALL guardar, por transcripción, diarización y resumen, la Procedencia (motor, modelo y si fue externo) y THE portal SHALL mostrarla en la reunión («Transcrito con whisper.cpp · local», «Resumen con Claude Sonnet · externo»).
2. THE Aviso_de_Privacidad y la tarjeta del proveedor SHALL decir que el uso se cobra en la cuenta del usuario con ese proveedor y que Sauri no muestra precios ni impone topes.
3. THE sistema SHALL registrar por intento, sin contenido, el proveedor, modelo, duración, resultado, clase de error y uso informado (tokens o segundos de audio).
4. WHEN el respaldo local reemplace a un proveedor, THE portal SHALL mostrar que el resultado salió del modelo local y por qué.

### Requisito 16: Plan de ChatGPT (Codex) por la vía oficial

**Historia de Usuario:** Como usuario con un plan de ChatGPT, quiero usarlo para los resúmenes sin comprar una clave de API, para aprovechar lo que ya pago.

#### Criterios de Aceptación

1. THE sistema SHALL ofrecer el tipo «Codex (plan de ChatGPT)» solo después de que el dueño confirme por escrito que el uso del plan por una aplicación local cumple los términos de OpenAI (verificación legal abierta).
2. THE vínculo SHALL usar el flujo oficial «Sign in with ChatGPT» para aplicaciones locales de OpenAI (autorización con PKCE, retorno por `127.0.0.1`, registro dinámico del cliente) y llamar a la API de Respuestas con el token del usuario; THE sistema SHALL NOT usar las rutas internas `backend-api` de ChatGPT ni suplantar al cliente de la CLI de Codex.
3. THE tokens SHALL guardarse como un único secreto en el Almacén_de_Secretos, con rotación del token de actualización guardada antes de usar el nuevo, y SHALL NOT mostrarse ni registrarse.
4. THE tarjeta SHALL indicar que el uso consume la cuota del plan del usuario y que el servicio está en vista previa en OpenAI.
5. IF el flujo oficial no está disponible o no admite salida JSON estricta en la API de Respuestas, THEN THE sistema SHALL ofrecer Codex solo mediante clave de API de OpenAI y SHALL documentarlo, sin implementar la alternativa de APX.

### Requisito 17: Seguridad, observabilidad y verificación

**Historia de Usuario:** Como dueño, quiero evidencia de que las claves están protegidas y de que todo funciona con proveedores reales, para aceptar la función.

#### Criterios de Aceptación

1. THE pasarelas y el Servicio_Anfitrión SHALL escuchar solo en `127.0.0.1` y autenticar cada llamada; THE rutas externas SHALL NOT seguir redirecciones HTTP.
2. THE sistema SHALL tener pruebas automáticas de que ninguna clave aparece en respuestas, registros, excepciones ni diagnósticos para valores de clave aleatorios.
3. THE entrega SHALL pasar las suites de backend, integración, portal y typecheck definidas por el proyecto, con proveedores simulados de red local solo en pruebas.
4. WHEN se cierre la entrega, THE Recorrido_de_Aceptacion SHALL ejecutarse con al menos un proveedor real por Proceso que el dueño haya vinculado, registrando Procedencia, tiempo, resultado y errores, sin audio ni texto de reuniones en el registro de evidencias.
5. THE aceptación de producto SHALL ser del dueño tras el Recorrido_de_Aceptacion; la verificación técnica no la sustituye.

### Requisito 18: Exclusiones explícitas

**Historia de Usuario:** Como dueño, quiero límites claros, para evitar cambios de producto, privacidad o gasto no aprobados.

#### Criterios de Aceptación

1. THE spec SHALL NOT implementar el chat con la grabación ni mostrar el Proceso `chat`.
2. THE spec SHALL NOT enviar audio, transcripciones ni resúmenes a ningún proveedor por defecto ni como parte de pruebas de conexión.
3. THE spec SHALL NOT almacenar claves en PostgreSQL, en variables de entorno de Docker, en el repositorio ni en `localStorage`.
4. THE spec SHALL NOT medir ni mostrar precios, ni imponer topes de gasto.
5. THE spec SHALL NOT cambiar la autenticación, la política de acceso ni el aislamiento entre usuarios existentes.
6. THE spec SHALL NOT prometer calidad o tiempos de un proveedor externo; solo prometen la medición y la Procedencia.
