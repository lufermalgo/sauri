# #880 / #900 — validación acústica aislada del original

Fecha: 2026-11-13, 19:33Z. Tarea APX `task_e54417ff1e164f69`. Continúa criterios #897 y diseño #898; no cierra #880 ni habilita flags en vivo.

## Procedimiento ejecutado

- Consulté en modo lectura el original previamente diagnosticado (duración 4175 s, transcript existente de 988 fuentes). La selección fue exacta y única; no usé otra grabación ni modifiqué filas.
- Leí el objeto original desde MinIO local y decodifiqué mediante ffmpeg por pipes, todo en memoria. No escribí audio, clips, transcripción ni resultados de producto en disco/DB/store/cola.
- La ventana de validación predeclarada fue `[0,180)` segundos del original: comprende el ruido inicial y los primeros saludos indicados por Fer. **Es una ventana de prueba, no una política que recorta los primeros 2 minutos.** Los offsets empiezan en el origen del medio, sin concatenar intervalos ni desplazar voz.
- Ejecuté VAD powerset pyannote ya instalado y MLX Whisper/MPS local, con `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`. No descargué modelos, usé servicios externos ni reemplacé procesos vivos. El modelo y los parámetros son los del candidato, no ajustados al ejemplo.
- El script solo publicó conteos agregados y el hash del módulo. No imprimió texto, audio_ref, credenciales ni métricas por persona. El proceso terminó y liberó sus referencias en RAM; no se promete sobreescritura criptográfica de memoria.

Comando real, con script temporal propio de esta sesión:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /Users/lufermalgo/.local/share/sauri/native-engines/venv/bin/python \
  <temporal-de-la-sesion>/qualify_original_window.py
```

**Binding del código ensayado:** SHA-256 de `backend/asr-engine/native_main.py` = `f6e1656186f60421c959dd1788323e7aee4170b730d16f85e5e9cd5bd11777f4`. Era el módulo del worktree con cambios de proyección en curso; **no atribuir esta ejecución al head anterior `e4ca3b8`**. El candidato publicado final debe contener el mismo módulo o repetir esta prueba si cambia admisión/VAD. El hash seguía coincidiendo al publicar este informe.

## Resultado observado — exit 0, 44,56 segundos

| Medida sobre `[0,180)` | Resultado |
|---|---:|
| Segmentos no vacíos del decoder | 18 |
| Segmentos del decoder que terminan antes/en 120 s | 2 |
| Fuentes admitidas que terminan antes/en 120 s | **0** |
| Segmentos del decoder que comienzan en/después de 120 s | 16 |
| Fuentes admitidas que comienzan en/después de 120 s | **16** |
| Fuentes admitidas totales | 16 |
| Regiones VAD con inicio antes de 120 s | 2 |

El dato de las dos regiones VAD tempranas impide afirmar «todo el prefijo fue detectado como silencio». Lo demostrado es que ninguna se solapó con los dos segmentos de texto temprano y, por ello, la política los rechazó; los dieciséis segmentos posteriores se conservaron. No eliminé clusters, forcé voces ni añadí un cutoff temporal.

La primera ejecución llegó a completar los motores pero falló al serializar un contador `numpy.int64` a JSON. Corregí **solo el script de medición**, usando conversión numérica en el serializador, y repetí inferencia en una segunda ejecución exitosa. No cambié el detector para obtener este resultado.

## Alcance de la evidencia

Esta ejecución utiliza **audio humano original**, no TTS: amplía los controles sintéticos ya documentados. La referencia de Fer es temporal gruesa (ruido antes del minuto 2 y saludos alrededor de ese minuto), **no ground truth humano palabra por palabra**. No se certifican las palabras reconocidas, omisiones, voz humana débil general, identidad de speakers ni calidad del resto de los 4175 s.

Quedan pendientes las pruebas de atribución/proyección, contratos API y recorrido portal/playback sobre el SHA final instalado de forma coordinada. La prueba no activa el candidato, no integra el PR ni cambia el resultado que Fer ve actualmente.

## Regresión de alineación adicional

La revisión independiente detectó palabras con inicios/fin en orden inverso aceptadas por `_aligned_segments`. Se añadió fallback entero sin reordenar ni recortar texto:

- RED: **2 fallos / 1 pase** en `pytest tests/asr_engine/test_native_acoustic_alignment.py -q -k 'non_monotonic or monotonic_overlapping'`.
- GREEN tras corregir: **3 pases / 12 deselected**. El control positivo conserva un overlap real entre palabras en orden monotónico.
- Los cambios de esos tests y de la función están en el worktree compartido con la continuación activa de #900; la publicación conjunta y el rerun completo corresponden al candidato final. Este informe no afirma que ya estén confirmados en remoto.

Antes de la continuación de proyección ejecuté adicionalmente las suites ASR/diarización/provider/factory/fence/worker: **179 passed, 1 skipped**. Es evidencia del estado de ese momento, no un reemplazo de las suites completas sobre el SHA final.

## Verificación independiente del WIP de proyección (19:38–19:48Z)

- `python -m alembic heads` en backend: un único head `014_final_presentation` en este candidato. No apliqué migraciones a la DB viva.
- `python -m pytest tests/asr_engine/test_native_acoustic_alignment.py tests/diarization/test_presentation.py tests/diarization/test_prepared_presentation_worker.py -q`: **21 passed**.
- `npm run typecheck` desde raíz: **PASS en los tres workspaces** (extensión, frontend y shared-types).
- `npm run test --workspace sauri-frontend -- src/transcript-projection.test.ts src/transcript-turns.test.ts src/components/TranscriptView.test.tsx src/components/__tests__/MeetingPlaybackView.test.tsx src/components/__tests__/PlaybackController.test.ts src/api.test.ts`: **96 passed, 6 archivos**. Hubo avisos de jsdom por `HTMLMediaElement.pause` no implementado; las aserciones pasaron. No constituyen prueba de reproducción real.

**Hallazgo de regresión pendiente en el WIP:** `projectTranscript` publica cada pieza como fila nueva y no agrupa piezas consecutivas con la misma voz cuando pertenecen a fuentes distintas. Reproduje con dos fuentes sintéticas `One.` `[0,1000)` y `Two.` `[2000,3000)`, ambas sustentadas por el mismo speaker: `groupTranscriptTurns` legacy devuelve **1 turno**, la proyección v2 devuelve **2 turnos** y conserva 2 intervalos. La comprobación se ejecutó con Node usando el TypeScript real transpilado en memoria; la aserción `v2.turns.length === 1` falla. Los 96 tests actuales no cubren ese contraejemplo.

Recomendación de esa revisión: agrupar también esas corridas en v2, separar el ID único de cada intervalo del `presentationTurnId` agrupado y conservar ambos intervalos/gap sin sintetizar un envolvente. No edité entonces el archivo porque la continuación `run_20b4009d286b4886` modificaba los contratos.

**Estado final posterior:** corregido en código `38a6fe6` con RED conductual y GREEN. La reactivación de Nahuel verificó de nuevo el contraejemplo sobre el head `954b4ea`: legacy **1 turno**, v2 **1 turno / 2 intervalos**. La regresión ya no queda abierta. La suite conjunta ASR/diar-engine/transcription/diarization/meetings dio **358 passed, 1 skipped** (se mantiene la exclusión declarada del módulo S3 sin configurar), la suite frontend completa **134 passed**, typecheck global/build/Ruff PASS y mypy focal de 10 archivos PASS. El primer rerun backend excedió su límite de 120 segundos; repetido con un límite de 600 segundos terminó correctamente en 105,82 segundos, sin nuevas exclusiones.

Recorrido APX adicional del componente real sobre fixtures y audio sintéticos en servidor propio aislado `127.0.0.1:9415`: tres filas A/B/`Speaker N`, dos padres contiguos de B en una sola fila, click B → seek **2000 ms**, click padre incierto → seek **4000 ms**, ambos con passage y etiqueta correctos. Se observaron capturas sin error visible de componente; no se presenta como integración QA combinada ni audio humano. El servidor temporal propio se detuvo al terminar. Un intento de escribir el slider no cambió su valor y no se cuenta como prueba manual del gap; los intervalos/gaps se cubren con las regresiones automatizadas.
