# Corrección técnica de alineación ASR — #880

## Autoridad y alcance

Fer solicitó el 13-11-2026 entregar el core real de carga de video completo, transcripción y separación en párrafos por hablante; autorizó resolver sus dependencias técnicas sin simulaciones ni recortar el video. Este ajuste conserva motores MLX/pyannote, contrato HTTP, modelo, autorización por grabación y reglas de agrupación de esta spec. No agrega producto, reglas de agrupación por silencio, filtros de vocabulario ni atribuciones inventadas.

## Defecto observado y causa

En la validación privada de un video completo de 1240,552 segundos, MLX devolvió 178 segmentos. Los últimos seis carecían de asignación; cinco comenzaban después del final real. El adaptador usaba límites del decodificador sin alineación por palabras y condicionaba ventanas posteriores sobre texto previo. La repetición en silencio es una hipótesis de causa, no una certificación de exactitud general del modelo.

## Ajuste y regresiones protegidas

Invocar las capacidades existentes de mlx-whisper `word_timestamps=True` y `condition_on_previous_text=False`. La primera alinea límites contra el audio; la segunda evita realimentar texto de ventanas anteriores. Se siguen devolviendo segmentos, no una palabra por fila; las palabras auxiliares del proveedor no cambian el contrato público. No eliminar manualmente segmentos de la base ni modificar resultados para aparentar corrección.

Conservar idioma, modelo, referencias privadas S3, bearer y capacidad de grabación, eliminación del archivo temporal y estados persistidos. No introducir reglas de agrupación por silencio ni forzar número de hablantes. Una segunda ejecución completa produjo 301 segmentos, ninguno iniciado fuera del medio, pero un agradecimiento aislado de 40 ms en el silencio final no estuvo respaldado por la muestra original. Para esa anomalía se activa el detector integrado de mlx-whisper `hallucination_silence_threshold=2.0`, dependiente de `word_timestamps` y de las probabilidades/anomalías del propio modelo. Es un parámetro técnico provisional de inferencia, no un umbral autorizado para agrupar párrafos ni una garantía de exactitud. Tercera ejecución completa en validación; no declarar eliminada la alucinación antes de comprobarla. Los criterios originales de separación y reproducción permanecen vigentes.

## Validación

- Contratos nativos ASR y diarización: `backend/.venv/bin/python -m pytest -q tests/asr_engine/test_native_contract.py tests/diar_engine/test_native_contract.py`, ejecutado desde backend con el intérprete compartido del repositorio: 32 passed.
- Suite completa de contratos/adaptadores nativos: `python -m pytest -q tests/asr_engine tests/diar_engine`: 39 passed. La prueba del contrato exige las tres opciones y conserva respuesta exacta y limpieza del temporal. `ruff check asr-engine/native_main.py tests/asr_engine/test_native_contract.py`: passed. El intento explícito de mypy sobre el motor encontró dos errores previos (lifespan sin anotación y mlx_whisper sin stubs); el proyecto excluye los directorios de motores de su descubrimiento mypy normal; no se cambiaron exclusiones ni se declara mypy global en verde.
- Interfaz: enlace desde resultado cargado al playback existente y metadatos auxiliares ocultos (su URL se revoca deliberadamente). RED determinista 16 passed / 1 failed; GREEN frontend completo 120/120, `npm run typecheck` de todos los workspaces y `npm run build --workspace frontend` aprobados. La prueba nueva exige el enlace exacto al meeting y que el medio de metadatos esté oculto, sin debilitar duración ni lectura de pistas.
- Repetición del video original completo, cargado desde navegador APX a las 12:45 UTC: en ejecución. Comparar resultado, límites y cola silenciosa; no declarar solucionado por las pruebas sintéticas.
- Integración de párrafos y playback: candidatos #850 → #859 → #861, runtime local separado, sin merge a main; #248 se resuelve en trabajo independiente de Nahuel. Pruebas de frontend/typecheck reportadas por Nahuel no certifican exactitud del audio.
- Grabaciones, transcripciones y muestras privadas quedan fuera del repositorio y los fixtures.
