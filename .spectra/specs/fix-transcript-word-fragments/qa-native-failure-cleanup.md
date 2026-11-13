# #880 / #882 — Regresión nativa ante fallos

Fecha: 2026-11-13. Base revisada: `7e8d2969b6858ed69dda2f1bb892055dcc7fbdff` (PR #882). Unidad técnica de validación dentro del core aprobado y de las regresiones protegidas de `native-alignment-validation.md`; no cambia producto, inferencia ni políticas.

## Cambio y evidencia

Se agregan tres escenarios HTTP sintéticos al contrato nativo ASR: descarga parcialmente escrita que falla, inferencia que falla y respuesta del proveedor con tiempos inválidos. Cada uno exige HTTP 500 con mensaje público estable, sin exponer el error privado ni el texto del proveedor, y comprueba que desaparece el archivo temporal. La inferencia no debe iniciarse si falla la descarga. No se modifica código productivo ni se debilitan aserciones previas.

Comandos desde `backend/`, intérprete compartido `/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/`:

- `python -m pytest -q tests/asr_engine tests/diar_engine`: **42 passed**, 0.32 s; base anterior: 39 passed.
- `ruff check asr-engine/native_main.py tests/asr_engine/test_native_contract.py`: **PASS**.
- `mypy app`: **PASS**, 61 archivos.
- `git diff --check`: **PASS**.

El comando explícito `mypy asr-engine/native_main.py` conserva los dos errores previos: retorno sin anotar de `lifespan` e import de `mlx_whisper` sin stubs en el venv de backend. Los motores están excluidos por la configuración existente del descubrimiento mypy normal; no se agregó ninguna exclusión ni supresión. No se declara ese comando en verde.

## Alcance de la conclusión

Estos escenarios prueban limpieza y errores HTTP del adaptador, no exactitud de transcripción, diarización, coordinación T-15, backend integrado ni aceptación del dueño. No se iniciaron servicios, motores o contenedores, ni se tocó el runtime de los videos. Esta unidad no modifica UI/TypeScript.

T-15/#248 sigue sin implementación aceptable y depende de la decisión vigente de privacidad B2–B4/T20 de recording-speaker-review. #885 reconcilia migraciones pero no activa T-15. El anterior #884 está cerrado sin integrar: no hay ejecución activa de T-15 que pueda darse por entrega. CI continúa sujeto al bloqueo externo de facturación registrado en las tareas; integración reservada a Fer. Se conserva la evidencia de los dos videos reales como validación parcial, nunca como certificación de precisión total.
