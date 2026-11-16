"""Secret store behaviour: file store properties, Keychain command shape against a fake binary."""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sauri_engine_common import secrets as secrets_module
from sauri_engine_common.secrets import (
    FileSecretStore,
    InvalidSecretError,
    InvalidSecretRefError,
    KeychainSecretStore,
    SecretRecord,
    SecretTooLargeError,
    SecretUnavailableError,
    default_secret_store,
    key_hint,
    validate_ref,
)

REF = "sauri/owner-1/provider-1"
ORIGIN = "https://api.example.com"
# The prefix keeps a random key from being a substring of fixed text (``repr``, command names).
KEYS = st.text(max_size=300).map(lambda text: "KEY-" + text)
SLOW = settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# --- key_hint and records -------------------------------------------------------------------------


@given(st.text(min_size=12, max_size=400))
def test_key_hint_is_exactly_the_last_four_for_long_keys(key: str) -> None:
    assert key_hint(key) == key[-4:]


@given(st.text(max_size=11))
def test_key_hint_is_absent_for_short_keys(key: str) -> None:
    assert key_hint(key) is None


@given(KEYS)
def test_record_repr_and_str_never_contain_the_key(key: str) -> None:
    record = SecretRecord(key=key, origin=ORIGIN)
    for text in (repr(record), str(record), f"{record}", repr([record]), repr({"r": record})):
        assert key not in text
        assert "key=***" in text


@pytest.mark.parametrize("ref", ["", "a b", "a\nb", "ñ", "a;b", "a" * 201, "../x\x00", "sauri/ünï"])
def test_invalid_refs_are_rejected(ref: str) -> None:
    with pytest.raises(InvalidSecretRefError) as caught:
        validate_ref(ref)
    assert str(caught.value) == "invalid_secret_ref"


@pytest.mark.parametrize("ref", ["a", "sauri/owner/provider", "A.b_c-d/e", "a" * 200])
def test_valid_refs_are_accepted(ref: str) -> None:
    assert validate_ref(ref) == ref


# --- FileSecretStore --------------------------------------------------------------------------------


def test_file_store_creates_private_folder_and_file(tmp_path: Path) -> None:
    root = tmp_path / "cfg" / "secrets"
    store = FileSecretStore(root)
    store.put(REF, SecretRecord(key="k" * 20, origin=ORIGIN))
    assert _mode(root) == 0o700
    files = list(root.iterdir())
    assert len(files) == 1 and _mode(files[0]) == 0o600
    assert not [path for path in files if path.name.startswith(".tmp-")]


def test_file_store_put_replaces_and_delete_removes(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "secrets")
    store.put(REF, SecretRecord(key="first-key-value", origin=ORIGIN))
    store.put(REF, SecretRecord(key="second-key-value", origin="https://other.example.com"))
    assert store.get(REF) == SecretRecord(key="second-key-value", origin="https://other.example.com")
    assert len(list((tmp_path / "secrets").iterdir())) == 1
    store.delete(REF)
    with pytest.raises(SecretUnavailableError) as caught:
        store.get(REF)
    assert str(caught.value) == "secret_unavailable"
    store.delete(REF)  # idempotent


def test_file_store_tightens_a_loose_folder(tmp_path: Path) -> None:
    root = tmp_path / "secrets"
    root.mkdir(mode=0o755)
    FileSecretStore(root).put(REF, SecretRecord(key="k" * 20, origin=ORIGIN))
    assert _mode(root) == 0o700


def test_file_store_refuses_a_symlinked_folder(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "secrets"
    link.symlink_to(target)
    with pytest.raises(SecretUnavailableError):
        FileSecretStore(link).put(REF, SecretRecord(key="k" * 20, origin=ORIGIN))
    assert list(target.iterdir()) == []


def test_file_store_does_not_follow_a_symlinked_secret(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "secrets")
    store.put(REF, SecretRecord(key="k" * 20, origin=ORIGIN))
    (path,) = (tmp_path / "secrets").iterdir()
    decoy = tmp_path / "decoy"
    decoy.write_text(json.dumps({"key": "stolen", "origin": ORIGIN}))
    path.unlink()
    path.symlink_to(decoy)
    with pytest.raises(SecretUnavailableError):
        store.get(REF)


@pytest.mark.parametrize("payload", ["", "not json", "[]", '{"key": 1, "origin": "x"}', '{"key": "", "origin": "x"}'])
def test_file_store_rejects_corrupt_files(tmp_path: Path, payload: str) -> None:
    store = FileSecretStore(tmp_path / "secrets")
    store.put(REF, SecretRecord(key="k" * 20, origin=ORIGIN))
    (path,) = (tmp_path / "secrets").iterdir()
    path.write_text(payload)
    with pytest.raises(SecretUnavailableError):
        store.get(REF)


def test_empty_key_or_origin_is_invalid(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "secrets")
    for record in (SecretRecord(key="", origin=ORIGIN), SecretRecord(key="k" * 20, origin="")):
        with pytest.raises(InvalidSecretError):
            store.put(REF, record)


def test_file_store_failure_to_write_is_secret_unavailable(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(SecretUnavailableError):
        FileSecretStore(blocker / "secrets").put(REF, SecretRecord(key="k" * 20, origin=ORIGIN))


@SLOW
@given(KEYS, st.from_regex(r"[A-Za-z0-9._/-]{1,200}", fullmatch=True))
def test_file_store_round_trips_any_key(key: str, ref: str) -> None:
    with tempfile.TemporaryDirectory() as folder:
        store = FileSecretStore(Path(folder) / "secrets")
        record = SecretRecord(key=key, origin=ORIGIN)
        store.put(ref, record)
        assert store.get(ref) == record
        (path,) = (Path(folder) / "secrets").iterdir()
        assert _mode(path) == 0o600 and _mode(Path(folder) / "secrets") == 0o700


@SLOW
@given(KEYS)
def test_secrets_stay_out_of_logs_errors_and_representations(key: str) -> None:
    """Property 3 and 4 at the store level: no key in logs, exception text or hints beyond four chars."""
    logger = logging.getLogger()
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = Capture(level=logging.DEBUG)
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        with tempfile.TemporaryDirectory() as folder:
            store = FileSecretStore(Path(folder) / "secrets")
            record = SecretRecord(key=key, origin=ORIGIN)
            store.put(REF, record)
            store.get(REF)
            store.delete(REF)
            errors: list[str] = []
            attempts = (
                lambda: store.get(REF),
                lambda: store.get("bad ref"),
                lambda: store.put(REF, SecretRecord("", "")),
            )
            for action in attempts:
                try:
                    action()
                except Exception as exc:
                    errors.append(f"{exc} {exc!r}")
            assert key_hint(key) == (key[-4:] if len(key) >= 12 else None)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    assert all(key not in text for text in [*records, *errors])


# --- KeychainSecretStore against a fake /usr/bin/security -------------------------------------------

FAKE_SECURITY = '''#!{python}
import json, os, shlex, sys, time
state_path = os.environ["FAKE_SECURITY_STATE"]
log_path = os.environ["FAKE_SECURITY_LOG"]
mode = os.environ.get("FAKE_SECURITY_MODE", "ok")
state = json.load(open(state_path)) if os.path.exists(state_path) else {{}}
with open(log_path, "a") as log:
    log.write(json.dumps({{"argv": sys.argv[1:]}}) + "\\n")

def save():
    json.dump(state, open(state_path, "w"))

def run(args):
    cmd = args[0]
    opts = dict(zip(args[1::1], args[2::1]))
    if cmd == "default-keychain":
        return 0
    if cmd == "add-generic-password":
        if mode == "silent-drop":
            return 0
        state[opts["-s"] + "|" + opts["-a"]] = opts["-w"]
        save()
        return 0
    if cmd == "find-generic-password":
        value = state.get(opts["-s"] + "|" + opts["-a"])
        if value is None:
            return 44
        print(value)
        return 0
    if cmd == "delete-generic-password":
        if state.pop(opts["-s"] + "|" + opts["-a"], None) is None:
            return 44
        save()
        return 0
    return 1

if mode == "hang":
    time.sleep(30)
if sys.argv[1:2] == ["-i"]:
    for line in sys.stdin:
        with open(log_path, "a") as log:
            log.write(json.dumps({{"stdin_command": line.split()[0]}}) + "\\n")
        run(shlex.split(line))
    sys.exit(0)
sys.exit(run(sys.argv[1:]))
'''


@pytest.fixture
def fake_security(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binary = tmp_path / "security"
    binary.write_text(FAKE_SECURITY.format(python=sys.executable))
    binary.chmod(0o700)
    monkeypatch.setenv("FAKE_SECURITY_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("FAKE_SECURITY_LOG", str(tmp_path / "calls.log"))
    return binary


def _argv_calls(tmp_path: Path) -> list[list[str]]:
    lines = (tmp_path / "calls.log").read_text().splitlines()
    return [json.loads(line)["argv"] for line in lines if "argv" in json.loads(line)]


def test_keychain_put_sends_the_secret_by_stdin_never_argv(fake_security: Path, tmp_path: Path) -> None:
    store = KeychainSecretStore(service="sauri-test-unit", binary=str(fake_security))
    key = "sk-very-secret-key-123456"
    record = SecretRecord(key=key, origin=ORIGIN)
    store.put(REF, record)
    assert store.get(REF) == record
    calls = _argv_calls(tmp_path)
    assert calls[0] == ["-i"]
    flat = " ".join(" ".join(call) for call in calls)
    stored = json.loads((tmp_path / "state.json").read_text())["sauri-test-unit|" + REF]
    assert key not in flat and stored not in flat and ORIGIN not in flat
    store.delete(REF)
    with pytest.raises(SecretUnavailableError):
        store.get(REF)
    store.delete(REF)  # item not found is a no-op


@SLOW
@given(KEYS)
def test_keychain_round_trips_awkward_keys(key: str) -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        binary = root / "security"
        binary.write_text(FAKE_SECURITY.format(python=sys.executable))
        binary.chmod(0o700)
        os.environ["FAKE_SECURITY_STATE"] = str(root / "state.json")
        os.environ["FAKE_SECURITY_LOG"] = str(root / "calls.log")
        try:
            store = KeychainSecretStore(service="sauri-test-unit", binary=str(binary))
            record = SecretRecord(key=key, origin=ORIGIN)
            store.put(REF, record)
            assert store.get(REF) == record
            assert key not in (root / "calls.log").read_text()
        finally:
            os.environ.pop("FAKE_SECURITY_STATE", None)
            os.environ.pop("FAKE_SECURITY_LOG", None)


def test_keychain_refuses_a_record_that_the_interactive_command_line_would_truncate(
    fake_security: Path, tmp_path: Path
) -> None:
    store = KeychainSecretStore(service="sauri-test-unit", binary=str(fake_security))
    with pytest.raises(SecretTooLargeError) as caught:
        store.put(REF, SecretRecord(key="K" * 3000, origin=ORIGIN))
    assert str(caught.value) == "secret_too_large" and isinstance(caught.value, InvalidSecretError)
    assert not (tmp_path / "calls.log").exists()  # nothing was sent
    store.put(REF, SecretRecord(key="K" * 2048, origin="https://" + "a" * 240 + ".com"))  # the host's maximum


def test_keychain_put_detects_a_silent_failure(fake_security: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_SECURITY_MODE", "silent-drop")
    store = KeychainSecretStore(service="sauri-test-unit", binary=str(fake_security))
    with pytest.raises(SecretUnavailableError):
        store.put(REF, SecretRecord(key="k" * 20, origin=ORIGIN))


def test_keychain_timeout_is_secret_unavailable(fake_security: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_SECURITY_MODE", "hang")
    store = KeychainSecretStore(service="sauri-test-unit", binary=str(fake_security), timeout_s=0.3)
    with pytest.raises(SecretUnavailableError):
        store.get(REF)


def test_keychain_missing_binary_is_secret_unavailable(tmp_path: Path) -> None:
    store = KeychainSecretStore(service="sauri-test-unit", binary=str(tmp_path / "missing"))
    with pytest.raises(SecretUnavailableError):
        store.get(REF)


def test_keychain_rejects_a_service_name_that_needs_quoting() -> None:
    with pytest.raises(InvalidSecretRefError):
        KeychainSecretStore(service="bad service")


# --- default_secret_store ---------------------------------------------------------------------------


def test_default_store_is_the_file_store_when_forced_or_off_macos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SAURI_SECRET_STORE", "file")
    store = default_secret_store()
    assert isinstance(store, FileSecretStore) and store.root == tmp_path / ".config" / "sauri" / "secrets"
    monkeypatch.delenv("SAURI_SECRET_STORE")
    monkeypatch.setattr(sys, "platform", "linux")
    assert isinstance(default_secret_store(), FileSecretStore)


def test_default_store_uses_the_keychain_on_macos_only_when_it_answers(
    fake_security: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SAURI_SECRET_STORE", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(secrets_module, "SECURITY_BINARY", str(fake_security))
    assert isinstance(default_secret_store(), KeychainSecretStore)
    monkeypatch.setattr(secrets_module, "SECURITY_BINARY", str(tmp_path / "missing"))
    assert isinstance(default_secret_store(), FileSecretStore)
