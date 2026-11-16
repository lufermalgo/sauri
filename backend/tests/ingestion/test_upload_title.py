"""Upload meeting title defaults to a safe recording filename."""

from app.ingestion.service import resolve_upload_title


def test_upload_title_defaults_to_safe_basename_when_title_is_missing() -> None:
    assert resolve_upload_title(None, r"C:\\private\\sales\\Quarterly <Plan>.webm") == (
        "Quarterly <Plan>.webm"
    )


def test_upload_title_defaults_when_explicit_title_is_empty_or_whitespace() -> None:
    assert resolve_upload_title("", "synthetic-recording.webm") == "synthetic-recording.webm"
    assert resolve_upload_title(" \t ", "synthetic-recording.webm") == "synthetic-recording.webm"


def test_upload_title_preserves_a_nonempty_explicit_title() -> None:
    assert resolve_upload_title("  Explicit title  ", "recording.webm") == "  Explicit title  "


def test_upload_title_is_bounded_to_meeting_title_limit() -> None:
    filename = "x" * 600 + ".webm"
    assert len(resolve_upload_title(None, filename)) == 512


def test_upload_title_uses_safe_fallback_for_filename_without_basename() -> None:
    assert resolve_upload_title(None, r"C:\\private\\") == "Untitled recording"


def test_upload_title_drops_control_characters_and_path_components() -> None:
    assert resolve_upload_title(None, "../../etc/pa\x00ss\r\nwd.webm") == "passwd.webm"
    assert resolve_upload_title(None, "\x00\x1b[31m\n") == "[31m"
    assert resolve_upload_title(None, "\x00\n\t") == "Untitled recording"
