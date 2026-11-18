"""Portal CSP, with the same inline-script selection as inline-script-hash.mjs."""

import base64
import hashlib
import re
from pathlib import Path

_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>", re.ASCII)


def inline_script_hash(index: Path) -> str:
    """Hash the exact UTF-8 script bytes; do not normalize CRLF as read_text would."""
    html = index.read_bytes().decode("utf-8", errors="replace")
    scripts = _INLINE_SCRIPT.findall(html)
    if len(scripts) != 1:
        raise ValueError(f"expected exactly one inline script in {index}, found {len(scripts)}")
    digest = hashlib.sha256(scripts[0].encode("utf-8")).digest()
    return f"sha256-{base64.b64encode(digest).decode('ascii')}"


def content_security_policy(index: Path) -> str:
    """Keep nginx hardening, replacing direct S3 reads with same-origin media."""
    # UploadView reads file metadata through a blob video before uploading; media still needs blob:.
    # Images use same-origin thumbnails or data: only, so neither S3 nor blob: is needed there.
    return (
        f"default-src 'self'; script-src 'self' '{inline_script_hash(index)}'; "
        "style-src 'self'; img-src 'self' data:; media-src 'self' blob:; font-src 'self'; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
