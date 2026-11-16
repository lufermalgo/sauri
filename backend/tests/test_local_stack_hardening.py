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


BACKEND_DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def test_auth_bypass_is_off_by_default_and_app_env_is_production() -> None:
    env = "\n".join(_compose()["services"]["api"]["environment"])
    assert "AUTH_DISABLED=${AUTH_DISABLED:-false}" in env
    assert "APP_ENV=${APP_ENV:-production}" in env
    assert "ENABLE_API_DOCS=${ENABLE_API_DOCS:-false}" in env


def test_cors_origins_are_configured_without_wildcard() -> None:
    env = "\n".join(_compose()["services"]["api"]["environment"])
    assert "CORS_ALLOWED_ORIGINS=" in env and "EXTENSION_ORIGINS=" in env
    assert "*" not in env.split("CORS_ALLOWED_ORIGINS=")[1].splitlines()[0]


def test_every_third_party_image_is_pinned_by_digest() -> None:
    for name, service in _compose()["services"].items():
        if "image" in service:
            assert DIGEST.search(service["image"]), f"{name} image is not pinned by digest: {service['image']}"


def test_application_containers_drop_privileges() -> None:
    services = _compose()["services"]
    for name in ("api", "worker", "portal"):
        assert services[name]["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in services[name]["security_opt"], name
    assert services["worker"]["read_only"] is True
    assert services["portal"]["read_only"] is True
    assert "healthcheck" in services["api"]


def test_backend_image_is_pinned_locked_and_non_root() -> None:
    text = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^ARG PYTHON_IMAGE=python:3\.11-slim@sha256:[0-9a-f]{64}$", text, re.MULTILINE)
    assert "uv sync --frozen --no-dev" in text
    assert "pip install" not in text
    users = re.findall(r"^USER (.+)$", text, re.MULTILINE)
    assert users and users[-1] == "sauri"
    assert "--uid 10001" in text
