"""Tests for the ASREngine factory (factory.py).

# Feature: transcription-asr
Tasks: 3.2, 3.3, 3.4
"""

from __future__ import annotations

import os
from typing import Literal
from unittest.mock import patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.transcription.cloud_provider import CloudProvider
from app.transcription.factory import create_asr_engine
from app.transcription.local_provider import LocalProvider

_SURROGATE_CATEGORY: Literal["Cs"] = "Cs"

# ---------------------------------------------------------------------------
# Property 1: Provider selection by configuration (Task 3.2)
# Feature: transcription-asr, Property 1: Provider selection by configuration
# Validates: Requirements 2.1, 2.2, 2.3, 2.4
# ---------------------------------------------------------------------------


@given(
    padding=st.text(alphabet=" \t", min_size=0, max_size=5),
)
def test_property_1_local_with_variants(padding: str) -> None:
    """ASR_PROVIDER='local' (with spaces/tabs) -> LocalProvider."""
    provider_value = padding + "local" + padding
    env = {
        "ASR_PROVIDER": provider_value,
        "ASR_LOCAL_URL": "http://asr-engine:8001",
    }
    with patch.dict(os.environ, env, clear=False):
        engine = create_asr_engine()
        assert isinstance(engine, LocalProvider)


@given(
    padding=st.text(alphabet=" \t", min_size=0, max_size=5),
)
def test_property_1_cloud_with_variants(padding: str) -> None:
    """ASR_PROVIDER='cloud' (with capitalization and spaces) -> CloudProvider."""
    provider_value = padding + "cloud" + padding
    env = {
        "ASR_PROVIDER": provider_value,
        "ASR_CLOUD_API_KEY": "test-key-123",
        "ASR_CLOUD_ENDPOINT": "https://api.example.com/transcribe",
    }
    with patch.dict(os.environ, env, clear=False):
        engine = create_asr_engine()
        assert isinstance(engine, CloudProvider)


@given(
    value=st.sampled_from(["", "   ", "\t", "\t  "]),
)
def test_property_1_absent_or_empty_is_local(value: str) -> None:
    """ASR_PROVIDER empty or whitespace-only -> LocalProvider (default)."""
    env = {
        "ASR_PROVIDER": value,
        "ASR_LOCAL_URL": "http://asr-engine:8001",
    }
    with patch.dict(os.environ, env, clear=False):
        engine = create_asr_engine()
        assert isinstance(engine, LocalProvider)


def test_property_1_absent_without_variable() -> None:
    """ASR_PROVIDER not defined -> LocalProvider (default)."""
    env = {"ASR_LOCAL_URL": "http://asr-engine:8001"}
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("ASR_PROVIDER", None)
        engine = create_asr_engine()
        assert isinstance(engine, LocalProvider)


# ---------------------------------------------------------------------------
# Property 2: Invalid provider value flags an error with the received value (Task 3.3)
# Feature: transcription-asr, Property 2: Invalid value flags an error
# Validates: Requirements 2.5
# ---------------------------------------------------------------------------


@given(
    value=st.text(
        alphabet=st.characters(
            blacklist_characters="\x00",
            blacklist_categories=(_SURROGATE_CATEGORY,),
        ),
        min_size=1,
        max_size=20,
    ).filter(lambda s: s.strip().lower() not in ("", "local", "cloud")),
)
def test_property_2_invalid_value_includes_value_in_error(value: str) -> None:
    """Unrecognized value -> ValueError that includes the received value."""
    import re

    env = {"ASR_PROVIDER": value}
    with patch.dict(os.environ, env, clear=False), pytest.raises(
        ValueError, match=re.escape(value.strip())
    ):
        create_asr_engine()


# ---------------------------------------------------------------------------
# Example tests for the factory (Task 3.4)
# Validates: Requirements 2.2, 2.3, 2.6
# ---------------------------------------------------------------------------


def test_example_local_with_valid_url() -> None:
    """Req 2.2: 'local' with a valid URL -> configured LocalProvider."""
    env = {
        "ASR_PROVIDER": "local",
        "ASR_LOCAL_URL": "http://asr-engine:8001",
    }
    with patch.dict(os.environ, env, clear=False):
        engine = create_asr_engine()
        assert isinstance(engine, LocalProvider)


def test_example_cloud_with_valid_configuration() -> None:
    """Req 2.3: 'cloud' with an API key and HTTPS endpoint -> CloudProvider."""
    env = {
        "ASR_PROVIDER": "cloud",
        "ASR_CLOUD_API_KEY": "sk-test-123",
        "ASR_CLOUD_ENDPOINT": "https://api.example.com/v1/transcribe",
    }
    with patch.dict(os.environ, env, clear=False):
        engine = create_asr_engine()
        assert isinstance(engine, CloudProvider)


def test_example_local_without_url_raises_valueerror() -> None:
    """Req 2.6: local provider without ASR_LOCAL_URL -> ValueError."""
    env = {"ASR_PROVIDER": "local", "ASR_LOCAL_URL": ""}
    with patch.dict(os.environ, env, clear=False), pytest.raises(
        ValueError, match="ASR_LOCAL_URL"
    ):
        create_asr_engine()


def test_example_local_url_whitespace_only_raises_valueerror() -> None:
    """Req 2.6: local provider with a whitespace-only ASR_LOCAL_URL -> ValueError."""
    env = {"ASR_PROVIDER": "local", "ASR_LOCAL_URL": "   "}
    with patch.dict(os.environ, env, clear=False), pytest.raises(
        ValueError, match="ASR_LOCAL_URL"
    ):
        create_asr_engine()
