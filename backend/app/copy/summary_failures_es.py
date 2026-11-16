"""Owner-facing Spanish text for why a summary request failed, keyed by its ``failure_cause``.

The keys are the closed classes the summary worker can store: the engine-wide provider classes
(``backend/app/engines`` and design.md, "Manejo de errores") and the causes of the local engine. No text
carries meeting content, provider names or keys.
"""

SUMMARY_FAILURE_MESSAGES: dict[str, str] = {
    # Local engine and queue.
    "context_exceeded": "La transcripción supera la capacidad del modelo de resumen.",
    "summary_invalid": "El modelo no devolvió un resumen con fuentes válidas.",
    "llm_unavailable": "El modelo de resumen no está disponible o agotó el tiempo de espera.",
    # External provider classes.
    "provider_auth": "El proveedor rechazó la clave. Revísala en Motores y modelos.",
    "provider_quota": "Tu cuenta con el proveedor no tiene cuota.",
    "provider_rate_limited": "El proveedor limitó las peticiones. Inténtalo de nuevo en unos minutos.",
    "provider_timeout": "El proveedor tardó demasiado.",
    "provider_unavailable": "No pudimos conectar con el proveedor.",
    "provider_bad_request": "El proveedor no aceptó la petición.",
    "provider_invalid_output": "El modelo no devolvió un resumen válido.",
    "provider_context_exceeded": "La reunión es demasiado larga para ese modelo.",
    "audio_too_large": "La reunión es demasiado larga para ese modelo.",
    "provider_unsupported": "Ese proveedor no sirve para generar resúmenes.",
    "consent_missing": "Falta aceptar el aviso de privacidad. Acéptalo en Motores y modelos.",
    "origin_mismatch": "La dirección no coincide con la de la clave guardada.",
    "secret_unavailable": "No pudimos leer la clave guardada.",
}


def summary_failure_message(cause: str | None) -> str | None:
    """The text for a stored cause, or ``None`` for an empty or unrecognized one."""
    return SUMMARY_FAILURE_MESSAGES.get(cause) if cause else None
