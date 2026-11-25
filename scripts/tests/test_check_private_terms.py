from __future__ import annotations

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "check_private_terms", Path(__file__).parents[1] / "dev" / "check_private_terms.py"
)
assert SPEC and SPEC.loader
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)

TERMS = """
# comment
acme
re:north\\s?wind
allow:acme-placeholder
"""


def scan(line: str) -> list[str]:
    matchers, allow = check.parse_terms(TERMS)
    return check.scan_line(line, matchers, allow)


def test_terms_match_whole_words_ignoring_case_and_accents() -> None:
    assert scan("Meeting with ACME today") == ["acme"]
    assert scan("Reunión con Ácme") == ["acme"]
    assert scan("acmesoft is a different word") == []


def test_regex_terms_and_allow_lines() -> None:
    assert scan("North Wind summary") == ["re:north\\s?wind"]
    assert scan("uses acme-placeholder as an example") == []


def test_real_user_paths_are_reported_but_placeholders_are_not() -> None:
    assert scan("/Users/jdoe/Projects/x") == ["absolute path of a real user (/Users/jdoe); use ~/ or a placeholder"]
    assert scan("/Users/test/Recordings and /Volumes/External") == []


def test_credential_shapes_are_reported() -> None:
    assert scan("token ghp_" + "a" * 36) == ["credential-shaped text"]
    assert scan("PROVIDER_KEY = 'sk-synthetic-value'") == []
