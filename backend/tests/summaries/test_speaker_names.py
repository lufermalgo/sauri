"""Pure substitution of anonymous speaker labels by the owner's chosen names (#1190)."""

import pytest

from app.summaries.speaker_names import apply_speaker_names, substitute_speaker_names

NAMES = {1: "Ana", 2: "Pedro Pablo"}


def test_spanish_labels_are_replaced_and_english_ones_are_not() -> None:
    text = "Hablante 2 pidio revisar lo que dijo Hablante 1; Speaker 2 no cambia."  # spanish-sample-data
    assert substitute_speaker_names(text, NAMES, "es-CO") == (
        "Pedro Pablo pidio revisar lo que dijo Ana; Speaker 2 no cambia."  # spanish-sample-data
    )


def test_other_languages_use_the_english_label() -> None:
    text = "Speaker 2 agreed with Speaker 1; Hablante 2 is untouched."  # spanish-sample-data
    expected = "Pedro Pablo agreed with Ana; Hablante 2 is untouched."  # spanish-sample-data
    assert substitute_speaker_names(text, NAMES, "en") == expected


@pytest.mark.parametrize(
    "text",
    [
        "Hablante 20 hablo",  # spanish-sample-data
        "Hablante 2x hablo",  # spanish-sample-data
        "Hablante 12 hablo",  # spanish-sample-data
        "xHablante 2 hablo",  # spanish-sample-data
        "Hablante ? hablo",  # spanish-sample-data
        "Hablante 3 hablo",  # spanish-sample-data
        "Hablante  2 hablo",  # spanish-sample-data
        "Hablante2 hablo",  # spanish-sample-data
    ],
)
def test_only_the_whole_word_and_whole_number_match(text: str) -> None:
    assert substitute_speaker_names(text, NAMES, "es") == text


def test_matching_ignores_case_and_punctuation_around_the_label() -> None:
    text = "**HABLANTE 1**, hablante 2."  # spanish-sample-data
    assert substitute_speaker_names(text, NAMES, "es") == "**Ana**, Pedro Pablo."
    assert substitute_speaker_names("(Speaker 1)'s idea", NAMES, "en") == "(Ana)'s idea"


LITERAL_NAMES = [r"\1", r"\g<0>", "$1", "&", "\\", "<b>Ana</b>", 'Ana "La Jefa"', "O'Brien", "${name}"]


@pytest.mark.parametrize("name", LITERAL_NAMES)
def test_names_are_inserted_literally(name: str) -> None:
    assert substitute_speaker_names("Speaker 1 spoke", {1: name}, "en") == f"{name} spoke"


def test_a_name_that_looks_like_a_label_is_not_replaced_again() -> None:
    assert substitute_speaker_names("Speaker 1 and Speaker 2", {1: "Speaker 2", 2: "Speaker 1"}, "en") == (
        "Speaker 2 and Speaker 1"
    )


@pytest.mark.parametrize("names", [{}, {1: ""}, {1: "   "}, {1: "\n\t"}])
def test_no_usable_name_leaves_the_text_untouched(names: dict[int, str]) -> None:
    assert substitute_speaker_names("Speaker 1 spoke", names, "en") == "Speaker 1 spoke"


def test_a_blank_name_does_not_block_other_speakers_and_names_are_trimmed() -> None:
    assert substitute_speaker_names("Speaker 1, Speaker 2", {1: "  ", 2: "  Luis "}, "en") == "Speaker 1, Luis"


def test_nested_key_points_are_walked_and_non_text_is_kept() -> None:
    key_points = [
        {
            "title": "Speaker 1 opens",
            "items": [{"text": "Speaker 2 objects", "sub_items": ["Speaker 1 replies", "Speaker 3 listens"]}],
            "sources": [{"passage_id": "P0001", "start_ms": 0, "end_ms": 5}],
        },
        {"text": "Speaker 2 closes", "sources": [{"passage_id": "P0002", "start_ms": 1, "end_ms": 2}]},
        "Legacy: Speaker 1",
        7,
        None,
    ]
    result = apply_speaker_names(key_points, NAMES, "en")
    assert result == [
        {
            "title": "Ana opens",
            "items": [{"text": "Pedro Pablo objects", "sub_items": ["Ana replies", "Speaker 3 listens"]}],
            "sources": [{"passage_id": "P0001", "start_ms": 0, "end_ms": 5}],
        },
        {"text": "Pedro Pablo closes", "sources": [{"passage_id": "P0002", "start_ms": 1, "end_ms": 2}]},
        "Legacy: Ana",
        7,
        None,
    ]
    assert key_points[0]["title"] == "Speaker 1 opens"  # type: ignore[index]  # the input is not mutated


def test_none_and_empty_names_return_the_value_as_is() -> None:
    assert apply_speaker_names(None, NAMES, "en") is None
    value = ["Speaker 1"]
    assert apply_speaker_names(value, {}, "en") is value
