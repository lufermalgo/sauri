"""Wire contracts of the engines API.

Requests forbid unknown fields and are bounded. Responses are built field by field from validated data:
nothing from the host service or the provider is passed through, and no key value exists in any model
except ``KeyIn``, whose ``repr`` is masked.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator

from app.engines.capability_matrix import ProcessName
from app.meetings.schemas import ResourceId

ProviderKind = Literal[
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
]
ProviderStatus = Literal["active", "no_key", "disabled", "unconfigured"]

MAX_LABEL_CHARS = 64
MAX_KEY_CHARS = 2048
MAX_MODEL_CHARS = 200
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_KEY_ALPHABET = re.compile(r"[\x21-\x7e]+")
_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*")
LOCAL_MODEL = re.compile(r"local:[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
LOCAL_DEFAULT_MODEL = "local:default"

# Closed set of classified error codes the host may report (design.md, "Manejo de errores").
ERROR_CLASSES = frozenset(
    {
        "provider_auth",
        "provider_quota",
        "provider_rate_limited",
        "provider_timeout",
        "provider_unavailable",
        "provider_bad_request",
        "provider_invalid_output",
        "provider_context_exceeded",
        "provider_unsupported",
        "audio_too_large",
        "no_word_timestamps",
        "consent_missing",
        "origin_mismatch",
        "secret_unavailable",
    }
)

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_LABEL_CHARS)]


def _clean_label(value: str | None) -> str | None:
    if value is not None and _CONTROL.search(value):
        raise ValueError("label_invalid")
    return value


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ProviderKind
    label: Label
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    enabled: bool = True

    @field_validator("label")
    @classmethod
    def check_label(cls, value: str) -> str:
        return str(_clean_label(value))


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Label | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    enabled: bool | None = None

    @field_validator("label")
    @classmethod
    def check_label(cls, value: str | None) -> str | None:
        return _clean_label(value)


class KeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: SecretStr

    @field_validator("key")
    @classmethod
    def check_key(cls, value: SecretStr) -> SecretStr:
        text = value.get_secret_value()
        if not 1 <= len(text) <= MAX_KEY_CHARS or _KEY_ALPHABET.fullmatch(text) is None:
            raise ValueError("key_invalid")
        return value


class KeyOut(BaseModel):
    key_set: bool
    key_hint: str | None
    reverted_processes: list[ProcessName] = []


class ProviderOut(BaseModel):
    id: str
    kind: ProviderKind
    label: str
    base_url: str | None
    enabled: bool
    status: ProviderStatus
    key_set: bool
    key_hint: str | None
    key_set_at: datetime | None
    used_by: list[ProcessName]
    created_at: datetime
    updated_at: datetime


class ProviderUpdateOut(ProviderOut):
    """The provider after an edit, plus the processes the edit sent back to the local engine."""

    reverted_processes: list[ProcessName] = []


class ProviderDeleteOut(BaseModel):
    reverted_processes: list[ProcessName]


class ProbeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: ProcessName | None = None


class ProbeOut(BaseModel):
    ok: bool
    latency_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    error_class: str | None = None
    json_schema_ok: bool | None = None


class ModelOut(BaseModel):
    id: str = Field(min_length=1, max_length=MAX_MODEL_CHARS)
    label: str | None = Field(default=None, max_length=MAX_MODEL_CHARS)
    # The processes this model can serve and Sauri offers for this provider kind (matrix pairs only).
    serves: list[ProcessName] = Field(default_factory=list)


class ModelsOut(BaseModel):
    models: list[ModelOut]
    # The model a new choice starts with ("Auto"), always one of `models`.
    starter: str | None
    from_cache: bool
    fetched_at: str | None
    # True when the list is missing or failed, so the portal lets the user type the model name.
    manual_entry: bool
    error_class: str | None = None
    # The processes this provider can serve, from the models it lists, within the pairs Sauri offers for its
    # kind. Empty when the list is missing or failed (`manual_entry`).
    serves: list[ProcessName] = Field(default_factory=list)


class ProcessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: ResourceId | None
    model: str = Field(min_length=1, max_length=MAX_MODEL_CHARS)
    local_fallback: bool = True
    notice_version: int | None = Field(default=None, ge=1, le=1_000_000)

    @field_validator("model")
    @classmethod
    def check_model(cls, value: str) -> str:
        if _MODEL_NAME.fullmatch(value) is None:
            raise ValueError("model_invalid")
        return value


class ProcessOut(BaseModel):
    capability: ProcessName
    provider_id: str | None
    provider_kind: ProviderKind | None
    provider_label: str | None
    model: str
    local_fallback: bool
    configured: bool
    version: int
    updated_at: datetime | None
    notice_version: int | None  # the notice version the current consent covers, if any


class NoticeOut(BaseModel):
    capability: ProcessName
    provider_id: str
    provider_kind: ProviderKind
    provider_name: str
    address: str
    notice_version: int
    title: str
    paragraphs: list[str]


class CapabilityOut(BaseModel):
    capability: ProcessName
    transport: str
    # ISO date of the check; None = offered by the owner's decision but not verified live yet.
    verified_on: str | None


class KindOut(BaseModel):
    kind: ProviderKind
    default_base_url: str | None
    key_required: bool
    # "account": no key, the user signs in with their account from the card (ChatGPT plan).
    auth: Literal["key", "account"] = "key"
    linkable: bool
    capabilities: list[CapabilityOut]


class CapabilitiesOut(BaseModel):
    notice_versions: dict[ProcessName, int]
    kinds: list[KindOut]


AccountState = Literal["disconnected", "pending", "connected"]
# Why the last sign-in did not end connected (the portal words each one).
ACCOUNT_ERRORS = frozenset({"code_expired", "access_denied", "login_failed", "session_expired"})


class AccountPendingOut(BaseModel):
    """A sign-in in progress: the code to type at the address."""

    user_code: str = Field(min_length=1, max_length=32)
    verification_url: str = Field(max_length=200)
    expires_at: datetime
    interval_s: int = Field(ge=1, le=60)
    slow_down: bool


class AccountOut(BaseModel):
    """The ChatGPT-plan account of a provider: never carries a token."""

    state: AccountState
    account: str | None = Field(default=None, max_length=254)
    plan: str | None = Field(default=None, max_length=32)
    pending: AccountPendingOut | None = None
    error: str | None = None
    reverted_processes: list[ProcessName] = []


class EngineStateOut(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    port: int = Field(ge=1, le=65535)
    state: str = Field(min_length=1, max_length=32)


class StatusOut(BaseModel):
    engines: list[EngineStateOut]
    secret_store: str | None
