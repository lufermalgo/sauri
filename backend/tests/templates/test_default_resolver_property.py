"""Property tests for personal default template resolution."""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import given, settings
from hypothesis import strategies as st

from app.templates.default_resolver import ResolvedDefault, resolve_default


@dataclass(frozen=True)
class SyntheticTemplate:
    """Minimal synthetic row shape consumed by the pure default resolver."""

    id: str
    version: int

    @property
    def category_id(self) -> str:
        raise AssertionError("default resolution must not read template category")


@settings(max_examples=100)
@given(template_id=st.text(min_size=1), version=st.integers(min_value=1))
def test_nullable_default_resolution_returns_none_only_for_missing_row(
    template_id: str, version: int
) -> None:
    """A missing default row resolves to None; a present row resolves to a selection."""
    assert resolve_default(None) is None
    assert resolve_default(SyntheticTemplate(id=template_id, version=version)) == (
        ResolvedDefault(template_id=template_id, version=version)
    )


@settings(max_examples=100)
@given(template_id=st.text(min_size=1), version=st.integers(min_value=1))
def test_resolution_preserves_exact_template_id_and_version(
    template_id: str, version: int
) -> None:
    """The resolver selects the exact configured template snapshot, not a substitute."""
    result = resolve_default(SyntheticTemplate(id=template_id, version=version))

    assert result == ResolvedDefault(template_id=template_id, version=version)
    assert result.template_id == template_id
    assert result.version == version


@settings(max_examples=100)
@given(template_id=st.text(min_size=1), version=st.integers(min_value=1))
def test_resolution_is_category_blind(
    template_id: str, version: int
) -> None:
    """Category data is outside the resolver contract and must not be inspected."""
    result = resolve_default(SyntheticTemplate(id=template_id, version=version))

    assert result == ResolvedDefault(template_id=template_id, version=version)
