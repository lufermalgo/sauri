"""Owner-facing copy for engines and models: privacy notices per process and provider, in Spanish and English.

Each process has its own notice version, shared by every language: the Spanish and the English text say the
same thing, and a consent records only the version. Change a text materially (in any language) and raise
that version: every consent given for an older version stops counting and the user is asked again.
"""

from dataclasses import dataclass
from typing import Literal

Language = Literal["es", "en"]
DEFAULT_LANGUAGE: Language = "es"

NOTICE_VERSIONS: dict[str, int] = {
    "transcription": 1,
    "diarization": 1,
    "summary": 1,
    "chat": 1,
}


@dataclass(frozen=True)
class _Texts:
    """Everything one language needs to write a notice; ``{x}`` fields are filled by ``build_notice``."""

    openai_compatible_name: str
    process_names: dict[str, str]
    what_leaves: dict[str, str]
    purpose: dict[str, str]
    stays_local: dict[str, str]  # each ends with ``{others}``, filled with ``others_stay``
    others_stay: str
    title: str
    send_device: str
    terms_device: str
    billing_device: str
    send_cloud: str
    terms_cloud: str
    billing_cloud: str
    billing_plan: str
    reversible: str


_PROVIDER_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "openrouter": "OpenRouter",
    "ollama": "Ollama",
    "lmstudio": "LM Studio",
    "openai_compatible": "",  # written per language
    "chatgpt_plan": "Codex (plan ChatGPT)",
    "assemblyai": "AssemblyAI",
    "deepgram": "Deepgram",
    "groq": "Groq",
}

_ES = _Texts(
    openai_compatible_name="tu servicio compatible con OpenAI",
    process_names={
        "transcription": "Transcripción",
        "diarization": "Detección de hablantes",
        "summary": "Resumen",
        "chat": "Chat con la grabación",
    },
    what_leaves={
        "transcription": "el audio completo de cada reunión (preparado y comprimido)",
        "diarization": "el audio completo de cada reunión (preparado y comprimido)",
        "summary": (
            "el texto de la transcripción de cada reunión, con la etiqueta de quién habla, "
            "y las instrucciones de la plantilla de resumen"
        ),
        "chat": (
            "el texto de la transcripción de la reunión, con la etiqueta de quién habla, y las preguntas que escribas"
        ),
    },
    purpose={
        "transcription": "convertirlo en texto",
        "diarization": "identificar quién habla en cada momento",
        "summary": "redactar el resumen",
        "chat": "responder tus preguntas",
    },
    stays_local={
        "transcription": "El audio no se usa para nada más y {others}",
        "diarization": "El texto y el resumen no pasan por este proceso y {others}",
        "summary": "El audio no sale de tu equipo en este proceso y {others}",
        "chat": "El audio no sale de tu equipo en este proceso y {others}",
    },
    others_stay="los demás procesos siguen con lo que tengas elegido para ellos.",
    title="{process} con {provider}",
    send_device=(
        "Si aceptas, Sauri enviará {leaves} a {provider}, una aplicación de este mismo equipo "
        "({address}), para {purpose}. Por esta vía no sale a Internet."
    ),
    terms_device=(
        "Lo que {provider} haga después con esos datos, por ejemplo reenviarlos a un servicio en la nube, "
        "depende de esa aplicación y no de Sauri. Revisa su configuración antes de aceptar."
    ),
    billing_device="Si ese servicio tiene un costo, se cobra en tu cuenta con {provider}, no en Sauri.",
    send_cloud=(
        "Si aceptas, Sauri enviará {leaves} a {provider}, en {address}, para {purpose}. Esos datos salen de tu equipo."
    ),
    terms_cloud=(
        "Lo que {provider} haga después con esos datos depende de sus condiciones y de su política "
        "de privacidad, no de Sauri. Revísalas antes de aceptar."
    ),
    billing_cloud="El uso se cobra en tu cuenta con {provider}, según tu plan con ellos; Sauri no lo cobra.",
    billing_plan=(
        "El uso cuenta contra los límites de tu plan de ChatGPT; Sauri no lo cobra. Es una vía que OpenAI no "
        "documenta de forma oficial y podría dejar de funcionar: si falla, Sauri te lo avisa."
    ),
    reversible=(
        "Puedes volver al modelo local cuando quieras. Las reuniones que ya terminaron no se vuelven a procesar."
    ),
)

_EN = _Texts(
    openai_compatible_name="your OpenAI-compatible service",
    process_names={
        "transcription": "Transcription",
        "diarization": "Speaker detection",
        "summary": "Summary",
        "chat": "Chat with the recording",
    },
    what_leaves={
        "transcription": "the full audio of each meeting (prepared and compressed)",
        "diarization": "the full audio of each meeting (prepared and compressed)",
        "summary": (
            "the transcript text of each meeting, with the label of who is speaking, "
            "and the instructions of the summary template"
        ),
        "chat": "the transcript text of the meeting, with the label of who is speaking, and the questions you write",
    },
    purpose={
        "transcription": "turn it into text",
        "diarization": "identify who is speaking at each moment",
        "summary": "write the summary",
        "chat": "answer your questions",
    },
    stays_local={
        "transcription": "The audio is not used for anything else and {others}",
        "diarization": "The text and the summary do not go through this process and {others}",
        "summary": "The audio does not leave your computer in this process and {others}",
        "chat": "The audio does not leave your computer in this process and {others}",
    },
    others_stay="the other processes keep whatever you have chosen for them.",
    title="{process} with {provider}",
    send_device=(
        "If you accept, Sauri will send {leaves} to {provider}, an application on this same computer "
        "({address}), to {purpose}. This route does not go out to the Internet."
    ),
    terms_device=(
        "What {provider} does afterwards with that data, for example forwarding it to a cloud service, "
        "depends on that application and not on Sauri. Check its settings before accepting."
    ),
    billing_device="If that service has a cost, it is charged to your account with {provider}, not by Sauri.",
    send_cloud=(
        "If you accept, Sauri will send {leaves} to {provider}, at {address}, to {purpose}. "
        "That data leaves your computer."
    ),
    terms_cloud=(
        "What {provider} does afterwards with that data depends on its terms and its privacy policy, "
        "not on Sauri. Read them before accepting."
    ),
    billing_cloud=(
        "Usage is charged to your account with {provider}, according to your plan with them; "
        "Sauri does not charge for it."
    ),
    billing_plan=(
        "Usage counts against the limits of your ChatGPT plan; Sauri does not charge for it. It is a route that "
        "OpenAI does not officially document and it could stop working: if it fails, Sauri will tell you."
    ),
    reversible=(
        "You can go back to the local model whenever you want. "
        "Meetings that have already finished are not processed again."
    ),
)

_TEXTS: dict[str, _Texts] = {"es": _ES, "en": _EN}

# The Spanish names kept as module constants: the routes and the tests look providers and processes up by key.
PROVIDER_NAMES: dict[str, str] = {**_PROVIDER_NAMES, "openai_compatible": _ES.openai_compatible_name}
PROCESS_NAMES: dict[str, str] = _ES.process_names


@dataclass(frozen=True)
class Notice:
    capability: str
    version: int
    title: str
    paragraphs: tuple[str, ...]
    provider_name: str
    address: str


def build_notice(
    capability: str, kind: str, address: str, *, runs_on_this_device: bool, language: Language = DEFAULT_LANGUAGE
) -> Notice:
    """The privacy notice for one process and one provider; ``address`` is the provider's origin."""
    texts = _TEXTS[language]
    provider = texts.openai_compatible_name if kind == "openai_compatible" else _PROVIDER_NAMES[kind]
    fields = {
        "provider": provider,
        "address": address,
        "leaves": texts.what_leaves[capability],
        "purpose": texts.purpose[capability],
    }
    if runs_on_this_device:
        send = texts.send_device.format(**fields)
        terms = texts.terms_device.format(**fields)
        billing = texts.billing_device.format(**fields)
    else:
        send = texts.send_cloud.format(**fields)
        terms = texts.terms_cloud.format(**fields)
        billing = texts.billing_plan if kind == "chatgpt_plan" else texts.billing_cloud.format(**fields)
    return Notice(
        capability=capability,
        version=NOTICE_VERSIONS[capability],
        title=texts.title.format(process=texts.process_names[capability], provider=provider),
        paragraphs=(
            send,
            terms,
            billing,
            texts.stays_local[capability].format(others=texts.others_stay),
            texts.reversible,
        ),
        provider_name=provider,
        address=address,
    )
