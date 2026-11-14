"""Credentials come from private files first and are injected into URLs safely."""

from __future__ import annotations

import pytest

from app.infra import secrets
from app.infra.database import get_database_url
from app.infra.secrets import SecretUnavailableError, object_store_credentials, read_secret, with_password


def test_file_wins_over_value_and_is_stripped(tmp_path, monkeypatch):
    secret_file = tmp_path / "secret"
    secret_file.write_text("from-file\n", encoding="utf-8")
    monkeypatch.setenv("SAMPLE_FILE", str(secret_file))
    monkeypatch.setenv("SAMPLE", "from-env")
    assert read_secret("SAMPLE_FILE", "SAMPLE") == "from-file"


def test_value_fallback_and_absence(monkeypatch):
    monkeypatch.delenv("SAMPLE_FILE", raising=False)
    monkeypatch.setenv("SAMPLE", "from-env")
    assert read_secret("SAMPLE_FILE", "SAMPLE") == "from-env"
    monkeypatch.delenv("SAMPLE")
    assert read_secret("SAMPLE_FILE", "SAMPLE") is None


@pytest.mark.parametrize("content", ["", "  \n"])
def test_empty_file_is_rejected_without_leaking(tmp_path, monkeypatch, content):
    secret_file = tmp_path / "secret"
    secret_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("SAMPLE_FILE", str(secret_file))
    with pytest.raises(SecretUnavailableError):
        read_secret("SAMPLE_FILE")


def test_missing_file_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLE_FILE", str(tmp_path / "absent"))
    with pytest.raises(SecretUnavailableError):
        read_secret("SAMPLE_FILE")


def test_with_password_encodes_and_keeps_host_port_path():
    url = with_password("amqp://sauri@rabbitmq:5672/vhost?heartbeat=30", "p@ss/word:1")
    assert url == "amqp://sauri:p%40ss%2Fword%3A1@rabbitmq:5672/vhost?heartbeat=30"
    assert with_password("amqp://sauri@rabbitmq:5672/", None) == "amqp://sauri@rabbitmq:5672/"


def test_with_password_requires_user():
    with pytest.raises(SecretUnavailableError):
        with_password("amqp://rabbitmq:5672/", "x")


def test_database_url_uses_password_file(tmp_path, monkeypatch):
    secret_file = tmp_path / "database_password"
    secret_file.write_text("abc123\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://sauri@postgres:5432/sauri")
    monkeypatch.setenv("DATABASE_PASSWORD_FILE", str(secret_file))
    assert get_database_url() == "postgresql+asyncpg://sauri:abc123@postgres:5432/sauri"


def test_object_store_credentials_prefer_files(tmp_path, monkeypatch):
    (tmp_path / "ak").write_text("sauri-ak\n", encoding="utf-8")
    (tmp_path / "sk").write_text("sk-value\n", encoding="utf-8")
    monkeypatch.setenv("OBJECT_STORE_ACCESS_KEY_FILE", str(tmp_path / "ak"))
    monkeypatch.setenv("OBJECT_STORE_SECRET_KEY_FILE", str(tmp_path / "sk"))
    monkeypatch.setenv("MINIO_ROOT_USER", "ignored")
    assert object_store_credentials() == ("sauri-ak", "sk-value")


def test_object_store_credentials_required(monkeypatch):
    for name in (
        "OBJECT_STORE_ACCESS_KEY_FILE",
        "OBJECT_STORE_SECRET_KEY_FILE",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SecretUnavailableError):
        secrets.object_store_credentials()
