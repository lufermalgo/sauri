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
