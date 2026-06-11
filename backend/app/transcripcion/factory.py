"""Fábrica de Motor_ASR por configuración.

Selecciona el Proveedor_De_Transcripcion activo mediante la variable de
entorno ASR_PROVIDER sin modificar el código del Servicio_De_Reuniones (Req. 5.2).
"""

from __future__ import annotations

import os

from app.transcripcion.motor_asr import MotorASR


def crear_motor_asr() -> MotorASR:
    """Crea la implementación de Motor_ASR configurada por entorno.

    Lee la variable de entorno ASR_PROVIDER:
    - "local" (por defecto): proveedor local basado en faster-whisper (Req. 5.3).
    - "cloud": proveedor en la nube con canal cifrado (Req. 5.4).

    También lee ASR_LOCAL_URL para el proveedor local.

    Raises:
        ValueError: Si ASR_PROVIDER tiene un valor no reconocido.
    """
    provider = os.environ.get("ASR_PROVIDER", "local")

    if provider == "local":
        from app.transcripcion.proveedor_local import ProveedorLocal

        url = os.environ.get("ASR_LOCAL_URL", "http://localhost:8001")
        return ProveedorLocal(url=url)
    elif provider == "cloud":
        from app.transcripcion.proveedor_nube import ProveedorNube

        return ProveedorNube()
    else:
        raise ValueError(f"ASR_PROVIDER no válido: {provider}")
