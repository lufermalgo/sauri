#!/usr/bin/env bash
set -Eeuo pipefail

python3 - "${HOME:?HOME must be set}/.config/sauri" <<'PY'
import os
import secrets
import stat
import sys
from pathlib import Path

config_dir = Path(sys.argv[1])
config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
os.chmod(config_dir, 0o700)

credentials = {
    "engine_token": secrets.token_urlsafe(32),
    "recording_capability_key": secrets.token_hex(32),
    "queue_signing_key": secrets.token_hex(32),
    # Login password for the single administrator account (43 URL-safe characters).
    "admin_password": secrets.token_urlsafe(32),
    # Service credentials for the local stack (hex: safe inside connection URLs).
    "database_password": secrets.token_hex(32),
    "queue_password": secrets.token_hex(32),
    "object_store_access_key": f"sauri-{secrets.token_hex(8)}",
    "object_store_secret_key": secrets.token_hex(32),
    "jwt_secret": secrets.token_hex(32),
}
for name, value in credentials.items():
    path = config_dir / name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError(f"Credential path is not a regular file: {path}")
        if info.st_size == 0:
            existing_flags = os.O_WRONLY | os.O_TRUNC
            if hasattr(os, "O_NOFOLLOW"):
                existing_flags |= os.O_NOFOLLOW
            fd = os.open(path, existing_flags)
            try:
                os.write(fd, f"{value}\n".encode("ascii"))
            finally:
                os.close(fd)
        os.chmod(path, 0o600, follow_symlinks=False)
    else:
        try:
            os.write(fd, f"{value}\n".encode("ascii"))
        finally:
            os.close(fd)

print("Local service credentials and the admin password file are present with private file permissions.")
PY
