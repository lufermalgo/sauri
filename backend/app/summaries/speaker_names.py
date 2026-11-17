"""Show the owner's chosen speaker names in a summary, at read time (#1190).

The stored summary keeps the anonymous labels the model saw ("Speaker 2", or its Spanish form). Nothing here
writes anything: the labels are replaced in the response only, so a renamed speaker shows up on the next read.
"""

import re
from collections.abc import Mapping
from typing import Any, TypeVar

from app.copy.speaker_labels import speaker_label

T = TypeVar("T")


def substitute_speaker_names(text: str, names: Mapping[int, str], language: str) -> str:
    """Replace each anonymous label whose speaker number has a non-blank name in ``names``.

    Whole words only: the label must not touch a word character on either side, so "Speaker 2" leaves
    "Speaker 20", "Speaker 2x" and "Speaker ?" alone. Matching ignores case. One pass over the text, so a
    name that is itself a label ("Speaker 1") is never replaced again. The replacement is a function, so
    characters such as ``\\1``, ``\\g<0>``, ``$1`` or ``&`` in a name stay literal.
    """
    by_label = {speaker_label(number, language).casefold(): name.strip() for number, name in names.items()}
    by_label = {label: name for label, name in by_label.items() if name}
    if not by_label:
        return text
    labels = "|".join(re.escape(speaker_label(number, language)) for number, name in names.items() if name.strip())
    pattern = re.compile(rf"(?<!\w)(?:{labels})(?!\w)", re.IGNORECASE)
    return pattern.sub(lambda match: by_label[match.group(0).casefold()], text)


def apply_speaker_names(value: T, names: Mapping[int, str], language: str) -> T:
    """Substitute in every string of ``value``: text and any nesting of lists and dicts (decoded key points)."""
    return _walk(value, names, language) if names else value


def _walk(value: Any, names: Mapping[int, str], language: str) -> Any:
    if isinstance(value, str):
        return substitute_speaker_names(value, names, language)
    if isinstance(value, list):
        return [_walk(item, names, language) for item in value]
    if isinstance(value, dict):
        return {key: _walk(item, names, language) for key, item in value.items()}
    return value
