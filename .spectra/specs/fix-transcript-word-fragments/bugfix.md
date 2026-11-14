# Bugfix — Render transcript speaker turns instead of word fragments

## Descripción del Bug

The meeting transcript is reported to render as thousands of very short word-level fragments, with speaker attribution repeated per word, rather than readable speaker turns. QA traced the confirmed fragmentation-preserving path: the worker persists each ASR segment as a `SpeechTurn`, while the API, frontend adapter, and view preserve and render that one-to-one granularity. It is not yet proven that the private meeting's ASR provider emitted the reported fragments, or how its actual speech-turn boundaries can be derived from current inputs; a mapping-only change may therefore be insufficient.

**Evidence and authority:** Fer reported this on 2026-10-30 in parent task `task_6a271652b2c34130` and the linked bugfix card `task_8ce8907902534201`: a full meeting displayed 2,919 approximately 15-character fragments with speaker attribution per word. These counts describe one observed recording only; the separate offline estimate of roughly 75 turns in 61 minutes is not a threshold or acceptance target. No meeting content is included here. The authorized expected behavior comes from the owner-approved `docs/product/baseline.md` snapshot at `f31c1437d002a49849fc577446290ab83d29a584` (blob `273e702ac8b4886a91366a1700c3c1946fc6c0c1`), §4.C.4: the portal transcript presents each turn with timestamp, speaker label, and text. The approved `meeting-review-playback` requirements define transcript passages as paragraphs or fragments with linked times; `recording-speaker-review` governs attribution and honest `Speaker N` labels, not general passage grouping. Neither upstream spec defines a silence-gap threshold or permits merging based solely on matching labels.

## Pasos para Reproducir

**Executed synthetic reproduction and code-path evidence:** see `.spectra/specs/fix-transcript-word-fragments/qa-reproduction.md`, authored by Nia for inspected candidate `19a18ea16a3d053b00be3a5b5d7a091bfee9a18e`.

1. Run the exact frontend and backend commands recorded in that evidence file from the assigned worktree.
2. Observe that the existing synthetic frontend API fixture retains each segment separately, and the component fixture renders one row and speaker label for each supplied turn. The backend property test explicitly persists each ASR segment as one `SpeechTurn`.
3. Compare these deterministic observations with Fer's reported full-meeting symptom (2,919 approximately 15-character fragments and speaker attribution per word).

The commands pass because current tests encode one-segment-to-one-row mapping; they confirm the existing fragmentation-preserving behavior, not a corrected candidate. This does **not** independently reproduce the private meeting or establish that its provider emitted one segment per word. Its audio and transcript remain private and are not included in this artifact. The evidence file identifies the inspected modules/functions, commands, test counts, gaps and limitations.

## Comportamiento Actual (Defecto)

WHEN ASR produces multiple transcript segments for a meeting, THEN the transcription worker persists one `SpeechTurn` per ASR segment; the meeting API serializes each row separately, the frontend adapter maps each valid timed segment to a separate turn, and the transcript view renders a separate row and speaker label for each turn. Nia confirmed this path by code inspection and executed tests at candidate `19a18ea16a3d053b00be3a5b5d7a091bfee9a18e`; the exact file/function findings and commands are in `qa-reproduction.md`.

WHEN the reported full meeting was reviewed, THEN it displayed 2,919 approximately 15-character fragments with speaker attribution per word (Fer's report, not independently reproduced). It remains unproven whether the real provider emitted those fragments or what the actual spoken-turn boundaries were. The confirmed implementation seam is one-ASR-segment-to-one-`SpeechTurn` and one-turn-to-one-row. This is a causal explanation for how segment granularity reaches the UI, but it does not establish that changing this mapping alone can recover correct speaker-turn boundaries.

## Comportamiento Esperado (Correcto)

WHEN the portal presents a transcript for a new recording, or a historical recording whose audio is available and authorized under existing retention, THEN the system SHALL present the transcript as complete speaker turns, each with a timestamp, speaker label, and associated text, as required by the owner-approved product baseline §4.C.4. Raw ASR segment boundaries SHALL NOT, by themselves, be treated as proof that each segment is a separate user-facing speaker turn.

WHEN a historical recording's audio is confirmed expired or irrecoverable under existing retention, THEN the system SHALL preserve its existing source fragments ungrouped and mark them `not_reconstructible`; it SHALL NOT recreate, infer, or fabricate turn groupings without authorized available audio.

WHEN consecutive speech belongs to different speakers or to distinct nonconsecutive turns, THEN the system SHALL preserve the correct turn distinction and attribution; repeated speaker labels alone SHALL NOT cause separate turns to be merged. The approved product behavior is turn-level presentation; the technical signal and processing layer needed to determine those boundaries are not yet established and belong in design, not this bugfix specification.

WHEN a transcript passage is linked to media time, THEN the system SHALL preserve the passage's correct start and end boundaries so that playback highlighting and passage-initiated playback continue to target the corresponding time under `meeting-review-playback` requirements 2 and 3. The fix SHALL NOT invent turn timing or a silence-gap threshold absent from approved sources.

## Comportamiento Sin Cambios (Prevención de Regresiones)

WHEN consecutive transcript turns have different speakers, THEN the system SHALL CONTINUE TO retain the speaker change and the correct attribution for each turn; unknown or uncertain attributions SHALL CONTINUE TO use `Speaker N` rather than an unsupported identity, under `recording-speaker-review` requirement 2.

WHEN two turns with the same speaker label are separated by an intervening speaker turn, THEN the system SHALL CONTINUE TO keep them as separate turns and in their original order.

WHEN transcript timing contains a gap or overlapping intervals, THEN the system SHALL CONTINUE TO preserve those original timing relationships and SHALL NOT bridge a gap or remove an overlap by widening, shifting, or fabricating turn boundaries.

WHEN playback time advances across a transcript passage boundary, THEN the system SHALL CONTINUE TO highlight the passage associated with that time; activating a passage playback control SHALL CONTINUE TO start playback at that passage's linked time, under `meeting-review-playback` requirements 2 and 3.

WHEN text or timing is absent or invalid for an entry, THEN the system SHALL CONTINUE TO avoid fabricating text or a time-linked playback association, consistent with the approved playback design's invalid/missing timing behavior.

## Restricciones del Fix

- Do not include actual meeting content, transcript text, names, or other owner data in this spec, tests, fixtures, or commits; use synthetic data only.
- Do not treat the observed counts or the offline turn estimate as thresholds, targets, or pass/fail criteria.
- Do not introduce an arbitrary silence-gap duration or other numerical threshold. The approved sources do not specify one.
- Do not merge nonconsecutive turns solely because speaker labels match; preserve turn order, speaker changes, unknown labels, and original timing gaps/overlaps.
- Do not change retention policy or recover audio outside existing retention and authorization; when historical audio is confirmed expired or irrecoverable, preserve source fragments ungrouped and mark them `not_reconstructible`.
- Preserve playback passage start/end fidelity and current seek/highlight behavior. Do not redesign the UI or add transcript editing.
- Establish the failing layer with reproducible synthetic test evidence before choosing backend, API, or frontend implementation placement. If a proposed fix requires new product behavior beyond presenting each turn as specified in the approved baseline, stop and identify that scope delta to Ansel for an authorized decision; do not silently broaden this bugfix.

## Criterios de Aceptación

1. Given a new recording, or a historical recording whose audio is available and authorized under existing retention, and a processing output representing multiple low-level text fragments within a spoken turn, the portal SHALL present the complete turn text as a turn-level passage with its timestamp and correct speaker label, rather than exposing each low-level ASR fragment as a user-facing turn. The approved baseline specifies this observable turn-level behavior; the source of reliable turn boundaries is an unresolved technical design investigation.
2. Given a historical recording whose audio is confirmed expired or irrecoverable under existing retention, the portal SHALL preserve the existing source fragments ungrouped and mark them `not_reconstructible`; this state SHALL be observable in the transcript representation, and no turn grouping SHALL be inferred or fabricated.
3. Given a speaker change or a distinct later nonconsecutive turn with a previously used speaker label, the output SHALL preserve separate turns, their original order, and their correct labels; matching labels alone SHALL NOT merge them.
4. Given unknown or uncertain speaker attribution, the output SHALL preserve the `Speaker N` label rather than assert an unsupported identity, consistent with `recording-speaker-review` requirement 2.
5. Given transcript timing with gaps or overlapping intervals, the fix SHALL preserve the original timing relationships and SHALL NOT fabricate continuous timing or bridge the intervals. No numeric silence-gap threshold is prescribed.
6. Given playback at a passage boundary or activation of a passage control, highlighting and playback start SHALL continue to use the correct passage timing; the fix SHALL NOT regress approved playback requirements 2 and 3.
7. Tests SHALL use synthetic transcript content only. Neither the reported 2,919 fragments nor the offline estimate of roughly 75 turns in 61 minutes is a numeric acceptance threshold.

---

## Enmienda propuesta 2026-11-13 — Ruido, evidencia temporal y atribución

**Estado: fase 1 propuesta, pendiente de revisión de Ansel y aprobación del delta SDD correspondiente.** Autor: Nahuel. Encargo: `task_e54417ff1e164f69`. Continúa [#880](https://github.com/lufermalgo/sauri/issues/880) y el candidato [#882](https://github.com/lufermalgo/sauri/pull/882); no los reemplaza ni crea otro issue equivalente. La ausencia del resumen se sigue en `recording-notes` y queda fuera de esta enmienda.

El texto anterior y sus AC1–AC7 conservan su aprobación histórica. Esta sección agrega requisitos identificados como E/R/AC-R; no declara aprobados ni implementados estos requisitos nuevos. `.config.spectra` conserva sus fases completas **del alcance previo**, no acredita aprobación de esta enmienda. El diseño y las tareas aprobados permanecen intactos; su granularidad de un segmento completo por asignación no resuelve por sí sola este delta. No se reinician fases ya aprobadas ni se habilita implementación, RED, despliegue, merge o reprocesamiento por publicar esta propuesta.

### Descripción del Bug y evidencia delimitada

Fer informó el 13-11 a las 18:20 UTC que la conversación de su ejemplo comienza alrededor del minuto 2, pero aparecen palabras antes, sobre ruido; también observó un hablante sin transcripción y otro con texto. El diagnóstico comunicado por Ansel a las 18:26 está concluido. Se reutiliza sin consultar nuevamente datos privados ni copiar audio, transcripción, identificadores de grabación o consultas privadas al repositorio.

| ID | Hecho y procedencia | Límite de la conclusión |
|---|---|---|
| H1 | Reporte de Fer y captura adjunta a la tarea: texto temprano donde indica ruido. | El inicio alrededor del minuto 2 describe ese ejemplo, no autoriza recortar un prefijo ni establece cuándo puede comenzar el habla de otra grabación. La captura no prueba acústicamente el contenido. |
| H2 | Diagnóstico de runtime: `mlx-whisper 0.4.3`, `mlx-community/whisper-large-v3-turbo`, `word_timestamps=True`, `condition_on_previous_text=False`, `hallucination_silence_threshold=2.0`; sin VAD externo. Código coherente en `7e8d296:backend/asr-engine/native_main.py::transcribe`. | Las opciones ya estaban activadas y no evitaron el caso informado; activarlas otra vez no constituye solución. `2.0` es configuración observada, no un nuevo umbral de aceptación. |
| H3 | El adaptador acepta cada segmento de texto no vacío y devuelve solo texto e inicio/fin. Descarta palabras y scores auxiliares del proveedor. El worker persiste los segmentos fuente. | La respuesta persistida no permite reconstruir qué evidencia de voz o alineación motivó cada palabra. Un score aislado tampoco certifica voz real. |
| H4 | `backend/app/diarization/assignment.py::assign_turns` elige un solo hablante por segmento completo según solapamiento acumulado positivo; `worker.py` genera hablantes a partir de intervalos del diarizador antes de asignar texto. | Un cambio de voz dentro de un segmento ASR puede perderse al asignar todo el segmento a un único hablante, aunque existan intervalos de ambos. No demuestra que haya ocurrido en cada caso real. |
| H5 | Diagnóstico ya entregado: la generación revisada no mezcla versiones; Speaker 8 tiene cero asignaciones y Speaker 9 tiene catorce. Los primeros tres segmentos quedan sin atribución. | Cero asignaciones no prueba detección falsa; catorce no prueba una persona distinta. `Speaker N` expresa atribución desconocida, no una identidad detectada adicional. No se exige ese número de hablantes o asignaciones en pruebas. |
| H6 | No se conservaron los intervalos crudos de pyannote de esa ejecución. | No se puede decidir acústicamente por qué quedó un hablante sin texto ni recuperar límites por palabra descartados a partir del texto persistido. No se autoriza retener esos datos ahora. |

**Hipótesis causal, no hecho acústico establecido:** el texto no vacío del decoder puede pasar como habla sin comprobación acústica suficiente; la pérdida de evidencia auxiliar impide contrastarlo después. La atribución por segmento completo puede dejar sin texto a una voz que sí intervino dentro de ese segmento. También puede existir una detección de voz falsa; ninguna de estas alternativas autoriza ocultar personas, borrar texto corto o forzar un número de hablantes.

**Referencias técnicas, no nuevos diagnósticos ni reemplazos de runtime:** base documental `origin/main@41ab5f4`; candidato core `#882@7e8d296`, incluido `native-alignment-validation.md` en ese commit; runtime informado API `d51aafb` / portal `fff14b2`. La validación anterior de silencio final en #882 no certifica este ruido inicial, exactitud completa o identidades. Estas referencias no equivalen a integración en main.

### Pasos para Reproducir — contratos sintéticos automatizables

Esta es una **especificación de fixtures y aserciones**, no código de prueba implementado ni RED ejecutado. El diseño debe ubicar el seam y definir cómo se obtiene evidencia acústica con los motores existentes. Las evidencias inyectadas abajo son entradas controladas de un doble de prueba, no la afirmación de que un detector real pueda producir un oráculo perfecto. Los tiempos son datos del fixture en milisegundos relativos al original, no umbrales de voz, de silencio o de duración mínima.

1. Construir en memoria la salida sintética del proveedor de la tabla. Usar IDs locales `s0`, `s1`, `s2`, `w1`… y hablantes `A`, `B`, `C`; sin contenido ni IDs de la grabación real. Definir evidencia acústica inyectable por intervalo con tres estados conceptuales: `non_speech`, `speech`, `unavailable`. Estos nombres describen el fixture, no cambian la API pública.
2. Para el defecto de admisión, alimentar `N0` y `N1` al mapeador nativo con `transcribe_audio` sustituido por la salida controlada. La versión inspeccionada conserva ambos por tener texto no vacío. En la futura ruta de comprobación, exigir las aserciones N0–N2; no implementar el doble como solución productiva.
3. Para el defecto de atribución, pasar a `assign_turns` un único segmento `s2=[2000,3000]` y los intervalos de D0. Actualmente adjudica el segmento completo a A (600 ms frente a 400 ms de B), por lo que B queda sin ese texto. La futura ruta debe aprovechar los límites de palabras comprobados para cumplir D0 sin convertir cada palabra en una fila de presentación.
4. Ejecutar separadamente D1–D5, variando solo las entradas indicadas; comparar texto, orden, límites y asignaciones, además de contadores. No inferir corrección porque disminuya el número de filas o de hablantes.
5. Cubrir N0–D5 con pruebas de contrato/adaptador, atribución, persistencia/API por generación y agrupación/playback. El futuro RED debe fallar por conducta observada, no por importaciones o configuración ausentes. Registrar comandos, SHA, fallos y GREEN en la fase de implementación autorizada.

| Caso | Entradas sintéticas deterministas | Resultado exigido al fix |
|---|---|---|
| N0 — ruido con texto del decoder | `s0=[0,800]`, texto inventado de fixture `texto de prueba`, evidencia `non_speech`; parametrizar otro inicio `[5000,5800]`. | Ninguna palabra atribuida a habla ni un hablante creado **a causa de ese texto** en la salida nueva aceptada. No filtrar por estar al principio. No borrar fuentes históricas. |
| N1 — saludo breve real | `s1=[900,1100]`, texto `Hola.`, palabra alineada al mismo intervalo, evidencia `speech`, hablante A en ese intervalo. Parametrizar `[0,200]` para habla al inicio. | Conservar `Hola.`, su intervalo y A. La duración corta y la posición inicial no justifican supresión. |
| N2 — ausencia de evidencia | Mismo segmento válido de N1 con evidencia `unavailable` o sin auxiliares; repetir con score ausente. | No etiquetar como ruido confirmado ni eliminar por un dato ausente; conservar texto y tiempos válidos, sin atribución nueva no sustentada. El diseño debe declarar la limitación, sin aprobar nueva pantalla o telemetría. |
| D0 — cambio interno comprobable | `s2=[2000,3000]`, texto `Hola. Buen día.`; `w1=Hola.[2000,2600]`, `w2=Buen[2600,2800]`, `w3=día.[2800,3000]`; evidencia `speech`; A `[2000,2600]`, B `[2600,3000]`. | Mantener cada palabra exactamente una vez, `Hola.` con A y `Buen día.` con B, con esos límites; presentación en turnos, no una fila por palabra. Conservar texto fuente y vinculación de procedencia. |
| D1 — sin palabras utilizables | Mismo `s2` e intervalos A/B, pero sin `words`; variantes con un límite de palabra ausente, no finito, invertido o fuera de `s2`. | No fabricar divisiones del texto ni tiempos interpolados ni afirmar B para una palabra sin soporte; conservar segmento fuente válido y su intervalo. El diseño debe definir fallback compatible y atribución honesta; ninguna división inválida llega al playback. |
| D2 — gaps, overlaps y repetición de voz | Fuentes ordenadas `s3=Sí.[4000,4200]`, `s4=Bien.[4500,4800]`, `s5=Vale.[4700,5000]`, una palabra por fuente con sus mismos límites; A `[4000,4200]`, B `[4500,4800]`, A `[4700,5000]`. B y último A se solapan. | Conservar A/B/A en orden fuente, gap `[4200,4500]` y overlap `[4700,4800]`. No fusionar A no consecutivos, rellenar huecos, duplicar palabras ni afirmar voz exclusiva cuando la evidencia de una palabra es ambigua. |
| D3 — voz sin texto | D0 más C `[3100,3300]`, sin ninguna palabra/segmento correspondiente. | C sigue sin asignación; no fabricar texto ni identidad ni borrar/ocultar C para reducir el conteo. La comprobación distingue detección sin texto de persona confirmada. |
| D4 — aislamiento y reproducción | Dos generaciones con IDs de speaker y etiquetas distintos, mismas fuentes válidas; revisión manual solo en la anterior. Ejecutar D0 y D2 contra la generación activa, luego activar cada passage de playback. | No copiar etiquetas/assignments entre generaciones; resaltar/reproducir solo intervalos originales correspondientes, dejando gaps sin passage activo. Escuchar desde el original, sin muestras derivadas persistentes. |
| D5 — empate y overlap cero | Una palabra `Listo.[6000,6200]`; variante empate: A y B ambos `[6000,6200]`, con secuencias locales 1 y 2; variante cero: A `[5800,6000]`, B `[6200,6400]`. | En cero no asignar hablante. En empate no afirmar voz exclusiva comprobada; documentar la limitación y aplicar el fallback que defina diseño sin inventar una identidad. El desempate técnico vigente por secuencia no constituye prueba acústica ni autoriza renombrar personas. |

**Límite de esta reproducción:** N0 prueba la decisión con evidencia suministrada, no que la evidencia sea acústicamente correcta; D0 prueba que el segmento completo pierde granularidad, no quién habló en la grabación privada. Antes de declarar corregido el producto se necesita validación acústica autorizada, no persistente, con ruido y habla real —incluida habla breve— y las regresiones de frontera. El diseño definirá el protocolo con los recursos existentes; esta fase no realiza cargas, grabaciones ni reprocesamientos y no habilita acceder nuevamente a audio privado.

### Comportamiento Actual (Defecto) — delta

- **A-R1:** WHEN el decoder devuelve texto no vacío, THEN el adaptador inspeccionado lo acepta sin conservar la evidencia auxiliar de palabras/scores ni efectuar una comprobación acústica adicional suficiente para el caso informado.
- **A-R2:** WHEN un segmento ASR contiene intervalos de varios hablantes, THEN la asignación actual elige un solo hablante para todo el segmento; una voz detectada puede quedarse sin texto atribuido.
- **A-R3:** WHEN solo quedan fuentes y asignaciones persistidas, THEN no es posible reconstruir las palabras/intervalos descartados ni concluir que un hablante sin texto es una detección falsa.

### Comportamiento Esperado (Correcto) — delta

- **E-R1:** WHEN se acepta una transcripción nueva, THEN el sistema SHALL comprobar la correspondencia de texto y habla usando evidencia acústica y temporal verificable de los recursos existentes, de modo que los casos de ruido sin habla verificados no se publiquen como palabras habladas. Texto no vacío, score aislado o falta de asignación no SHALL bastar como prueba de habla o de ruido. No se promete eliminar toda alucinación posible.
- **E-R2:** WHEN hay habla real, incluidos saludos e intervenciones breves o al comienzo, THEN el sistema SHALL conservar palabras reales y límites respaldados; no SHALL descartarlas por duración, vocabulario, posición en la grabación o etiqueta desconocida.
- **E-R3:** WHEN palabras alineadas utilizables y evidencia de diarización permiten comprobar un cambio de hablante dentro de un segmento, THEN el sistema SHALL aprovechar esa granularidad para atribuir el texto correspondiente, preservando procedencia, orden y tiempos, sin duplicarlo, reescribirlo o regresar a una fila por palabra.
- **E-R4:** WHEN la evidencia de palabra, voz o frontera es ausente, inválida, contradictoria o insuficiente, THEN el sistema SHALL preservar el texto/intervalos fuente válidos sin inventar divisiones o identidades; el diseño SHALL definir el fallback y su limitación, conservando `Speaker N` donde no exista atribución sustentada.
- **E-R5:** WHEN un grupo de voz detectado no tiene texto asignado, THEN el sistema SHALL mantener la distinción entre detección, asignación e identidad; no SHALL inventarle texto, declararlo una persona confirmada, ni borrarlo u ocultarlo como supuesto falso positivo sin evidencia.

### Comportamiento Sin Cambios (Prevención de Regresiones) — delta

- **R-R1:** WHEN se procesa texto válido, THEN el sistema SHALL CONTINUE TO preservar fuentes `Transcript`/`SpeechTurn` existentes, palabras, orden, procedencia y límites originales. La comprobación de admisión de resultados futuros no autoriza borrar o editar resultados ya guardados.
- **R-R2:** WHEN se agrupan passages o se reproduce el original, THEN el sistema SHALL CONTINUE TO respetar AC1–AC7, gaps, overlaps, cambios reales y A/B/A; una etiqueta coincidente o un silencio supuesto no convierte fragmentos separados en habla continua.
- **R-R3:** WHEN se consulta, revisa o regenera una grabación, THEN el sistema SHALL CONTINUE TO aislar generaciones, revisiones e identidades; conservar correcciones manuales previas sin copiarlas automáticamente a la nueva generación de la misma grabación. Esta propuesta no autoriza regenerarla.
- **R-R4:** WHEN se autoriza acceso al audio o falla el motor, THEN el sistema SHALL CONTINUE TO exigir dueño/capability de la grabación exacta, limpiar temporales en éxito/error y conservar errores y estados veraces; no devolver éxito vacío para ocultar fallos. El diseño debe verificar el contrato existente de audio sin habla, distinto de fallo de motor, sin redefinirlo aquí.
- **R-R5:** WHEN el audio histórico falta o expiró, THEN el sistema SHALL CONTINUE TO preservar fuentes y `not_reconstructible` bajo las reglas aprobadas; no buscar otra copia ni ampliar retención.
- **R-R6:** WHEN se escucha para identificar una voz, THEN el sistema SHALL CONTINUE TO usar el original y los tramos significativos exigidos por Fer, sin generar/guardar muestras derivadas ni introducir una duración mínima numérica. Esta enmienda no modifica la selección de escucha ya entregada.

### Restricciones del Fix y evidencia mínima para diseño

1. No introducir modelos nuevos, descargas, servicios cloud, costos ni cambios de infraestructura para resolver este delta sin autorización. No forzar cantidad de hablantes, filtros de vocabulario, corte de los primeros dos minutos ni umbrales acústicos arbitrarios. El diseño puede evaluar capacidades existentes y justificar decisiones técnicas con evidencia, sin convertirlas en políticas de producto.
2. No modificar runtime, contratos HTTP, esquema, UI o telemetría en esta entrega documental. Para el diseño, conservar compatibilidad de consumidores actuales; cualquier transporte interno de evidencia auxiliar debe explicitar formato, validación, disponibilidad y fallback, sin exponer palabras/scores/intervalos sensibles por API o logs. Un cambio real de producto, privacidad, gastos o política de seguridad requiere decisión del dueño, no inferencia técnica.
3. No borrar personas o transcripción ni alterar fuentes persistidas para aparentar éxito; no generar clips persistentes, embeddings de identidad o referencias de voz entre reuniones. Ningún dato privado en commits, fixtures, issues, capturas nuevas o informes públicos. Mantener las autorizaciones y retención existentes.
4. **Mínimo técnico a evaluar de forma no persistente:** opciones/versiones del motor; segmentos y palabras con sus tiempos/validez; disponibilidad de probabilidades/scores y significado efectivo en MLX; evidencia de habla/no habla que ya pueda producirse con recursos locales; intervalos originales de diarización con etiquetas locales y relación temporal con palabras; duración original y offsets. Examinar solo lo necesario en memoria durante una ejecución autorizada; no registrar audio, texto, scores por palabra, intervalos crudos o URLs privadas como telemetría. No se aprueba nueva retención ni nueva ejecución por enumerarlos.
5. Ausencia de una palabra/score no significa silencio; una detección de diarización no certifica voz real; un solapamiento no certifica identidad. El diseño debe separar estos límites, explicar manejo de overlaps/empates/invalidación y demostrar que los metadatos auxiliares no se conservan tras la ejecución, sin desactivar la limpieza vigente. Solo evidencia sintética y resultados agregados no sensibles en Git.
6. No volver a diagnosticar la grabación ni exigir especialistas históricos ausentes. Ansel revisa esta propuesta y gestiona aprobación del delta; Fer integra. La revisión técnica no sustituye aceptación de producto ni prueba de exactitud acústica.

### Criterios de Aceptación — delta y trazabilidad

| ID | Requisito / regresión | Verificación exigida antes de declarar implementado |
|---|---|---|
| AC-R1 | E-R1; R-R1/R-R4 | N0 rechaza palabras inventadas de la salida nueva respaldadas como no-habla; repetir fuera del prefijo inicial. Contrastar además una ejecución acústica autorizada de ruido/no habla con el protocolo diseñado. No borrar fuentes existentes ni transformar fallos en éxito. |
| AC-R2 | E-R2/E-R4 | N1 conserva saludo breve al inicio y después de ruido; N2 no elimina por ausencia de scores/evidencia. Validación acústica de habla breve con los modelos existentes; ningún mínimo temporal o vocabulario prohibido como sustituto. |
| AC-R3 | E-R3; R-R1/R-R2 | D0 conserva todas las palabras exactamente una vez con A/B y sus límites comprobados; fuentes intactas y presentación por turnos. Debe fallar con la adjudicación completa a A; validar backend, contrato/API y portal, no solo conteo de filas. |
| AC-R4 | E-R4; R-R2 | D1, D2 y D5 cubren ausencia/invalidación de auxiliares, ambigüedad, empates, gaps y overlaps; sin interpolación, duplicación o continuidad falsa. El fallback definido por diseño conserva texto/tiempos válidos y atribución honesta. |
| AC-R5 | E-R5 | D3 mantiene detección sin texto sin inventar una persona o esconderla; no se usa el conteo real como expectativa. No se exige concluir si el Speaker 8 real es falso. |
| AC-R6 | R-R2/R-R3/R-R5/R-R6; AC1–AC7 | D4 y regresiones existentes prueban generaciones aisladas, labels honestos, fragmentos históricos no reconstruibles, playback/highlight de intervalos originales y escucha sin clips nuevos. |
| AC-R7 | R-R4 y restricciones 2–5 | Contratos y pruebas de autorización/limpieza en éxito y error, estados sin-habla frente a fallo compatibles con lo aprobado, ausencia de metadatos sensibles nuevos en DB/logs/artefactos. Documentar campos auxiliares y ciclo de vida; no ampliar retención. |
| AC-R8 | Límites de H1–H6 | Informe del SHA implementado separa pruebas sintéticas de validación acústica real, hallazgos de limitaciones y autorización de la ejecución. No afirma eliminación absoluta de alucinaciones ni identidad exacta; ni documentos, ni CI verde, ni menos hablantes sustituyen esa validación. |

**Condición de cierre de esta asignación (solo fase 1):** PR documental publicado para revisión, ligado a #880/#882 y la tarea APX, con diff y metadata JSON verificados. No significa aprobación del delta ni arreglo instalado. Después de la revisión de Ansel y la aprobación correspondiente, la siguiente fase deberá diseñar: (a) obtención/comprobación de evidencia acústica existente y protocolo de validación real; (b) paso temporal de palabras e intervalos y fallback compatible; (c) atribución sin pérdida de fuente ni fronteras inventadas; (d) ciclo de vida no persistente y contratos/errores; (e) matriz de pruebas y actualización incremental del plan aprobado. Recién entonces se desglosan/autorizarán tareas RED→GREEN; no se reutiliza la aprobación previa como autorización de este delta.
