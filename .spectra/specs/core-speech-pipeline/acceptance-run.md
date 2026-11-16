# Registro de la corrida real de aceptación — Core de voz (U8.1, #928)

Estado: registro técnico de mediciones. **No es la aceptación de producto**: esa es del dueño (Requisito 8.5). No contiene audio, texto de transcripción, texto de resumen, títulos ni nombres de participantes; solo cifras, fechas, ids truncados a 8 caracteres y nombres de motor/modelo.

Fecha del registro: 16-11-2026. Las dos reuniones medidas son grabaciones reales del dueño subidas por el portal y procesadas por el worker Docker contra los motores nativos del Mac (ASR whisper.cpp `large-v3-turbo` Q5_0, diarización Senko, resumen `llm-engine` con Qwen3.5-9B).

## Fuentes

| Id | Fuente |
|---|---|
| BD | Base PostgreSQL local del proyecto `sauri`, solo consultas `SELECT`: `state_history` (inicio `transcribing` y `completed`), `transcripts.created_at`, `diarizations` (`created_at`, `updated_at`, `speaker_count`), `word_speaker_assignments` (conteo por estado), `summary_request_outbox.requested_at` frente a `meeting_summaries.created_at`, `session_recordings.duration_seconds`. |
| #1010 | Issue #1010: corrida del 16-11-2026, reunión `734d4887`, 94 min, VAD activo. |
| M1, M2 | Notas privadas del orquestador (`sauri_real_run_benchmarks_2026_11_14`, `sauri_core_pipeline_codex_eval_2026_11_14`), fuera del repositorio. M1 es una corrida por el portal del 14-11 (54,2 min) y M2 la evaluación de Codex del 13–14-11 (benchmarks fuera de Sauri). |

## Reuniones medidas (fuente: BD)

| Reunión | Fecha (UTC) | Duración de la grabación | Palabras | Estado final |
|---|---|---|---|---|
| `850b696a` | 15-11-2026 | 55,3 min | 7 906 | `completed` |
| `734d4887` | 16-11-2026 | 94,3 min | 11 659 | `completed` |

La BD no conserva más reuniones de 30 min o más. La columna de procedencia del motor (`engine_name`, `engine_model`) está vacía en ambas porque se procesaron antes de que existiera el registro de procedencia (`model-engines`); el modelo en uso se conoce por la configuración del despliegue, no por la fila.

## Valores medidos frente a las metas

`Tiempo_Hasta_Transcripcion` (Requisito 3.4) se mide como definió la spec: desde que la reunión pasa a `transcribing` (el worker toma el trabajo; la fila de la reunión y ese estado tienen la misma marca, así que no hay espera en cola) hasta que la diarización queda persistida (`diarizations.updated_at`), es decir, hasta que la transcripción atribuida es legible. El resumen queda fuera, como exige el Requisito 4.6.

| Medición | `850b696a` (55,3 min) | `734d4887` (94,3 min) | Meta | Veredicto | Fuente |
|---|---|---|---|---|---|
| Tiempo hasta transcripción persistida (ASR, normalización y guardado) | 363 s (6,05 min) | 809 s (13,49 min) | — | — | BD |
| Diarización y atribución por palabra | 16 s | 42 s | — | — | BD |
| **Tiempo_Hasta_Transcripcion total** | **380 s (6,3 min)** | **852 s (14,2 min)** | ≤ 7 min para 60 min | **No demostrada** (ver nota 1) | BD |
| Equivalente lineal a 60 min (extrapolación, no medición) | 6,9 min | 9,0 min | ≤ 7 min | — | cálculo sobre BD |
| Hablantes detectados | 4 | 3 | sin meta numérica | Medido; exactitud no verificada (nota 2) | BD |
| Palabras `unassigned` | 20 de 7 906 = **0,25 %** | 34 de 11 659 = **0,29 %** | < 3 % | **Cumplida** (ver nota 3) | BD |
| Palabras `ambiguous` | 1 (0,01 %) | 10 (0,09 %) | sin meta | Medido | BD |
| Duración del resumen (solicitud aceptada → resumen persistido) | 298 s (4,96 min) | 622 s (10,4 min); regeneración posterior 628 s | sin meta numérica | Medido; incluye cola y espera del slot | BD |
| Memoria y presión del host | no registrada | no registrada | — | **No medido** | — |
| Condiciones_de_Referencia (corriente, sin otra inferencia, sin suspensión) | no registradas | no registradas | — | **No verificado** | — |

Notas.

1. La meta es de 7 min para una grabación de 60 min. La única reunión de al menos 60 min (`734d4887`) tardó 14,2 min; su equivalente lineal a 60 min (9,0 min) supera la meta. La reunión de 55,3 min tardó 6,3 min, dentro de 7, pero no alcanza los 60 min que exige el recorrido (Requisito 8.4) y su extrapolación a 60 min (6,9 min) queda al límite. La corrida de 94 min es más lenta por minuto de audio (9,0 s/min frente a 6,9 s/min); la BD no explica por qué y no se investigó. No se registraron las Condiciones_de_Referencia, así que no se puede descartar carga concurrente. Esta meta queda **abierta**: falta una corrida de ≥ 60 min en condiciones controladas y con registro de memoria.
2. El conteo sale de la diarización guardada. El texto de este registro no afirma que sea el número real de personas; la spec exige tratarlos como voces, no identidades.
3. La meta de 3 % se definió sobre ArgosOKRs (línea base 8,69 %); aquí se comparó con grabaciones distintas, ambas muy por debajo. La corrida M1 del 14-11 (54,2 min, 4 hablantes) dio 0,25 % de palabras sin asignar y diarización de 14 s, coherente con `850b696a`.

## Otras mediciones y hallazgos

- Corrida M1 (14-11, 54,2 min, por el portal): subida 3,9 s, ASR 313 s (unas 10 veces el tiempo real), diarización 14 s, resumen 381 s, total 714 s. Es una medición previa a las correcciones de VAD y de prompt inicial del ASR.
- Calidad del resumen (M1): 10 de 10 puntos revisados tenían respaldo en los pasajes citados; detalles como porcentajes pueden ser inferidos. No se revisó la calidad del resumen de `734d4887` ni de `850b696a`.
- Calidad del ASR: #1010 registra que en `734d4887` los primeros 1:36 salen sin puntuación ni mayúsculas y desde 1:41 la puntuación es normal (unas 20 marcas por minuto). Sigue abierto; se investigará con audio real. Los tiempos por palabra no se ven afectados según ese informe. M1 había mostrado pérdida de puntuación después del minuto 20, que el prompt inicial predeterminado (#1024/#1026) mitiga: su repetición sobre el archivo completo de 94 min no está verificada en este registro.
- WER y DER no se midieron (no hay referencia humana; M2).
- Fallos observados: M1 anotó tres subidas iniciales con `engine_failed` en unos 2,5 s que se resolvieron al reiniciar los motores; la causa raíz no se encontró. En las dos reuniones medidas aquí no hubo fallos.
- Evaluación previa de Codex (M2, fuera de Sauri, 98 min con 4 hablantes confirmados por el dueño): Senko 11,1 s de inferencia (~31 s de punta a punta); whisper.cpp `large-v3-turbo` Q5_0 en 60 min (ArgosOKRs): 5:47. Esas cifras son de referencia, no de Sauri integrado.

## Criterios de completado de U8.1

- Archivo con valores medidos frente a las metas: **hecho** (este documento).
- «El dueño abre la reunión en el portal y ve transcripción con hablantes y resumen borrador»: **pendiente de registro**. Las dos reuniones están en estado `completed`, con hablantes y resumen guardados en la BD, pero la BD no registra aperturas del portal por reunión y no hay otra evidencia en el repositorio de que el dueño las haya visto; no se afirma observación. Debe anotarse aquí con fecha cuando el dueño lo confirme.
