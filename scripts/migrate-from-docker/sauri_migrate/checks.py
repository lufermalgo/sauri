"""Pure decisions: free space, and the comparison behind property 8 (rows per table, {key, size, MD5})."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .objects import ObjectRecord

SPACE_MARGIN = 1.10
SPACE_RESERVE_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class SpaceNeed:
    label: str
    path: Path
    bytes: int


@dataclass(frozen=True)
class SpaceCheck:
    labels: list[str]
    path: str
    required_bytes: int
    available_bytes: int

    @property
    def enough(self) -> bool:
        return self.available_bytes >= self.required_bytes


def existing_parent(path: Path) -> Path:
    path = path.expanduser().absolute()
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def check_space(
    needs: Iterable[SpaceNeed],
    free_bytes: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free,
    device: Callable[[Path], int] = lambda path: os.stat(path).st_dev,
) -> list[SpaceCheck]:
    """Needs on the same volume add up; each volume must hold them plus a margin and a reserve."""
    grouped: dict[int, list[tuple[SpaceNeed, Path]]] = {}
    for need in needs:
        anchor = existing_parent(need.path)
        grouped.setdefault(device(anchor), []).append((need, anchor))
    checks: list[SpaceCheck] = []
    for items in grouped.values():
        total = sum(need.bytes for need, _ in items)
        anchor = items[0][1]
        checks.append(SpaceCheck(
            labels=[need.label for need, _ in items], path=str(anchor),
            required_bytes=int(total * SPACE_MARGIN) + SPACE_RESERVE_BYTES, available_bytes=free_bytes(anchor),
        ))
    return checks


@dataclass(frozen=True)
class Difference:
    kind: str
    name: str
    source: Any = None
    target: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def compare_rows(
    source_before: Mapping[str, int], source_after: Mapping[str, int], target: Mapping[str, int],
) -> list[Difference]:
    differences: list[Difference] = []
    for table in sorted(set(source_before) | set(source_after)):
        if source_before.get(table) != source_after.get(table):
            differences.append(Difference("source_changed_rows", table, source_before.get(table),
                                          source_after.get(table)))
    for table in sorted(source_after):
        if table not in target:
            differences.append(Difference("table_missing_in_target", table, source_after[table]))
        elif target[table] != source_after[table]:
            differences.append(Difference("row_count", table, source_after[table], target[table]))
    for table in sorted(set(target) - set(source_after)):
        # Tables added by the app's newer migrations (job_messages) must start empty.
        if target[table] != 0:
            differences.append(Difference("new_table_not_empty", table, None, target[table]))
    return differences


def compare_objects(
    source: Mapping[str, ObjectRecord], source_after: Mapping[str, tuple[int, str]],
    source_before: Mapping[str, tuple[int, str]], target: Mapping[str, ObjectRecord],
) -> list[Difference]:
    """`source` holds the verified records; the (size, ETag) listings before and after detect source changes."""
    differences: list[Difference] = []
    for key in sorted(set(source_before) | set(source_after)):
        if source_before.get(key) != source_after.get(key):
            differences.append(Difference("source_changed_object", key))
    for key in sorted(source):
        expected = source[key]
        found = target.get(key)
        if found is None:
            differences.append(Difference("object_missing_in_target", key, expected.size))
        elif found.size != expected.size:
            differences.append(Difference("object_size", key, expected.size, found.size))
        elif found.md5 != expected.md5:
            differences.append(Difference("object_md5", key, expected.md5, found.md5))
    for key in sorted(set(target) - set(source)):
        differences.append(Difference("object_extra_in_target", key, None, target[key].size))
    return differences
