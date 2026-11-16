"""The provider x process pairs a gateway accepts, as pure data the host gateways can import.

The API owns the evidence behind each claim (``backend/app/engines/capability_matrix.py``) and cannot be
imported by a native engine, so the pairs that are OFFERED (supported, verified and linkable) are repeated
here. ``tests/engine_common/test_offered_providers.py`` fails when the two drift apart.
"""

from __future__ import annotations

from typing import Final

from sauri_engine_common.route import Capability, Transport

# kind -> process -> transport, only for pairs the portal offers today.
OFFERED: Final[dict[str, dict[str, Transport]]] = {
    "openai": {"summary": "openai-chat"},
    "anthropic": {"summary": "anthropic-messages"},
    "gemini": {"summary": "openai-chat"},
    "chatgpt_plan": {"summary": "chatgpt-responses"},
    "openrouter": {"summary": "openai-chat"},
    "lmstudio": {"summary": "openai-chat"},
    "openai_compatible": {"summary": "openai-chat"},
    "assemblyai": {"transcription": "assemblyai"},
    "deepgram": {"transcription": "deepgram", "diarization": "deepgram"},
    "groq": {"transcription": "openai-audio"},
}

# Kinds whose base URL may be a server on this machine or network (loopback, plain http); every other kind
# must reach a public HTTPS host. Mirrors ``LOOPBACK_KINDS`` of the API matrix.
LOCAL_SERVER_KINDS: Final[frozenset[str]] = frozenset({"ollama", "lmstudio", "openai_compatible"})


class OfferedMatrix:
    """``CapabilityMatrix`` (see ``route.py``) backed by ``OFFERED``."""

    def supports(self, kind: str, capability: Capability, transport: Transport) -> bool:
        return OFFERED.get(kind, {}).get(capability) == transport
