"""Anonymous speaker labels shown to the summary model, by transcript language.

Spanish transcripts use the owner-approved Spanish label so the model does not copy an English
word into a Spanish summary. Any other language keeps the English label.
"""

_SPANISH = "es"


def _is_spanish(language: str) -> bool:
    return language.lower().replace("_", "-").split("-")[0] == _SPANISH


def speaker_label(number: int, language: str) -> str:
    return f"Hablante {number}" if _is_spanish(language) else f"Speaker {number}"


def unknown_speaker_label(language: str) -> str:
    return "Hablante ?" if _is_spanish(language) else "Speaker ?"
