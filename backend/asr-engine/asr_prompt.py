"""Bound private vocabulary prompts without a tokenizer dependency."""

from pathlib import Path

# Whisper's 448-token text context reserves half for the initial prompt.
# UTF-8 bytes upper-bound byte-BPE tokens, including non-Latin entries.
PROMPT_BYTE_LIMIT = 224
_PROMPT_PREFIX = "Hola. Estos son los nombres propios: "


def vocabulary_prompt(path: Path) -> str | None:
    try:
        source = path.open(encoding="utf-8")
    except FileNotFoundError:
        return None
    terms: list[str] = []
    with source:
        for line in source:
            term = " ".join(line.split())
            if not term or not term.isprintable() or term in terms:
                continue
            candidate = _PROMPT_PREFIX + ", ".join([*terms, term]) + "."
            if len(candidate.encode("utf-8")) <= PROMPT_BYTE_LIMIT:
                terms.append(term)
    return _PROMPT_PREFIX + ", ".join(terms) + "." if terms else None
