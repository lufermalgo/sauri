# Evidencia parcial — autorización HTTP de presentación v2

## Alcance

Complemento acotado de la revisión preliminar de seguridad de #880/#659, sobre PR902 `178f893551405774bc5d9006d0eb90cd4c33f586`. No modifica código productivo, políticas, retención ni el procesamiento. No es el gate T20: T19 y las dependencias #248/#246/#253 siguen pendientes. Tampoco sustituye el diagnóstico acústico de Nahuel ni demuestra exactitud de hablantes.

## Cobertura agregada

`backend/tests/speaker_review/test_v2_http_authorization.py` usa FastAPI por ASGI y filas reales en SQLite temporal aislada (no handlers HTTP simulados). Construye una proyección v2 válida y comprueba primero que el dueño la recibe completa. Luego comprueba:

- Sin token o con token inválido: 401 sin identificadores ni piezas.
- Otro dueño: 404 con cuerpo idéntico al de reunión inexistente, sin filtrar identificadores ni piezas.
- La respuesta del dueño no publica texto duplicado, `prepared_result` ni etiquetas internas del motor.
- Un PUT válido de renombre por otro dueño produce el mismo 404 que para una reunión inexistente y no altera el snapshot de revisión del dueño.

Los datos son sintéticos. No se abrió la DB del dueño, S3 ni motores reales; no hubo inferencias ni contenedores Docker. Las fixtures eliminan sus archivos SQLite al finalizar y los archivos temporales se confinan a scratch.

## Validación

Desde `backend/`, intérprete `/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python`:

```bash
python -m pytest -p no:cacheprovider --basetemp=<scratch>/pytest-new tests/speaker_review/test_v2_http_authorization.py tests/meetings/test_review_asset_authorization.py tests/speaker_review/test_generation_api.py tests/diarization/test_prepared_presentation_worker.py tests/summaries/test_summary_api.py -q
python -m ruff check tests/speaker_review/test_v2_http_authorization.py
```

Entorno: `PYTHONDONTWRITEBYTECODE=1`, `TMPDIR` e `HYPOTHESIS_STORAGE_DIRECTORY` en scratch; `SAURI_QA_SUMMARY_READ_URL` deshabilitada para no usar PostgreSQL externo.

Resultado inicial: 52 PASS en 2.56 s. Ruff detectó orden de imports y redefinición de fixtures; corregidos reutilizando el patrón de asignación de fixtures existente. Reejecución definitiva: **52 PASS en 2.46 s**, Ruff del archivo **PASS** y `git diff --check` **PASS**. El SHA final queda registrado en el PR.

## Límites y entrega

Prueba HTTP de controles existentes, no nueva funcionalidad ni cierre de T20. Sin validación PostgreSQL, medios desplegados ni limpieza en cancelación de toda la cadena. H1/retención sigue en PR905 separado. PR apilado sobre el candidato PR902, sin merge; integración reservada a Fer. El archivo nuevo no interfiere con los archivos del diagnóstico acústico ni PR905.
