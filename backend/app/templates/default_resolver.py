"""Pure resolution of a user's configured default summary template."""

from __future__ import annotations

from typing import NamedTuple, Protocol


class ResolvedDefault(NamedTuple):
    """The exact template snapshot selected as a personal default."""

    template_id: str
    version: int


class _TemplateRow(Protocol):
    """Minimal template-row attributes needed for default resolution."""

    @property
    def id(self) -> str: ...

    @property
    def version(self) -> int: ...


def resolve_default(template_row: _TemplateRow | None) -> ResolvedDefault | None:
    """Resolve a configured default without fallback or category inspection."""
    if template_row is None:
        return None
    return ResolvedDefault(template_id=template_row.id, version=template_row.version)
