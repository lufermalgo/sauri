# Requisitos — Core de voz: transcripción e identificación de hablantes rápidas y precisas

## Introducción

Sauri tiene puertos para sus motores (`ASREngine`, `DiarizationEngine`, `JobQueue`, `ObjectStore`) y servicios de motor HTTP separados (`backend/asr-engine`, `backend/diar-engine`), pero el recorrido real worker → motor nativo → transcripción nunca se demostró de extremo a extremo (`docs/architecture/overview.md`). Los motores nativos actuales (Whisper Turbo sobre MLX, pyannote 3.1 sobre MPS) fueron lentos e inestables por memoria: pyannote tardó entre 8 y 15 minutos solo en diarizar reuniones de 70–98 minutos. El idioma está fijado a `es-CO` (`backend/app/transcription/worker.py:139`), la transcripción no tiene marcas por palabra y cada segmento se asigna entero a un único hablante, lo que pierde cambios de hablante dentro de un segmento. El resumen recibe texto sin hablantes y está acoplado a Ollama. El portal no permite subir una grabación y ver su resultado completo.

Entre el 13 y el 14/11/2026 Codex evaluó alternativas en el Mac del dueño (Apple M3, 24 GiB), fuera de Sauri, y recomendó priorizando precisión: **Senko** para hablantes, **Whisper large-v3-turbo** (whisper.cpp, Metal) para transcripción y **Qwen3.5-9B** local para el resumen como borrador revisable. Evidencia en `~/Proyectos/APX/evidence/codex-*` (informes `report.md`; audios y transcripciones son privados y no se copian al repositorio):
- Senko (CoreML) diarizó 60 min en ~19 s y 98 min en ~31 s de extremo a extremo, detectó los 4 hablantes confirmados por el dueño en SupplyChain y conservó al hablante breve. Su salida suavizada descarta turnos ≤ 0,78 s.
- whisper.cpp `large-v3-turbo` GGML Q5_0 en Metal transcribió 60 min en 5 min 47 s de cómputo activo; emitió marcas de palabra invertidas (39 en 9 min).
- Con Senko + Whisper, 8,69 % de las palabras de ArgosOKRs quedaron sin hablante.
- Ningún resumen local fue fiel sin revisión: el resumen se entrega como borrador con citas.
- El Mac entró en suspensión durante una transcripción y triplicó la espera; cargas de GPU concurrentes abortaron corridas.

El dueño decidió el 14/11/2026 **implementar esa recomendación sin nuevas pruebas comparativas** y cerrar la entrega cuando pueda subir una grabación en el portal y ver el resultado final.

**Idea fuerza:** el core rápido sale de motores nativos adecuados detrás de puertos estables, ejecución en paralelo y atribución por palabra; el portal debe mostrar ese resultado de punta a punta.

**Alcance:** contratos y adaptadores de motor (ASR, diarización, LLM de resumen); normalización única del audio; orquestación en paralelo con prevención de suspensión y reserva de recursos; atribución por palabra; idioma configurable; resumen automático como borrador con citas; y el recorrido funcional mínimo del portal: subir, seguir el procesamiento y ver transcripción con hablantes y resumen.

**No-alcance:** pulido visual del portal y la extensión (specs `portal-visual-design` y `extension-capture-preferences`); panel de configuración de proveedores de LLM y de idioma por usuario (spec posterior, con referencia del dueño); procesamiento incremental durante la captura (spec posterior, tras la aceptación de esta); reconocimiento de identidades entre grabaciones (`recording-speaker-review`); despliegue en la nube; edición manual del texto de la transcripción (excluida por el baseline).

**Dependencias:** reutiliza de `performance-observability-pipeline` (#907) la admisión con lease y fencing; conserva generaciones, fencing e incertidumbre de `recording-speaker-review`; conserva plantillas e idempotencia de `meeting-summaries-templates`; conserva el original y su reproducción de `meeting-review-playback`; toma la composición del portal aprobada en `portal-visual-design` sin exigir aún su tratamiento visual.

## Glosario

- **Core_de_Voz**: etapas de procesamiento de una grabación almacenada: normalización, transcripción, diarización, unión, persistencia de la transcripción atribuida y solicitud del resumen.
- **Puerto_de_Motor**: contrato versionado (`ASREngine`, `DiarizationEngine`, `SummarizationEngine`) que los workers usan sin conocer el motor concreto.
- **Adaptador_de_Motor**: implementación de un Puerto_de_Motor para un entorno o proveedor, seleccionada por configuración.
- **Proveedor_LLM**: servicio que expone la API de chat compatible con OpenAI (p. ej. `llama-server` local; en el futuro Ollama, ChatGPT, Anthropic, Gemini u otros), identificado por URL base, modelo y credencial opcional.
- **Audio_Normalizado**: PCM mono 16 kHz derivado una sola vez del original para la duración del procesamiento; temporal, no se persiste.
- **Palabra_Atribuida**: palabra con texto, inicio, fin, probabilidad ASR y hablante asignado, o marca explícita `sin_asignar` o `ambigua`.
- **Tiempo_Hasta_Transcripcion**: tiempo de pared desde que el worker recibe el trabajo de una grabación almacenada hasta que la transcripción atribuida queda persistida y legible por el portal.
- **Condiciones_de_Referencia**: Mac Apple M3 de 24 GiB conectado a corriente, modelos ya descargados, sin otra inferencia de Sauri concurrente, corrida continua sin suspensión.
- **Borrador_de_Resumen**: resumen generado con citas a pasajes de la transcripción, presentado como pendiente de revisión.
- **Recorrido_de_Aceptacion**: subir en el portal una grabación del dueño, ver el avance del procesamiento y abrir la reunión con reproducción, transcripción con hablantes y Borrador_de_Resumen.

## Requisitos

### Requisito 1: Puertos de motor estables y adaptadores intercambiables

**Historia de Usuario:** Como dueño, quiero que el core corra hoy en mi Mac y mañana en la nube sin reescribirlo, para poder migrarlo sin perder trabajo.

#### Criterios de Aceptación

1. THE Puerto_de_Motor de ASR SHALL devolver segmentos y palabras con texto, inicio, fin y probabilidad, el idioma usado y los identificadores de modelo y dispositivo.
2. THE Puerto_de_Motor de diarización SHALL devolver segmentos por hablante anónimo sin el filtro que descarta turnos breves, con identificadores de modelo y dispositivo.
3. WHEN se configure un Adaptador_de_Motor, THE Core_de_Voz SHALL seleccionarlo solo por configuración, sin cambios en workers ni API.
4. THE Core_de_Voz SHALL usar por defecto en macOS Senko (CoreML) para diarización y whisper.cpp `large-v3-turbo` GGML Q5_0 (Metal) para transcripción, y conservar un Adaptador_de_Motor Linux funcional para cada puerto.
5. WHEN cambie la forma de un Puerto_de_Motor, THE Core_de_Voz SHALL versionar el contrato y rechazar respuestas de una versión incompatible con un error categorizado.

### Requisito 2: Una sola normalización del audio

**Historia de Usuario:** Como usuario, quiero que cada formato se prepare una vez y bien, para que transcripción y hablantes usen el mismo audio y el mismo reloj.

#### Criterios de Aceptación

1. THE Core_de_Voz SHALL derivar el Audio_Normalizado con una única implementación y parámetros idénticos (PCM mono 16 kHz) para transcripción y diarización; cada motor nativo lo deriva del original porque corren como servicios separados (costo medido por Codex: ~5 s por hora de audio).
2. IF la normalización altera la duración en más de 100 ms respecto del original, THEN THE Core_de_Voz SHALL registrarlo como discrepancia.
3. THE Core_de_Voz SHALL eliminar el Audio_Normalizado al terminar o fallar el trabajo y SHALL NOT modificar el original.
4. THE Core_de_Voz SHALL aislar la preparación por formato en una función de entrada, de modo que agregar un formato no cambie las etapas siguientes; esta spec cubre `.webm` (Opus) y los formatos ya aceptados por la carga.

### Requisito 3: Procesamiento en paralelo con prevención de suspensión

**Historia de Usuario:** Como usuario, quiero la transcripción con hablantes en pocos minutos, para revisar la reunión casi en cuanto termina.

#### Criterios de Aceptación

1. THE Core_de_Voz SHALL ejecutar transcripción y diarización en serie; la ejecución en paralelo SHALL activarse solo si una medición real muestra una reducción del Tiempo_Hasta_Transcripcion de al menos 10 % (con Senko la diarización dura ~30 s de ~6 min, así que el beneficio esperado es menor).
2. WHILE un Adaptador_de_Motor nativo ejecute un trabajo, THE Core_de_Voz SHALL impedir la suspensión por inactividad solo durante ese trabajo, sin cambiar la configuración de energía del equipo.
3. THE Core_de_Voz SHALL permitir un único trabajo de motor pesado a la vez por host mediante un bloqueo compartido por todos los motores nativos que se libere si el proceso muere, y SHALL seguir descartando resultados de una generación obsoleta mediante el fencing de generaciones existente; la reserva distribuida con lease (`performance-observability-pipeline` T9) queda para despliegues de varios hosts.
4. WHEN se procese una grabación de 60 minutos en Condiciones_de_Referencia, THE Core_de_Voz SHALL lograr un Tiempo_Hasta_Transcripcion de 7 minutos o menos.
5. THE Core_de_Voz SHALL registrar la duración de cada etapa (espera, carga de modelo, normalización, transcripción, diarización, unión, persistencia), declarando ausente lo no medido.

### Requisito 4: Atribución de hablante por palabra

**Historia de Usuario:** Como usuario, quiero que cada frase quede con quien la dijo aunque cambie el hablante a mitad de segmento, para confiar en la transcripción.

#### Criterios de Aceptación

1. THE Core_de_Voz SHALL asignar hablante a cada Palabra_Atribuida por intersección temporal con los segmentos de diarización y construir los turnos agrupando palabras consecutivas del mismo hablante.
2. WHEN una palabra tenga marcas invertidas o fuera de la duración, THE Core_de_Voz SHALL corregirlas con una regla determinista documentada o marcarlas `sin_asignar`, SHALL NOT inventar tiempos y SHALL contarlas.
3. IF una palabra intersecta dos hablantes sin un ganador claro, THEN THE Core_de_Voz SHALL marcarla `ambigua` y conservar ambos candidatos.
4. WHEN una palabra no intersecte ningún segmento, THE Core_de_Voz SHALL asignarle el hablante del segmento más cercano dentro de 500 ms o marcarla `sin_asignar`; sobre ArgosOKRs SHALL quedar `sin_asignar` menos del 3 % de las palabras (línea base 8,69 %).
5. THE Core_de_Voz SHALL conservar todo el texto de la transcripción; la atribución SHALL NOT eliminar palabras.
6. WHEN un hablante tenga al menos 5 s de voz en la diarización, THE Core_de_Voz SHALL mostrarlo en la transcripción atribuida.

### Requisito 5: Idioma configurable

**Historia de Usuario:** Como dueño, quiero que el idioma no esté fijo en el código, para poder internacionalizar Sauri en el futuro.

#### Criterios de Aceptación

1. THE Core_de_Voz SHALL tomar el idioma de transcripción de la configuración, con `es` por defecto, y SHALL aceptar un idioma por grabación cuando la solicitud lo indique.
2. WHERE el idioma configurado sea `auto`, THE Core_de_Voz SHALL usar la detección del Adaptador_de_Motor y persistir el idioma detectado.
3. THE Core_de_Voz SHALL eliminar el valor `es-CO` fijo del worker y de los valores por defecto de los contratos.

### Requisito 6: Resumen automático como borrador con proveedor configurable

**Historia de Usuario:** Como usuario, quiero un resumen con sus fuentes en cuanto termine la transcripción, sabiendo que es un borrador, para no tomar por cierto algo que el modelo inventó.

#### Criterios de Aceptación

1. WHEN una transcripción atribuida quede persistida, THE Core_de_Voz SHALL solicitar automáticamente un Borrador_de_Resumen con la plantilla por defecto, reutilizando la solicitud idempotente existente.
2. THE Core_de_Voz SHALL enviar al modelo la transcripción completa con etiquetas de hablante y marcas temporales por pasaje, sin descartar pasajes.
3. THE Borrador_de_Resumen SHALL contener tema principal y puntos clave, cada punto con al menos una cita a un pasaje existente; THE Core_de_Voz SHALL descartar citas que no correspondan a pasajes de la transcripción.
4. THE Core_de_Voz SHALL acceder al modelo mediante un Adaptador_de_Motor de Proveedor_LLM configurado por URL base, modelo y credencial opcional, y SHALL usar por defecto `llama-server` local con Qwen3.5-9B Q4_K_M.
5. THE Core_de_Voz SHALL leer credenciales de Proveedor_LLM solo desde secretos de entorno y SHALL NOT registrarlas ni enviarlas a la telemetría.
6. THE Core_de_Voz SHALL marcar el Borrador_de_Resumen como pendiente de revisión y SHALL NOT incluir su generación en el Tiempo_Hasta_Transcripcion.

### Requisito 7: Recorrido funcional en el portal

**Historia de Usuario:** Como dueño, quiero subir una grabación y ver el resultado final en el portal, para aceptar el core con mis propios archivos.

#### Criterios de Aceptación

1. THE portal SHALL ofrecer una página de carga con selección de archivo, acción «Subir y procesar» y barra de progreso basada en bytes enviados.
2. WHEN termine la subida, THE portal SHALL abrir la reunión y mostrar su estado de procesamiento real (en cola, transcribiendo, identificando hablantes, completada, fallida) sin porcentajes inventados.
3. WHEN la transcripción esté lista, THE portal SHALL mostrar el reproductor sobre la transcripción, con turnos con marca temporal y etiqueta de hablante, y saltar al tiempo de un turno al seleccionarlo.
4. WHEN el Borrador_de_Resumen esté listo, THE portal SHALL mostrarlo en una pestaña Resumen con su marca de borrador y enlaces de cada cita al turno correspondiente.
5. IF el procesamiento falla, THEN THE portal SHALL mostrar la causa en lenguaje claro y una acción de reintento.
6. THE portal SHALL listar las reuniones de la más reciente a la más antigua y permitir abrir cualquiera.

### Requisito 8: Fallos, recuperación y verificación

**Historia de Usuario:** Como usuario, quiero que un fallo no pierda mi grabación ni deje la reunión colgada, y como dueño quiero evidencia de que todo funciona.

#### Criterios de Aceptación

1. IF un Adaptador_de_Motor no responde, se queda sin memoria o devuelve un contrato inválido, THEN THE Core_de_Voz SHALL registrar una causa categorizada, conservar el original y dejar la reunión en un estado reintentable.
2. WHEN se reintente un trabajo, THE Core_de_Voz SHALL reutilizar la generación y el fencing existentes y SHALL NOT duplicar transcripciones ni hablantes.
3. THE entrega SHALL pasar las suites de backend, integración, extensión y portal definidas por el proyecto, y el typecheck de TypeScript.
4. WHEN se cierre la entrega, THE Recorrido_de_Aceptacion SHALL ejecutarse en Condiciones_de_Referencia con una grabación de al menos 60 minutos del dueño, registrando Tiempo_Hasta_Transcripcion, número de hablantes, porcentaje de palabras `sin_asignar` y tiempo del resumen.
5. THE aceptación de producto SHALL ser del dueño tras el Recorrido_de_Aceptacion; la verificación técnica no la sustituye.

### Requisito 10: Revisión de hablantes sobre la grabación original

**Historia de Usuario:** Como usuario, quiero escuchar dónde habla cada «Speaker N» y ponerle su nombre, para que la transcripción muestre personas y no etiquetas.

#### Criterios de Aceptación

1. THE portal SHALL ofrecer, por cada hablante de la revisión activa, una acción «Escuchar» que reproduce un tramo de la grabación ORIGINAL; THE Core_de_Voz SHALL NOT generar, almacenar ni servir clips o muestras de audio derivados (decisión del dueño del 13/11/2026, enmienda R-R6).
2. THE tramo SHALL ser el tramo continuo más largo del hablante en los turnos atribuidos por palabra, con pausas de hasta 250 ms permitidas, cortado en cambios de hablante, huecos y solapamientos, de máximo 20 s; IF dura menos de 5 s, THEN THE portal SHALL advertirlo sin impedir la reproducción.
3. WHEN el usuario nombre, confirme o corrija un hablante, THE Core_de_Voz SHALL guardar esa disposición de forma idempotente y con control de versión (`expected_version`), y SHALL rechazar con conflicto una revisión que ya no sea la activa.
4. THE nombre elegido SHALL mostrarse en todos los turnos de ese hablante de la revisión, también después de recargar la reunión; mientras no haya nombre ni confirmación, THE transcripción SHALL mostrar `Speaker N`.
5. THE revisión SHALL permanecer pendiente hasta que cada hablante tenga disposición y SHALL volver a pedirse al regresar a la reunión; marcar un hablante SHALL NOT marcar a otro.
6. THE acceso SHALL verificar la propiedad de la reunión en cada ruta y responder «no encontrado» para reuniones ajenas.
7. THE Core_de_Voz SHALL NOT reutilizar nombres entre grabaciones ni generar huellas de voz en esta entrega; el reconocimiento por usuario queda para una spec posterior.

### Requisito 9: Exclusiones explícitas

**Historia de Usuario:** Como dueño, quiero límites claros, para evitar cambios de producto, privacidad o gastos no aprobados.

#### Criterios de Aceptación

1. THE spec SHALL NOT agregar el panel de configuración de proveedores de LLM ni de idioma por usuario; el Adaptador_de_Motor de Proveedor_LLM queda listo para que una spec posterior lo configure desde el portal.
2. THE Core_de_Voz SHALL procesar localmente por defecto y SHALL NOT enviar audio, transcripciones ni resúmenes a un Proveedor_LLM externo salvo configuración explícita del dueño.
3. THE spec SHALL NOT persistir muestras de voz, clips derivados, embeddings ni Audio_Normalizado más allá del trabajo.
4. THE spec SHALL NOT incluir procesamiento incremental durante la captura ni pulido visual Terra; ambos quedan para specs posteriores.
5. THE spec SHALL NOT prometer tiempos fuera de las Condiciones_de_Referencia.
