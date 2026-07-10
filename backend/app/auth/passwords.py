"""Hash y verificación de contraseñas para el almacén mínimo de Usuario.

Usa PBKDF2-HMAC-SHA256 (stdlib `hashlib`) para no introducir una nueva
dependencia. No es una integración con el IdP de Summan (Req. 13.1, 13.2).
"""

from __future__ import annotations

import hashlib
import hmac
import os

_ITERATIONS = 260_000
_ALGORITMO = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """Genera un hash con sal aleatoria: '<algoritmo>$<iteraciones>$<sal>$<hash>'."""
    sal = os.urandom(16)
    derivado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, _ITERATIONS)
    return f"{_ALGORITMO}${_ITERATIONS}${sal.hex()}${derivado.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica una contraseña contra un hash generado por `hash_password`."""
    try:
        algoritmo, iteraciones_str, sal_hex, hash_hex = password_hash.split("$")
        if algoritmo != _ALGORITMO:
            return False
        iteraciones = int(iteraciones_str)
        sal = bytes.fromhex(sal_hex)
        esperado = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False

    derivado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, iteraciones)
    return hmac.compare_digest(derivado, esperado)
