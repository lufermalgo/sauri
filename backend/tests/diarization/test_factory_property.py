"""Property tests for the DiarizationEngine factory (factory.py).

# Feature: identificacion-hablantes, Property 1: Provider selection by configuration
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.diarization.factory import create_diarization_engine
from app.diarization.local_provider import LocalProvider
from app.diarization.cloud_provider import CloudProvider


# ---------------------------------------------------------------------------
# Property 1: Provider selection by configuration
# Feature: identificacion-hablantes, Property 1: Provider selection by configuration
# Validates: Requirements 2.1, 2.2, 2.3, 2.4
# ---------------------------------------------------------------------------

# Strategy: generate "local" with arbitrary capitalization and padding
_local_capitalization = st.sampled_from(["local", "Local", "LOCAL", "lOcAl", "LocAL"])
_cloud_capitalization = st.sampled_from(["cloud", "Cloud", "CLOUD", "cLoUd", "ClOUD"])
_padding = st.text(alphabet=" \t", min_size=0, max_size=5)


@settings(max_examples=100)
@given(
    word=_local_capitalization,
    padding_left=_padding,
    padding_right=_padding,
)
def test_property_1_local_with_capitalization_and_spaces(
    word: str, padding_left: str, padding_right: str
):
    """DIARIZATION_PROVIDER='local' (arbitrary capitalization/spaces) -> LocalProvider."""
    provider_value = padding_left + word + padding_right
    env = {
        "DIARIZATION_PROVIDER": provider_value,
        "DIARIZATION_LOCAL_URL": "http://diar-engine:8000",
    }
    with patch.dict(os.environ, env, clear=False):
        engine = create_diarization_engine()
        assert isinstance(engine, LocalProvider)


@settings(max_examples=100)
@given(
    word=_cloud_capitalization,
    padding_left=_padding,
    padding_right=_padding,
)
def test_property_1_cloud_with_capitalization_and_spaces(
    word: str, padding_left: str, padding_right: str
):
    """DIARIZATION_PROVIDER='cloud' (arbitrary capitalization/spaces) -> CloudProvider."""
    provider_value = padding_left + word + padding_right
    env = {
        "DIARIZATION_PROVIDER": provider_value,
        "DIARIZATION_CLOUD_ENDPOINT": "https://example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "test-key",
    }
    with patch.dict(os.environ, env, clear=False):
        engine = create_diarization_engine()
        assert isinstance(engine, CloudProvider)


@settings(max_examples=100)
@given(
    value=st.sampled_from(["", "   ", "\t", "\t  "]),
)
def test_property_1_empty_is_local(value: str):
    """DIARIZATION_PROVIDER empty or whitespace-only -> LocalProvider (default)."""
    env = {
        "DIARIZATION_PROVIDER": value,
        "DIARIZATION_LOCAL_URL": "http://diar-engine:8000",
    }
    with patch.dict(os.environ, env, clear=False):
        engine = create_diarization_engine()
        assert isinstance(engine, LocalProvider)


def test_property_1_absent_without_variable():
    """DIARIZATION_PROVIDER not defined -> LocalProvider (default)."""
    env = {"DIARIZATION_LOCAL_URL": "http://diar-engine:8000"}
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("DIARIZATION_PROVIDER", None)
        engine = create_diarization_engine()
        assert isinstance(engine, LocalProvider)


# ---------------------------------------------------------------------------
# Property 2: Invalid provider value flags an error with the received value
# Feature: identificacion-hablantes, Property 2: Invalid provider value flags an error with the received value
# Validates: Requirements 2.5
# ---------------------------------------------------------------------------

# Strategy: generate DIARIZATION_PROVIDER values that, when normalized
# (strip + lowercase), are NOT "local", "cloud", or empty/whitespace-only.
_invalid_provider = st.text(
    alphabet=st.characters(
        blacklist_characters="\x00",
        blacklist_categories=("Cs",),  # Exclude surrogates (invalid in env vars)
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip().lower() not in ("local", "cloud", ""))


@settings(max_examples=100)
@given(provider_value=_invalid_provider)
def test_property_2_invalid_value_flags_error(provider_value: str):
    """An invalid DIARIZATION_PROVIDER (normalized != local/cloud/empty) raises ValueError with the received value."""
    import re

    env = {
        "DIARIZATION_PROVIDER": provider_value,
        "DIARIZATION_LOCAL_URL": "http://diar-engine:8000",
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match=re.escape(provider_value.strip())):
            create_diarization_engine()

# ---------------------------------------------------------------------------
# Example tests for the DiarizationEngine factory (Task 4.3)
# Validates: Requirements 2.2, 2.3, 2.6
# ---------------------------------------------------------------------------


def test_example_local_with_url_defined():
    """Req 2.2: DIARIZATION_PROVIDER='local' with DIARIZATION_LOCAL_URL defined -> LocalProvider."""
    env = {
        "DIARIZATION_PROVIDER": "local",
        "DIARIZATION_LOCAL_URL": "http://diar-engine:8002",
    }
    with patch.dict(os.environ, env, clear=False):
        engine = create_diarization_engine()
        assert isinstance(engine, LocalProvider)


def test_example_cloud_with_endpoint_and_key():
    """Req 2.3: DIARIZATION_PROVIDER='cloud' with HTTPS endpoint and API key -> CloudProvider."""
    env = {
        "DIARIZATION_PROVIDER": "cloud",
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.diarization.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "sk-test-key-12345",
    }
    with patch.dict(os.environ, env, clear=False):
        engine = create_diarization_engine()
        assert isinstance(engine, CloudProvider)


def test_example_local_url_missing_raises_valueerror():
    """Req 2.6: Local provider selected but DIARIZATION_LOCAL_URL missing -> ValueError."""
    env = {"DIARIZATION_PROVIDER": "local"}
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("DIARIZATION_LOCAL_URL", None)
        with pytest.raises(ValueError, match="DIARIZATION_LOCAL_URL"):
            create_diarization_engine()


def test_example_local_url_empty_raises_valueerror():
    """Req 2.6: Local provider selected but DIARIZATION_LOCAL_URL empty -> ValueError."""
    env = {
        "DIARIZATION_PROVIDER": "local",
        "DIARIZATION_LOCAL_URL": "   ",
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match="DIARIZATION_LOCAL_URL"):
            create_diarization_engine()
