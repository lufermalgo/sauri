"""Fábrica de Motor_ASR por configuración.

Selecciona el Proveedor_De_Transcripcion activo mediante la variable de
entorno ASR_PROVIDER sin modificar el código del Servicio_De_Reuniones (Req. 5.2).
"""

from __future__ import annotations

import os

from app.transcripcion.motor_asr import MotorASR


def crear_motor_asr() -> MotorASR:
    """Crea la implementación de Motor_ASR configurada por entorno.

    Lee la variable de entorno ASR_PROVIDER (case-insensitive, stripped):
    - "local" o ausente/vacío: proveedor local basado en faster-whisper (Req. 2.2, 2.4).
    - "cloud": proveedor en la nube con canal cifrado (Req. 2.3).

    También lee ASR_LOCAL_URL para el proveedor local (obligatoria, Req. 2.6).

    Raises:
        ValueError: Si ASR_PROVIDER tiene un valor no reconocido (Req. 2.5),
            o si se selecciona el proveedor local y ASR_LOCAL_URL está
            ausente o vacía (Req. 2.6).
    """
    raw = os.environ.get("ASR_PROVIDER", "")
    provider = raw.strip().lower()

    if provider in ("", "local"):
        from app.transcripcion.proveedor_local import ProveedorLocal

        url = os.environ.get("ASR_LOCAL_URL", "")
        if not url or not url.strip():
            raise ValueError(
                "ASR_LOCAL_URL no está definida o está vacía; "
                "es obligatoria para el proveedor local"
            )
        return ProveedorLocal(url=url.strip())
    elif provider == "cloud":
        from app.transcripcion.proveedor_nube import ProveedorNube

        return ProveedorNube()
    else:
        raise ValueError(f"ASR_PROVIDER no válido: '{raw.strip()}'")
