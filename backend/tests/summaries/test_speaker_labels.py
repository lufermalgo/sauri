"""Anonymous speaker labels follow the transcript language and reach the model unchanged."""

import json

import httpx
import pytest

from app.copy.speaker_labels import speaker_label, unknown_speaker_label
from app.summaries.engine import OpenAICompatibleSummarizationEngine
from app.summaries.passages import Turn, build_passages

CONTENT = {
    "topic": "ok", "conclusion": "done",
    "key_points": [{"title": "block", "items": [{"text": "point", "sub_items": []}],
                    "sources": [{"passage_id": "P0000"}]}],
}


@pytest.mark.parametrize("language", ["es", "es-CO", "es_MX", "ES"])
def test_spanish_transcripts_use_spanish_labels(language: str) -> None:
    assert speaker_label(3, language) == "Hablante 3"  # spanish-sample-data
    assert unknown_speaker_label(language) == "Hablante ?"  # spanish-sample-data


@pytest.mark.parametrize("language", ["en", "en-US", "pt", "essay"])
def test_other_languages_keep_english_labels(language: str) -> None:
    assert speaker_label(3, language) == "Speaker 3"
    assert unknown_speaker_label(language) == "Speaker ?"


def test_assigned_names_render_unchanged() -> None:
    passage = build_passages([Turn("hola", 0, 1000, "Ana Perez"), Turn("si", 1000, 2000, speaker_label(2, "es"))])[0]
    assert passage.render().splitlines()[0].endswith("Ana Perez: hola")
    assert "Hablante 2: si" in passage.render()  # spanish-sample-data


async def test_engine_request_carries_spanish_labels() -> None:
    passages = build_passages([
        Turn("uno", 0, 1000, speaker_label(3, "es")), Turn("dos", 1000, 2000, unknown_speaker_label("es")),
    ])
    sent: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)["messages"]
        sent.extend(message["content"] for message in body)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(CONTENT)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        engine = OpenAICompatibleSummarizationEngine("http://localhost/v1", "synthetic", client=client)
        await engine.generate(passages, "Summarize")
    user_message = sent[1]
    assert "Hablante 3: uno" in user_message and "Hablante ?: dos" in user_message  # spanish-sample-data
    assert "Speaker" not in user_message
