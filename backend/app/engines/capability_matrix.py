"""Which provider kinds can serve which process, with the evidence behind each claim.

The matrix is the single source of truth for the API (and the contract the gateways validate against):
a pair that is absent is unsupported, and a pair whose ``verified_on`` is ``None`` is not offered until
someone checks it against the provider's official documentation or with a real key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, get_args

Capability = Literal["transcription", "diarization", "summary", "chat"]
Transport = Literal["openai-chat", "anthropic-messages", "chatgpt-responses", "openai-audio", "assemblyai", "deepgram"]

CAPABILITIES: Final[tuple[str, ...]] = get_args(Capability)
# `chat` is reserved for the future chat-with-recording feature: modelled, never offered or routed.
ProcessName = Literal["transcription", "diarization", "summary"]
VISIBLE_CAPABILITIES: Final[tuple[ProcessName, ...]] = ("transcription", "diarization", "summary")

# Kinds the user can link, in the order the portal lists them.
PROVIDER_KINDS: Final[tuple[str, ...]] = (
    "openai",
    "anthropic",
    "gemini",
    "openrouter",
    "ollama",
    "lmstudio",
    "openai_compatible",
    "chatgpt_plan",
    "assemblyai",
    "deepgram",
    "groq",
)
# Kinds that cannot be linked (none today; the ChatGPT plan was one until the owner decided on 2026-11-16).
BLOCKED_KINDS: Final[frozenset[str]] = frozenset()
# Kinds that sign in with the user's account on the host instead of a key: no key is stored or asked for.
ACCOUNT_KINDS: Final[frozenset[str]] = frozenset({"chatgpt_plan"})
# Kinds that run on the user's own machine; they may use http on loopback and may work without a key.
LOCAL_APP_KINDS: Final[frozenset[str]] = frozenset({"ollama", "lmstudio"})
# The key is optional for these (a local or self-hosted server may not need one).
KEY_OPTIONAL_KINDS: Final[frozenset[str]] = frozenset({"ollama", "lmstudio", "openai_compatible"})
# Kinds whose base URL may point at loopback (a local server); everything else needs a public HTTPS host.
LOOPBACK_KINDS: Final[frozenset[str]] = frozenset({"ollama", "lmstudio", "openai_compatible"})

DEFAULT_BASE_URLS: Final[dict[str, str | None]] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://127.0.0.1:11434/v1",
    "lmstudio": "http://127.0.0.1:1234/v1",
    "openai_compatible": None,
    "chatgpt_plan": "https://chatgpt.com/backend-api/codex",
    "assemblyai": "https://api.assemblyai.com",
    "deepgram": "https://api.deepgram.com",
    "groq": "https://api.groq.com/openai/v1",
}


@dataclass(frozen=True)
class Support:
    transport: Transport
    verified_on: str | None  # ISO date of the documentation or real-key check, or None = NO VERIFICADO
    notes: str  # English evidence note: the source and what is still unchecked
    # ISO date the owner decided to offer the pair although it is not verified (``verified_on`` stays None).
    accepted_on: str | None = None

    @property
    def offered(self) -> bool:
        return self.verified_on is not None or self.accepted_on is not None


_DOCS_CHECK = "2026-11-16"

_OPENAI_CHAT = Support(
    "openai-chat",
    _DOCS_CHECK,
    "developers.openai.com Chat Completions: response_format type json_schema with strict.",
)
_ANTHROPIC = Support(
    "anthropic-messages",
    _DOCS_CHECK,
    "platform.claude.com structured outputs (stable): output_config.format json_schema; maxItems and "
    "minItems above 1 unsupported, so the adapter must adapt the schema and validate locally.",
)
_OPENROUTER = Support(
    "openai-chat",
    _DOCS_CHECK,
    "openrouter.ai structured outputs: response_format json_schema; enforcement varies by endpoint, so "
    "route with provider.require_parameters.",
)
_LMSTUDIO = Support(
    "openai-chat",
    _DOCS_CHECK,
    "lmstudio.ai: /v1/chat/completions accepts response_format json_schema; models under 7B may not "
    "comply, so the connection test checks the schema.",
)
_OLLAMA = Support(
    "openai-chat",
    None,
    "docs.ollama.com list response_format for /v1/chat/completions but do not state json_schema, and "
    "enforcement depends on the backend; verify against the installed version (U2.4) before offering.",
)
_COMPATIBLE_CHAT = Support(
    "openai-chat",
    _DOCS_CHECK,
    "Protocol level only (OpenAI Chat Completions json_schema); each server differs, so the connection "
    "test checks the schema.",
)
_GEMINI = Support(
    "openai-chat",
    _DOCS_CHECK,
    "Real-key check 2026-11-16 on the OpenAI-compatible route (base .../v1beta/openai): GET /models answers "
    "200 with 40 ids; POST /chat/completions with response_format json_schema strict is honored on "
    "gemini-3.1-flash-lite, gemini-3.5-flash-lite and gemini-flash-lite-latest. Gemini 2.5 ids answered 404 "
    "for that key, the larger flash ids exceeded the 10 s probe budget and some answered 429/503. Streaming "
    "with stream_options.include_usage is not checked yet. Transcription and diarization are not offered: "
    "audio goes through generateContent (not an adapter Sauri has) and returns no word times or speakers. "
    "Checked again 2026-11-16 with the real summary schema: json_schema strict with maxItems is refused (400), "
    "so the gateway sends it without maxItems and const as a one-value enum (gemini-3.1-flash-lite and "
    "gemini-4-hydrogen answered valid summaries); gemini-2.5-* answers 404 \"no longer available to new users\".",
)
_CODEX = Support(
    "chatgpt-responses",
    None,
    "NO VERIFICADO against documentation. Offered by the owner's decision of 2026-11-16, who accepts that this "
    "is not a documented access path and may break: device-code sign-in with the user's ChatGPT account and "
    "the Responses API at chatgpt.com/backend-api/codex, the way APX does it. Checked live 2026-11-16 (gpt-6-luna, gpt-6.1-terra, "
    "synthetic text): text.format json_schema strict is honored (minItems/maxItems included, every object "
    "must be closed), the event stream has no Content-Type header, temperature is refused; the originator "
    "and user agent Sauri sends are accepted.",
    accepted_on="2026-11-16",
)
_GROQ_ASR = Support(
    "openai-audio",
    _DOCS_CHECK,
    "console.groq.com API reference: timestamp_granularities[] word with verbose_json on "
    "whisper-large-v3 and whisper-large-v3-turbo; multilingual (Spanish not named on the page); 25 MB "
    "free and 100 MB paid upload limits. Real-key check in U4.2/U10.",
)
_ASSEMBLY_ASR = Support(
    "assemblyai",
    _DOCS_CHECK,
    "assemblyai.com docs: words[] with start/end in ms; Spanish listed for Universal-2 and "
    "Universal-3.5 Pro. Limits and real-key behaviour pending (U4.2/U10).",
)
_ASSEMBLY_DIAR = Support(
    "assemblyai",
    None,
    "Speaker labels carry word times, but the official pages reached do not state Spanish for "
    "diarization; confirm with a real key (U5.1) before offering.",
)
_DEEPGRAM_ASR = Support(
    "deepgram",
    _DOCS_CHECK,
    "developers.deepgram.com: words with start/end; Nova-3 lists es. Limits and real-key behaviour pending (U4.2/U10).",
)
_DEEPGRAM_DIAR = Support(
    "deepgram",
    _DOCS_CHECK,
    "developers.deepgram.com: diarization lists all available languages; words carry speaker, start, "
    "end (diarize_model latest/v1/v2). Real-key check and quality against Senko pending (U5.1/U10).",
)

# Per kind and process. `chat` mirrors `summary` (same chat contract) but is never offered.
_ENTRIES: Final[dict[str, dict[str, Support]]] = {
    "openai": {"summary": _OPENAI_CHAT},
    "anthropic": {"summary": _ANTHROPIC},
    "gemini": {"summary": _GEMINI},
    "openrouter": {"summary": _OPENROUTER},
    "ollama": {"summary": _OLLAMA},
    "lmstudio": {"summary": _LMSTUDIO},
    "openai_compatible": {"summary": _COMPATIBLE_CHAT},
    "chatgpt_plan": {"summary": _CODEX},
    "assemblyai": {"transcription": _ASSEMBLY_ASR, "diarization": _ASSEMBLY_DIAR},
    "deepgram": {"transcription": _DEEPGRAM_ASR, "diarization": _DEEPGRAM_DIAR},
    "groq": {"transcription": _GROQ_ASR},
}
MATRIX: Final[dict[str, dict[str, Support]]] = {
    kind: {**entries, **({"chat": entries["summary"]} if "summary" in entries else {})}
    for kind, entries in _ENTRIES.items()
}


def get_support(kind: str, capability: str) -> Support | None:
    """The matrix entry for the pair, or None when the pair is not supported at all."""
    return MATRIX.get(kind, {}).get(capability)


def key_needed(kind: str) -> bool:
    """True when the user must store a key for the kind (local servers and account sign-in need none)."""
    return kind not in KEY_OPTIONAL_KINDS and kind not in ACCOUNT_KINDS


def is_offered(kind: str, capability: str) -> bool:
    """True when the pair may be chosen: supported, verified, visible and the kind is linkable."""
    support = get_support(kind, capability)
    return support is not None and support.offered and capability in VISIBLE_CAPABILITIES and kind not in BLOCKED_KINDS


def probe_transport(kind: str, capability: str | None = None) -> Transport | None:
    """Transport the connection test uses: the requested process' one, else the kind's first."""
    entries = MATRIX.get(kind, {})
    if capability is not None and capability in entries:
        return entries[capability].transport
    for name in (*VISIBLE_CAPABILITIES, "chat"):
        if name in entries:
            return entries[name].transport
    return None


class ApiCapabilityMatrix:
    """Adapter for the gateway contract (``sauri_engine_common.route.CapabilityMatrix``)."""

    def supports(self, kind: str, capability: str, transport: str) -> bool:
        support = get_support(kind, capability)
        return is_offered(kind, capability) and support is not None and support.transport == transport
