"""Bootstrap is idempotent and creates real, unloginable ownership with starter templates."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.auth.local import LocalConfigurationError, local_cookie_header, local_mode, local_token
from app.auth.passwords import verify_password
from app.infra.database import create_engine, create_session_factory
from app.infra.models import SummaryTemplate, TemplateCategory, User


def test_bootstrap_cli_reuses_user_and_templates(local_app: FastAPI) -> None:
    ids = []
    for name in ("Local Tester", "Another Name"):
        result = subprocess.run(
            [sys.executable, "-m", "app.local.bootstrap", "--name", name],
            capture_output=True,
            text=True,
            check=True,
        )
        ids.append(result.stdout.strip())
        assert result.stderr == ""
    assert ids == [os.environ["SAURI_LOCAL_USER_ID"]] * 2


async def test_real_owner_default_and_unusable_password(local_app: FastAPI) -> None:
    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session:
            user = (await session.execute(select(User))).scalar_one()
            assert user.name == "Local Tester"
            assert user.is_sales is True
            assert user.default_summary_template_id is not None
            template = await session.get(SummaryTemplate, user.default_summary_template_id)
            assert template is not None and template.owner_user_id == user.id
            assert await session.scalar(select(func.count()).select_from(TemplateCategory)) == 1
            for password in ("", "!local-account", "local@sauri.local", "synthetic-password"):
                assert not verify_password(password, user.password_hash)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("value", ["", "ab" * 31, "z" * 64, "ab" * 33, "non-ascii-ñ"])
def test_token_file_rejects_invalid_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    path = tmp_path / "credential"
    path.write_text(value)
    monkeypatch.setenv("SAURI_LOCAL_TOKEN_FILE", str(path))
    with pytest.raises(LocalConfigurationError, match="^local_token_unavailable$"):
        local_token()


def test_missing_token_never_falls_back_to_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAURI_LOCAL_TOKEN_FILE", raising=False)
    monkeypatch.setenv("JWT_SECRET", "synthetic" * 8)
    with pytest.raises(LocalConfigurationError, match="local_token_unavailable"):
        local_cookie_header()


def test_password_mode_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAURI_AUTH_MODE", raising=False)
    assert not local_mode()
    monkeypatch.setenv("SAURI_AUTH_MODE", "typo")
    with pytest.raises(LocalConfigurationError, match="invalid_auth_mode"):
        local_mode()
