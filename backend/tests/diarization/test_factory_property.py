"""Property tests for the DiarizationEngine factory (factory.py).

# Feature: speaker-identification, Property 1: Provider selection by configuration
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import os
import socket
from unittest.mock import patch

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.diarization.factory import create_diarization_engine
from app.diarization.local_provider import LocalProvider

# ---------------------------------------------------------------------------
# Property 1: Provider selection by configuration
# Feature: speaker-identification, Property 1: Provider selection by configuration
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
    """Cloud is rejected regardless of capitalization or surrounding spaces."""
    provider_value = padding_left + word + padding_right
    env = {
        "DIARIZATION_PROVIDER": provider_value,
        "DIARIZATION_CLOUD_ENDPOINT": "https://example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "test-key",
    }
    with (
        patch.dict(os.environ, env, clear=False),
        pytest.raises(ValueError, match="DIARIZATION_PROVIDER"),
    ):
        create_diarization_engine()


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
# Feature: speaker-identification, Property 2: Invalid provider value flags an error with the received value
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
    with (
        patch.dict(os.environ, env, clear=False),
        pytest.raises(ValueError, match=re.escape(provider_value.strip())),
    ):
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
    """A cloud provider selection is rejected even when cloud settings exist."""
    env = {
        "DIARIZATION_PROVIDER": "cloud",
        "DIARIZATION_CLOUD_ENDPOINT": "https://api.diarization.example.com/diarize",
        "DIARIZATION_CLOUD_API_KEY": "sk-test-key-12345",
    }
    with (
        patch.dict(os.environ, env, clear=False),
        pytest.raises(ValueError, match="DIARIZATION_PROVIDER"),
    ):
        create_diarization_engine()


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
    with (
        patch.dict(os.environ, env, clear=False),
        pytest.raises(ValueError, match="DIARIZATION_LOCAL_URL"),
    ):
        create_diarization_engine()


# ---------------------------------------------------------------------------
# Fail-closed factory contract (GitHub #85, Task 1.1 — RED)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider_value",
    [None, "", " \t", "local", " LOCAL ", "LoCaL"],
)
def test_fail_closed_factory_defaults_only_to_local(provider_value: str | None):
    """Missing/empty/local provider values select local after normalization."""
    env = {"DIARIZATION_LOCAL_URL": " http://diar-engine:8000/ "}
    if provider_value is not None:
        env["DIARIZATION_PROVIDER"] = provider_value

    with patch.dict(os.environ, env, clear=False):
        if provider_value is None:
            os.environ.pop("DIARIZATION_PROVIDER", None)
        engine = create_diarization_engine()

    assert isinstance(engine, LocalProvider)
    assert engine._url == "http://diar-engine:8000"


@pytest.mark.parametrize("provider_value", ["cloud", "unrecognized-provider"])
def test_fail_closed_factory_rejects_non_local_before_cloud_import_or_side_effects(
    provider_value: str,
):
    """Non-local providers fail before cloud import, provider construction, or I/O."""
    import sys

    cloud_module_name = "app.diarization.cloud_provider"
    previously_loaded_cloud_module = sys.modules.pop(cloud_module_name, None)
    observations = {
        "cloud_imports": [],
        "cloud_constructions": [],
        "local_constructions": [],
        "clients": [],
        "requests": [],
        "connections": [],
    }

    original_local_init = LocalProvider.__init__

    def track_local_construction(instance, *args, **kwargs):
        observations["local_constructions"].append(instance)
        original_local_init(instance, *args, **kwargs)

    class ObservingLoader:
        """Record imports and constructor calls before factory code can use them."""

        def __init__(self, loader):
            self.loader = loader

        def create_module(self, spec):
            if hasattr(self.loader, "create_module"):
                return self.loader.create_module(spec)
            return None

        def exec_module(self, module):
            self.loader.exec_module(module)
            provider_class = module.CloudProvider
            original_init = provider_class.__init__

            def track_construction(instance, *args, **kwargs):
                observations["cloud_constructions"].append(instance)
                original_init(instance, *args, **kwargs)

            provider_class.__init__ = track_construction

    class CloudImportObserver(importlib.abc.MetaPathFinder):
        """Observe the import machinery, regardless of import statement spelling."""

        def find_spec(self, fullname, path=None, target=None):
            if fullname != cloud_module_name:
                return None
            observations["cloud_imports"].append(fullname)
            spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
            if spec is not None and spec.loader is not None:
                spec.loader = ObservingLoader(spec.loader)
            return spec

    def track_client_init(original_init, client_name):
        def tracked_init(instance, *args, **kwargs):
            observations["clients"].append(client_name)
            original_init(instance, *args, **kwargs)

        return tracked_init

    def block_request(*args, **kwargs):
        observations["requests"].append((args, kwargs))
        raise RuntimeError("outbound request blocked by factory test")

    def block_connection(*args, **kwargs):
        observations["connections"].append((args, kwargs))
        raise OSError("outbound connection blocked by factory test")

    cloud_import_observer = CloudImportObserver()

    env = {
        "DIARIZATION_PROVIDER": provider_value,
        "DIARIZATION_LOCAL_URL": "http://diar-engine:8000",
        "DIARIZATION_CLOUD_ENDPOINT": "https://example.invalid/diarize",
        "DIARIZATION_CLOUD_API_KEY": "synthetic-test-key",
    }
    try:
        sys.meta_path.insert(0, cloud_import_observer)
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(LocalProvider, "__init__", track_local_construction),
            patch.object(
                httpx.Client,
                "__init__",
                track_client_init(httpx.Client.__init__, "httpx.Client"),
            ),
            patch.object(
                httpx.AsyncClient,
                "__init__",
                track_client_init(httpx.AsyncClient.__init__, "httpx.AsyncClient"),
            ),
            patch.object(httpx.Client, "request", block_request),
            patch.object(httpx.AsyncClient, "request", block_request),
            patch.object(socket.socket, "connect", block_connection),
            patch.object(socket.socket, "connect_ex", block_connection),
        ):
            factory_error = None
            try:
                create_diarization_engine()
            except Exception as exc:
                factory_error = exc

        violations = []
        if observations["cloud_imports"]:
            violations.append("cloud provider module was imported")
        if observations["cloud_constructions"]:
            violations.append("cloud provider was constructed")
        if observations["local_constructions"]:
            violations.append("local provider was constructed")
        if observations["clients"]:
            violations.append(f"HTTP client(s) constructed: {observations['clients']}")
        if observations["requests"]:
            violations.append("outbound HTTP request was attempted")
        if observations["connections"]:
            violations.append("outbound socket connection was attempted")
        if not isinstance(factory_error, ValueError):
            violations.append(
                f"expected ValueError, got {type(factory_error).__name__}"
            )
        assert not violations, "; ".join(violations)
    finally:
        if cloud_import_observer in sys.meta_path:
            sys.meta_path.remove(cloud_import_observer)
        sys.modules.pop(cloud_module_name, None)
        if previously_loaded_cloud_module is not None:
            sys.modules[cloud_module_name] = previously_loaded_cloud_module


@pytest.mark.parametrize("local_url", [None, "", " \t "])
def test_fail_closed_factory_rejects_missing_local_url_before_side_effects(
    local_url: str | None,
):
    """Local selection without a usable URL fails before construction or I/O."""
    from app.diarization.local_provider import LocalProvider as LocalProviderClass

    env = {"DIARIZATION_PROVIDER": "local"}
    if local_url is not None:
        env["DIARIZATION_LOCAL_URL"] = local_url

    provider_constructions = []
    client_constructions = []
    requests = []
    connections = []
    original_init = LocalProviderClass.__init__
    original_http_client_init = httpx.Client.__init__
    original_async_http_client_init = httpx.AsyncClient.__init__

    def track_provider_construction(instance, *args, **kwargs):
        provider_constructions.append(instance)
        original_init(instance, *args, **kwargs)

    def track_http_client(instance, *args, **kwargs):
        client_constructions.append(instance)
        original_http_client_init(instance, *args, **kwargs)

    def track_async_http_client(instance, *args, **kwargs):
        client_constructions.append(instance)
        original_async_http_client_init(instance, *args, **kwargs)

    def block_request(*args, **kwargs):
        requests.append((args, kwargs))
        raise RuntimeError("outbound request blocked by factory test")

    def block_connection(*args, **kwargs):
        connections.append((args, kwargs))
        raise OSError("outbound connection blocked by factory test")

    with (
        patch.dict(os.environ, env, clear=False),
        patch.object(LocalProviderClass, "__init__", track_provider_construction),
        patch.object(httpx.Client, "__init__", track_http_client),
        patch.object(httpx.AsyncClient, "__init__", track_async_http_client),
        patch.object(httpx.Client, "request", block_request),
        patch.object(httpx.AsyncClient, "request", block_request),
        patch.object(socket.socket, "connect", block_connection),
        patch.object(socket.socket, "connect_ex", block_connection),
    ):
        if local_url is None:
            os.environ.pop("DIARIZATION_LOCAL_URL", None)
        factory_error = None
        try:
            create_diarization_engine()
        except Exception as exc:
            factory_error = exc

    violations = []
    if (
        not isinstance(factory_error, ValueError)
        or "DIARIZATION_LOCAL_URL" not in str(factory_error)
    ):
        violations.append("expected ValueError identifying DIARIZATION_LOCAL_URL")
    if provider_constructions:
        violations.append("local provider was constructed")
    if client_constructions:
        violations.append("HTTP client was constructed")
    if requests:
        violations.append("outbound HTTP request was attempted")
    if connections:
        violations.append("outbound socket connection was attempted")
    assert not violations, "; ".join(violations)
