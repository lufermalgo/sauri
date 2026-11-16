"""Owner-facing Spanish copy for engines and models: privacy notices per process and provider.

Each process has its own notice version. Change a text materially and raise that version: every
consent given for an older version stops counting and the user is asked again.
"""

from dataclasses import dataclass

NOTICE_VERSIONS: dict[str, int] = {
    "transcription": 1,
    "diarization": 1,
    "summary": 1,
    "chat": 1,
}

PROVIDER_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "openrouter": "OpenRouter",
    "ollama": "Ollama",
    "lmstudio": "LM Studio",
    "openai_compatible": "tu servicio compatible con OpenAI",
    "chatgpt_plan": "Codex (plan ChatGPT)",
    "assemblyai": "AssemblyAI",
    "deepgram": "Deepgram",
    "groq": "Groq",
}

PROCESS_NAMES: dict[str, str] = {
    "transcription": "Transcripción",
    "diarization": "Detección de hablantes",
    "summary": "Resumen",
    "chat": "Chat con la grabación",
}

_WHAT_LEAVES: dict[str, str] = {
    "transcription": "el audio completo de cada reunión (preparado y comprimido)",
    "diarization": "el audio completo de cada reunión (preparado y comprimido)",
    "summary": (
        "el texto de la transcripción de cada reunión, con la etiqueta de quién habla, "
        "y las instrucciones de la plantilla de resumen"
    ),
    "chat": (
        "el texto de la transcripción de la reunión, con la etiqueta de quién habla, y las preguntas que escribas"
    ),
}

_PURPOSE: dict[str, str] = {
    "transcription": "convertirlo en texto",
    "diarization": "identificar quién habla en cada momento",
    "summary": "redactar el resumen",
    "chat": "responder tus preguntas",
}

_OTHERS_STAY = "los demás procesos siguen con lo que tengas elegido para ellos."
_STAYS_LOCAL: dict[str, str] = {
    "transcription": f"El audio no se usa para nada más y {_OTHERS_STAY}",
    "diarization": f"El texto y el resumen no pasan por este proceso y {_OTHERS_STAY}",
    "summary": f"El audio no sale de tu equipo en este proceso y {_OTHERS_STAY}",
    "chat": f"El audio no sale de tu equipo en este proceso y {_OTHERS_STAY}",
}


@dataclass(frozen=True)
class Notice:
    capability: str
    version: int
    title: str
    paragraphs: tuple[str, ...]
    provider_name: str
    address: str


def build_notice(capability: str, kind: str, address: str, *, runs_on_this_device: bool) -> Notice:
    """The privacy notice for one process and one provider; ``address`` is the provider's origin."""
    provider = PROVIDER_NAMES[kind]
    process = PROCESS_NAMES[capability]
    leaves = _WHAT_LEAVES[capability]
    purpose = _PURPOSE[capability]
    if runs_on_this_device:
        send = (
            f"Si aceptas, Sauri enviará {leaves} a {provider}, una aplicación de este mismo equipo "
            f"({address}), para {purpose}. Por esta vía no sale a Internet."
        )
        terms = (
            f"Lo que {provider} haga después con esos datos, por ejemplo reenviarlos a un servicio en la nube, "
            "depende de esa aplicación y no de Sauri. Revisa su configuración antes de aceptar."
        )
        billing = f"Si ese servicio tiene un costo, se cobra en tu cuenta con {provider}, no en Sauri."
    else:
        send = (
            f"Si aceptas, Sauri enviará {leaves} a {provider}, en {address}, para {purpose}. "
            "Esos datos salen de tu equipo."
        )
        terms = (
            f"Lo que {provider} haga después con esos datos depende de sus condiciones y de su política "
            "de privacidad, no de Sauri. Revísalas antes de aceptar."
        )
        billing = (
            "El uso cuenta contra los límites de tu plan de ChatGPT; Sauri no lo cobra. Es una vía que OpenAI no "
            "documenta de forma oficial y podría dejar de funcionar: si falla, Sauri te lo avisa."
            if kind == "chatgpt_plan"
            else f"El uso se cobra en tu cuenta con {provider}, según tu plan con ellos; Sauri no lo cobra."
        )
    reversible = (
        "Puedes volver al modelo local cuando quieras. Las reuniones que ya terminaron no se vuelven a procesar."
    )
    return Notice(
        capability=capability,
        version=NOTICE_VERSIONS[capability],
        title=f"{process} con {provider}",
        paragraphs=(send, terms, billing, _STAYS_LOCAL[capability], reversible),
        provider_name=provider,
        address=address,
    )
