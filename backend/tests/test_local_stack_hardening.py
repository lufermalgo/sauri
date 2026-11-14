"""The local stack publishes ports only on loopback and carries no fixed credentials."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
WEAK_VALUES = ("sauri_dev", "minioadmin", "guest:guest", "dev-secret-change-in-production")


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_every_published_port_binds_loopback_only() -> None:
    for name, service in _compose()["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} beyond this machine"


def test_no_fixed_credentials_in_compose() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    for weak in WEAK_VALUES:
        assert weak not in text
    assert not re.search(r"(PASSWORD|SECRET|MINIO_ROOT_USER)=(?!/run/secrets/)", text)


def test_services_read_credentials_from_mounted_files() -> None:
    services = _compose()["services"]
    for name in ("api", "worker"):
        env = "\n".join(services[name]["environment"])
        assert "DATABASE_URL=postgresql+asyncpg://sauri@postgres:5432/sauri" in env
        assert "DATABASE_PASSWORD_FILE=/run/secrets/database_password" in env
        assert "QUEUE_BROKER_PASSWORD_FILE=/run/secrets/queue_password" in env
        assert "OBJECT_STORE_SECRET_KEY_FILE=/run/secrets/object_store_secret_key" in env
        mounts = "\n".join(services[name]["volumes"])
        for secret in ("database_password", "queue_password", "object_store_access_key", "object_store_secret_key"):
            assert f"/run/secrets/{secret}:ro" in mounts
    assert "JWT_SECRET_FILE=/run/secrets/jwt_secret" in services["api"]["environment"]
    assert "POSTGRES_PASSWORD_FILE=/run/secrets/database_password" in services["postgres"]["environment"]
    assert "RUSTFS_SECRET_KEY_FILE=/run/secrets/object_store_secret_key" in services["minio"]["environment"]
    assert services["rabbitmq"]["hostname"] == "sauri-rabbitmq"
    assert "rabbitmq-data:/var/lib/rabbitmq" in services["rabbitmq"]["volumes"]
