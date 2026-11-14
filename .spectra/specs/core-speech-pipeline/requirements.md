# Requisitos — Core de voz: transcripción e identificación de hablantes rápidas y precisas

## Introducción

Sauri tiene puertos para sus motores (`ASREngine`, `DiarizationEngine`, `JobQueue`, `ObjectStore`) y servicios de motor HTTP separados (`backend/asr-engine`, `backend/diar-engine`), pero el recorrido real worker → motor nativo → transcripción nunca se demostró de extremo a extremo (`docs/ARCHITECTURE.md`). Los motores nativos actuales (Whisper Turbo sobre MLX, pyannote 3.1 sobre MPS) fueron lentos e inestables por memoria: pyannote tardó entre 8 y 15 minutos solo en diarizar reuniones de 70–98 minutos. Además, el idioma está fijado a `es-CO` (`backend/app/transcription/worker.py:139`), la transcripción no tiene marcas por palabra y cada segmento se asigna entero a un único hablante por solapamiento máximo, lo que pierde cambios de hablante dentro de un segmento. El resumen recibe texto sin hablantes y no superó pruebas de fidelidad.

Entre el 13 y el 14/11/2026 Codex evaluó alternativas en el Mac del dueño (Apple M3, 24 GiB), fuera de Sauri. Evidencia en `~/Proyectos/APX/evidence/codex-*` (informes `report.md`; las transcripciones y audios son privados y no se copian al repositorio):
- **Hablantes:** Senko (CoreML) diarizó 98 min en 11,1 s de inferencia (~31 s de extremo a extremo) y 60 min en ~19 s, detectó los 4 hablantes confirmados por el dueño en SupplyChain y conservó al hablante breve (~60 s de voz); FluidAudio coincidió (49,6 s). La salida suavizada de Senko descarta turnos ≤ 0,78 s.
- **Transcripción:** whisper.cpp con `large-v3-turbo` GGML Q5_0 en Metal transcribió 60 min en 5 min 47 s de cómputo activo. Parakeet Ultra fue ~3× más rápido pero con errores de nombres y mezcla de idiomas; Whisper con CoreML fue más lento. Whisper emitió marcas de palabra invertidas (39 en 9 min).
- **Unión:** con Senko + Whisper, 8,69 % de las palabras de Argos quedaron sin hablante asignado.
- **Resumen:** ninguna variante local (Qwen3-4B, Qwen3.5-9B, extractiva) superó fidelidad y cobertura; Codex recomendó Qwen3.5-9B solo como borrador con revisión humana.
- **Operación:** el Mac entró en suspensión durante una transcripción y triplicó la espera real; la concurrencia de cargas de GPU abortó corridas.
- No existe referencia humana del audio: WER y DER siguen sin medir.

**Idea fuerza:** el core rápido sale de motores nativos adecuados detrás de puertos estables, ejecución en paralelo y atribución por palabra, no de sacrificar precisión; cada promoción de motor se decide con evidencia medida contra una referencia humana.

**Alcance:** contratos de motor (ASR y diarización) y sus adaptadores nativos macOS y portables; normalización de audio; orquestación del procesamiento posterior a la grabación (paralelismo, atribución por palabra, idioma configurable, prevención de suspensión, admisión de recursos); banco de evaluación con referencia humana; entrega del resumen como borrador revisable; y, en una segunda etapa, procesamiento incremental durante la captura.

**No-alcance:** interfaz del portal y de la extensión (specs `portal-visual-design` y `extension-capture-preferences`); preferencia de idioma por usuario en un panel de administración (requiere enmienda de `PRODUCT_BASELINE.md`); reconocimiento de identidades entre grabaciones (`recording-speaker-review`); despliegue en la nube; edición manual de texto de la transcripción (excluida por el baseline).

**Dependencias:** reutiliza de `performance-observability-pipeline` (#907) la admisión con lease y fencing (T9) y la telemetría de etapas (T6–T7); conserva generaciones, fencing e incertidumbre de `recording-speaker-review`; conserva plantillas e idempotencia de `meeting-summaries-templates`; conserva el original y su reproducción de `meeting-review-playback`.

## Glosario

- **Core_de_Voz**: etapas de procesamiento de una grabación almacenada: normalización, transcripción, diarización, unión y persistencia de la transcripción atribuida.
- **Puerto_de_Motor**: contrato versionado (`ASREngine`, `DiarizationEngine`) que el worker usa sin conocer el motor concreto.
- **Adaptador_de_Motor**: implementación de un Puerto_de_Motor para un entorno (p. ej. Senko-CoreML o whisper.cpp-Metal en macOS; pyannote o faster-whisper en Linux/CUDA), seleccionada por configuración.
- **Audio_Normalizado**: PCM mono 16 kHz derivado una sola vez del original para la duración del procesamiento; temporal, no se persiste.
- **Palabra_Atribuida**: palabra con texto, inicio, fin, probabilidad ASR y hablante asignado, o marca explícita `sin_asignar` o `ambigua`.
- **Tiempo_Hasta_Transcripcion**: tiempo de pared desde que el worker recibe el trabajo de una grabación almacenada hasta que la transcripción atribuida queda persistida y legible por el portal.
- **Condiciones_de_Referencia**: Mac Apple M3 de 24 GiB conectado a corriente, modelos ya descargados, sin otra inferencia de Sauri concurrente, corrida continua sin suspensión.
- **Referencia_Humana**: transcripción y segmentación por hablante de al menos 10 minutos de cada una de 2 grabaciones del dueño, revisadas y validadas por el dueño, usadas solo para evaluación.
- **Banco_de_Evaluacion**: conjunto versionado de grabaciones autorizadas (José-María, Invesa, SupplyChain, ArgosOKRs), Referencia_Humana y lista de hechos verificados para resúmenes, con un comando que mide tiempos, memoria, WER, DER, cobertura del hablante breve y fidelidad.
- **Borrador_de_Resumen**: resumen generado localmente con citas a pasajes de la transcripción, presentado como revisable y no como resultado verificado.

## Requisitos

### Requisito 1: Puertos de motor estables y adaptadores intercambiables

**Historia de Usuario:** Como dueño, quiero que el core corra hoy en mi Mac y mañana en la nube sin reescribirlo, para poder migrarlo sin perder trabajo.

#### Criterios de Aceptación

1. THE Puerto_de_Motor de ASR SHALL devolver segmentos y Palabra_Atribuida sin hablante (texto, inicio, fin, probabilidad), el idioma detectado y el identificador de modelo y dispositivo usados.
2. THE Puerto_de_Motor de diarización SHALL devolver segmentos por hablante anónimo sin el filtro que descarta turnos breves, con el identificador de modelo y dispositivo usados.
3. WHEN se configure un Adaptador_de_Motor, THE Core_de_Voz SHALL seleccionarlo solo por configuración, sin cambios de código en el worker ni en la API.
4. THE Core_de_Voz SHALL incluir un Adaptador_de_Motor macOS para Senko (CoreML) y otro para whisper.cpp `large-v3-turbo` (Metal), y conservar un Adaptador_de_Motor Linux funcional para cada puerto.
5. WHEN cambie la forma de un Puerto_de_Motor, THE Core_de_Voz SHALL versionar el contrato y rechazar respuestas de una versión incompatible con un error categorizado.

### Requisito 2: Una sola normalización del audio

**Historia de Usuario:** Como usuario, quiero que cada formato se prepare una vez y bien, para que transcripción y hablantes usen el mismo audio y el mismo reloj.

#### Criterios de Aceptación

1. WHEN comience el procesamiento de una grabación, THE Core_de_Voz SHALL derivar Audio_Normalizado una única vez y entregarlo a transcripción y diarización.
2. THE Core_de_Voz SHALL conservar la duración y el origen temporal del original; IF la normalización altera la duración en más de 100 ms, THEN THE Core_de_Voz SHALL registrarlo como discrepancia.
3. THE Core_de_Voz SHALL eliminar el Audio_Normalizado al terminar o fallar el trabajo y SHALL NOT modificar el original.
4. THE Core_de_Voz SHALL aislar la preparación por formato detrás de una función de entrada, de modo que agregar un formato nuevo no cambie las etapas siguientes; esta spec solo cubre `.webm` (Opus) y los formatos ya aceptados por la carga.

### Requisito 3: Procesamiento en paralelo con prevención de suspensión

**Historia de Usuario:** Como usuario, quiero la transcripción con hablantes en pocos minutos, para revisar la reunión casi en cuanto termina.

#### Criterios de Aceptación

1. WHEN haya Audio_Normalizado, THE Core_de_Voz SHALL ejecutar transcripción y diarización en paralelo cuando la admisión de recursos lo permita, y en serie cuando no.
2. WHILE un Adaptador_de_Motor nativo ejecute un trabajo, THE Core_de_Voz SHALL impedir la suspensión por inactividad del sistema solo durante ese trabajo, sin cambiar la configuración de energía del equipo.
3. WHEN un trabajo pesado solicite inferencia, THE Core_de_Voz SHALL adquirir la reserva de recursos con lease y fencing definida en `performance-observability-pipeline` T9 y SHALL NOT persistir resultados de un propietario obsoleto.
4. WHEN se procese una grabación de 60 minutos en Condiciones_de_Referencia, THE Core_de_Voz SHALL lograr un Tiempo_Hasta_Transcripcion de 7 minutos o menos, medido en una corrida continua con tiempo de pared y activo registrados.
5. THE Core_de_Voz SHALL registrar por etapa: espera de admisión, carga de modelo, normalización, transcripción, diarización, unión y persistencia, declarando ausente lo que no se mida.

### Requisito 4: Atribución de hablante por palabra

**Historia de Usuario:** Como usuario, quiero que cada frase quede con quien la dijo aunque cambie el hablante a mitad de segmento, para confiar en la transcripción.

#### Criterios de Aceptación

1. THE Core_de_Voz SHALL asignar hablante a cada Palabra_Atribuida por intersección temporal con los segmentos de diarización y construir los turnos agrupando palabras consecutivas del mismo hablante.
2. WHEN una palabra tenga marcas invertidas o fuera de la duración, THE Core_de_Voz SHALL corregirlas con una regla documentada y determinista o marcarlas `sin_asignar`, SHALL NOT inventar tiempos y SHALL contarlas.
3. IF una palabra intersecta dos hablantes sin un ganador claro, THEN THE Core_de_Voz SHALL marcarla `ambigua` y conservar ambos candidatos.
4. WHEN se evalúe sobre el Banco_de_Evaluacion, THE Core_de_Voz SHALL dejar `sin_asignar` menos del 3 % de las palabras de ArgosOKRs, frente al 8,69 % de la línea base.
5. THE Core_de_Voz SHALL conservar todo el texto de la transcripción; la atribución SHALL NOT eliminar palabras para mejorar sus métricas.
6. THE Core_de_Voz SHALL conservar hablantes breves: un hablante con al menos 5 s de voz en la diarización SHALL aparecer en la transcripción atribuida.

### Requisito 5: Idioma configurable

**Historia de Usuario:** Como dueño, quiero que el idioma no esté fijo en el código, para poder internacionalizar Sauri en el futuro.

#### Criterios de Aceptación

1. THE Core_de_Voz SHALL tomar el idioma de transcripción de la configuración, con `es` como valor por defecto, y SHALL aceptar un idioma por grabación cuando la solicitud lo indique.
2. WHERE el idioma configurado sea `auto`, THE Core_de_Voz SHALL usar la detección del Adaptador_de_Motor y persistir el idioma detectado.
3. THE Core_de_Voz SHALL eliminar el valor `es-CO` fijo del worker y de los valores por defecto de los contratos.

### Requisito 6: Resumen como borrador revisable

**Historia de Usuario:** Como usuario, quiero un resumen rápido con sus fuentes, sabiendo que es un borrador, para no tomar por cierto algo que el modelo inventó.

#### Criterios de Aceptación

1. WHEN se genere un resumen, THE Core_de_Voz SHALL enviar al modelo la transcripción completa con etiquetas de hablante, sin descartar pasajes.
2. THE Borrador_de_Resumen SHALL citar cada punto clave con al menos un pasaje y su marca temporal, y SHALL rechazar citas que no existan literalmente en la transcripción.
3. THE Core_de_Voz SHALL marcar el Borrador_de_Resumen como pendiente de revisión hasta que el usuario lo revise.
4. WHEN se proponga cambiar el modelo o la estrategia de resumen por defecto, THE Banco_de_Evaluacion SHALL demostrar cobertura de al menos 90 % de los hechos verificados y cero afirmaciones sin respaldo sobre su lista de hechos; mientras ninguna opción lo cumpla, el resumen SHALL seguir marcado como borrador.
5. THE Core_de_Voz SHALL generar el resumen fuera del camino crítico: el Tiempo_Hasta_Transcripcion SHALL NOT incluir el resumen.

### Requisito 7: Banco de evaluación y regla de promoción

**Historia de Usuario:** Como dueño, quiero saber con números si un cambio es más rápido sin ser menos preciso, para no confundir velocidad con calidad.

#### Criterios de Aceptación

1. THE Banco_de_Evaluacion SHALL medir por motor y grabación: tiempo de pared y activo por etapa, memoria residente máxima, presión de memoria, número de hablantes, palabras sin asignar, permanencia del hablante breve y, sobre la Referencia_Humana, WER y DER.
2. THE Banco_de_Evaluacion SHALL ejecutarse con un único comando documentado y guardar resultados sin audio ni texto de transcripción fuera de la carpeta privada de evaluación.
3. WHEN se proponga promover un Adaptador_de_Motor como predeterminado, THE Banco_de_Evaluacion SHALL demostrar WER y DER no peores que el predeterminado vigente en la Referencia_Humana; IF falta la Referencia_Humana, THEN el cambio SHALL declararse con precisión no evaluada y SHALL NOT promoverse.
4. THE Banco_de_Evaluacion SHALL reservar al menos una grabación fuera de cualquier ajuste de parámetros para validar sin sesgo.
5. THE Banco_de_Evaluacion SHALL NOT usar el número esperado de hablantes como parámetro de los motores.

### Requisito 8: Fallos y recuperación

**Historia de Usuario:** Como usuario, quiero que un fallo del motor no pierda mi grabación ni deje la reunión colgada, para poder reintentar.

#### Criterios de Aceptación

1. IF un Adaptador_de_Motor no responde, se queda sin memoria o devuelve un contrato inválido, THEN THE Core_de_Voz SHALL registrar una causa categorizada, conservar el original y dejar la reunión en un estado reintentable visible.
2. WHEN se reintente un trabajo, THE Core_de_Voz SHALL reutilizar la generación y el fencing existentes y SHALL NOT duplicar transcripciones ni hablantes.
3. WHEN una etapa falle, THE Core_de_Voz SHALL conservar los resultados válidos de la otra etapa solo si pertenecen a la misma generación.

### Requisito 9: Procesamiento incremental durante la captura (segunda etapa)

**Historia de Usuario:** Como usuario, quiero que al detener la grabación la transcripción esté lista casi de inmediato, para no esperar después de la reunión.

#### Criterios de Aceptación

1. WHEN la extensión suba fragmentos durante una captura, THE Core_de_Voz SHALL transcribir los fragmentos recibidos mientras la reunión continúa, con una cola acotada y bajo la reserva de recursos.
2. THE Core_de_Voz SHALL asignar hablantes con una agrupación global sobre toda la grabación al cerrar, para que la misma persona conserve su etiqueta en toda la reunión.
3. WHEN termine una captura de 60 minutos en Condiciones_de_Referencia, THE Core_de_Voz SHALL tener la transcripción atribuida lista en 2 minutos o menos tras detener.
4. THE Core_de_Voz SHALL producir el mismo texto y la misma atribución, dentro de las tolerancias del Banco_de_Evaluacion, que el procesamiento posterior de la misma grabación.
5. Esta etapa SHALL comenzar solo después de que los Requisitos 1–8 estén integrados y medidos.

### Requisito 10: Exclusiones explícitas

**Historia de Usuario:** Como dueño, quiero límites claros, para evitar cambios de producto o gastos no aprobados.

#### Criterios de Aceptación

1. THE spec SHALL NOT cambiar la interfaz del portal ni de la extensión, salvo exponer el estado y los datos ya definidos por otras specs.
2. THE spec SHALL NOT enviar audio, transcripciones ni resúmenes a servicios externos; todo el procesamiento es local.
3. THE spec SHALL NOT persistir muestras de voz, embeddings ni Audio_Normalizado más allá del trabajo.
4. THE spec SHALL NOT agregar la preferencia de idioma por usuario en un panel de administración; queda sujeta a una enmienda aprobada de `PRODUCT_BASELINE.md`.
5. THE spec SHALL NOT prometer tiempos fuera de las Condiciones_de_Referencia ni extrapolar mediciones de fragmentos a grabaciones completas.
