"""The gateways' copy of the offered provider pairs must match the API capability matrix."""

from __future__ import annotations

from itertools import product
from typing import get_args

from sauri_engine_common.offered_providers import LOCAL_SERVER_KINDS, OFFERED, OfferedMatrix
from sauri_engine_common.route import Capability, Transport

from app.engines import capability_matrix as api


def test_gateway_pairs_match_the_api_matrix_for_every_kind_process_and_transport() -> None:
    gateway, kinds = OfferedMatrix(), {*api.MATRIX, *OFFERED, "unknown-kind"}
    for kind, capability, transport in product(sorted(kinds), get_args(Capability), get_args(Transport)):
        assert gateway.supports(kind, capability, transport) == api.ApiCapabilityMatrix().supports(
            kind, capability, transport
        ), (kind, capability, transport)


def test_local_server_kinds_match_the_api_loopback_kinds() -> None:
    assert LOCAL_SERVER_KINDS == api.LOOPBACK_KINDS


def test_the_chatgpt_plan_is_offered_for_summary_only() -> None:
    assert OFFERED["chatgpt_plan"] == {"summary": "chatgpt-responses"}
    assert not OfferedMatrix().supports("chatgpt_plan", "transcription", "chatgpt-responses")
    assert not OfferedMatrix().supports("chatgpt_plan", "diarization", "chatgpt-responses")
    assert not OfferedMatrix().supports("chatgpt_plan", "summary", "openai-chat")
    assert "chatgpt_plan" not in api.KEY_OPTIONAL_KINDS and "chatgpt_plan" in api.ACCOUNT_KINDS


def test_chat_is_never_offered_and_blocked_kinds_are_absent() -> None:
    assert all("chat" not in processes for processes in OFFERED.values())
    assert not set(OFFERED) & api.BLOCKED_KINDS
