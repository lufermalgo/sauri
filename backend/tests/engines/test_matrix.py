"""Capability matrix and privacy notices (Property 6, requirements 2 and 7)."""

from __future__ import annotations

import re

import pytest

from app.copy.engine_notices import NOTICE_VERSIONS, PROCESS_NAMES, PROVIDER_NAMES, build_notice
from app.engines import capability_matrix as matrix
from app.engines.schemas import ERROR_CLASSES, ProviderKind

CAPABILITIES = ("transcription", "diarization", "summary", "chat")


def test_every_provider_kind_has_an_entry_a_default_and_a_name() -> None:
    from typing import get_args

    assert set(matrix.PROVIDER_KINDS) == set(matrix.MATRIX) == set(matrix.DEFAULT_BASE_URLS) == set(PROVIDER_NAMES)
    assert set(get_args(ProviderKind)) == set(matrix.PROVIDER_KINDS)


@pytest.mark.parametrize("kind", [*matrix.PROVIDER_KINDS, "unknown"])
@pytest.mark.parametrize("capability", CAPABILITIES)
def test_pairs_outside_the_matrix_are_never_offered(kind: str, capability: str) -> None:
    support = matrix.get_support(kind, capability)
    if support is None:
        assert not matrix.is_offered(kind, capability)
        assert not matrix.ApiCapabilityMatrix().supports(kind, capability, "openai-chat")


@pytest.mark.parametrize("kind", matrix.PROVIDER_KINDS)
@pytest.mark.parametrize("capability", CAPABILITIES)
def test_unverified_blocked_and_reserved_pairs_are_not_offered(kind: str, capability: str) -> None:
    support = matrix.get_support(kind, capability)
    offered = matrix.is_offered(kind, capability)
    if support is None or (support.verified_on is None and support.accepted_on is None):
        assert not offered
    if kind in matrix.BLOCKED_KINDS or capability == "chat":
        assert not offered
    if offered:
        assert support is not None and (support.verified_on is not None or support.accepted_on is not None)
        assert capability in matrix.VISIBLE_CAPABILITIES


def test_verified_dates_are_iso_and_every_entry_has_evidence() -> None:
    for entries in matrix.MATRIX.values():
        for support in entries.values():
            assert support.notes.strip()
            if support.verified_on is not None:
                assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", support.verified_on)


def test_documented_expectations_of_the_design_table() -> None:
    assert matrix.is_offered("anthropic", "summary")
    assert matrix.is_offered("openai", "summary")
    assert not matrix.is_offered("openai", "transcription")  # whisper-1 retires 2027-02-26, no words on successors
    assert not matrix.is_offered("openai", "diarization")
    assert not matrix.is_offered("anthropic", "transcription")
    assert not matrix.is_offered("groq", "diarization")
    assert not matrix.is_offered("assemblyai", "summary")
    assert not matrix.is_offered("deepgram", "summary")
    # Not verified against official documentation: not offered until checked.
    assert not matrix.is_offered("ollama", "summary")
    assert not matrix.is_offered("assemblyai", "diarization")


def test_the_chatgpt_plan_is_offered_by_decision_for_summary_only_and_says_it_is_not_verified() -> None:
    support = matrix.get_support("chatgpt_plan", "summary")
    assert support is not None and support.verified_on is None and support.accepted_on == "2026-11-16"
    assert "NO VERIFICADO" in support.notes
    assert matrix.is_offered("chatgpt_plan", "summary")
    assert not matrix.is_offered("chatgpt_plan", "transcription")
    assert not matrix.is_offered("chatgpt_plan", "diarization")
    assert not matrix.key_needed("chatgpt_plan") and matrix.key_needed("openai")
    assert matrix.ApiCapabilityMatrix().supports("chatgpt_plan", "summary", "chatgpt-responses")


def test_gemini_serves_summary_only() -> None:
    # Checked with a real key on 2026-11-16 (OpenAI-compatible route); audio would need generateContent.
    assert matrix.is_offered("gemini", "summary")
    assert not matrix.is_offered("gemini", "transcription")
    assert not matrix.is_offered("gemini", "diarization")
    assert matrix.ApiCapabilityMatrix().supports("gemini", "summary", "openai-chat")


def test_gateway_contract_requires_the_matching_transport() -> None:
    contract = matrix.ApiCapabilityMatrix()
    assert contract.supports("anthropic", "summary", "anthropic-messages")
    assert not contract.supports("anthropic", "summary", "openai-chat")
    assert not contract.supports("anthropic", "transcription", "anthropic-messages")


def test_probe_transport_prefers_the_requested_process() -> None:
    assert matrix.probe_transport("assemblyai", "diarization") == "assemblyai"
    assert matrix.probe_transport("groq") == "openai-audio"
    assert matrix.probe_transport("gemini") == "openai-chat"
    assert matrix.probe_transport("nothing") is None


def test_error_classes_match_the_gateway_contract() -> None:
    from sauri_engine_common.external.errors import ERROR_CODES

    assert ERROR_CLASSES == ERROR_CODES


@pytest.mark.parametrize("capability", matrix.VISIBLE_CAPABILITIES)
@pytest.mark.parametrize("kind", matrix.PROVIDER_KINDS)
def test_every_notice_names_process_provider_address_and_billing(capability: str, kind: str) -> None:
    address = "https://api.example.com"
    notice = build_notice(capability, kind, address, runs_on_this_device=False)
    text = " ".join([notice.title, *notice.paragraphs])
    assert PROCESS_NAMES[capability] in notice.title
    assert PROVIDER_NAMES[kind] in text
    assert address in text
    # The plan has no per-use bill: its notice says the use counts against the plan and that the path is unofficial.
    assert ("tu plan de ChatGPT" in text and "no documenta" in text) if kind == "chatgpt_plan" else (
        "se cobra en tu cuenta" in text
    )
    assert "no de Sauri" in text
    assert notice.version == NOTICE_VERSIONS[capability]


def test_notice_content_depends_on_what_leaves_the_machine() -> None:
    audio = build_notice("transcription", "groq", "https://api.groq.com", runs_on_this_device=False)
    assert "audio completo" in audio.paragraphs[0]
    assert (
        "audio completo"
        in build_notice("diarization", "deepgram", "https://x.org", runs_on_this_device=False).paragraphs[0]
    )
    summary = build_notice("summary", "openai", "https://api.openai.com", runs_on_this_device=False)
    assert "texto de la transcrip" in summary.paragraphs[0]
    assert "plantilla" in summary.paragraphs[0]
    assert "audio completo" not in summary.paragraphs[0]
    assert "salen de tu equipo" in summary.paragraphs[0]


def test_local_application_notice_says_it_stays_on_the_machine() -> None:
    notice = build_notice("summary", "ollama", "http://127.0.0.1:11434", runs_on_this_device=True)
    text = " ".join(notice.paragraphs)
    assert "este mismo equipo" in text
    assert "http://127.0.0.1:11434" in text
    assert "se cobra en tu cuenta" in text
    assert "salen de tu equipo" not in text


def test_notices_avoid_technical_vocabulary() -> None:
    forbidden = ("API", "token", "endpoint", "JSON", "payload", "HTTP", "SDK", "streaming", "esquema", "prompt")
    for capability in matrix.VISIBLE_CAPABILITIES:
        for kind in matrix.PROVIDER_KINDS:
            for local in (False, True):
                notice = build_notice(capability, kind, "https://api.example.com", runs_on_this_device=local)
                text = " ".join([notice.title, *notice.paragraphs])
                assert not [word for word in forbidden if word in text], (capability, kind, local)


@pytest.mark.parametrize("capability", matrix.VISIBLE_CAPABILITIES)
@pytest.mark.parametrize("kind", matrix.PROVIDER_KINDS)
@pytest.mark.parametrize("local", [False, True])
def test_english_notice_says_the_same_as_the_spanish_one(capability: str, kind: str, local: bool) -> None:
    spanish = build_notice(capability, kind, "https://api.example.com", runs_on_this_device=local)
    english = build_notice(capability, kind, "https://api.example.com", runs_on_this_device=local, language="en")
    assert english.version == spanish.version == NOTICE_VERSIONS[capability]
    assert len(english.paragraphs) == len(spanish.paragraphs)
    assert english.address == spanish.address
    text = " ".join([english.title, *english.paragraphs])
    assert "https://api.example.com" in text
    assert english.provider_name in text
    assert "not on Sauri" in text or "not by Sauri" in text or "Sauri does not charge" in text
    # No Spanish is left behind in the English text.
    assert not re.search(r"[áéíóúñ¿¡]|\b(de|el|la|los|con|tu|tus|para)\b", text.replace("Codex (plan ChatGPT)", ""))
    forbidden = ("token", "endpoint", "JSON", "payload", "HTTP", "SDK", "streaming", "prompt")
    assert not [word for word in forbidden if word in text]
