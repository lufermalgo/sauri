"""Fábrica de Motor_De_Diarizacion por configuración.

Selecciona el Proveedor_De_Diarizacion activo mediante la variable de
entorno DIARIZATION_PROVIDER (Req. 2.1).

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

import os

from app.diarizacion.motor_diarizacion import MotorDiarizacion


def crear_motor_diarizacion() -> MotorDiarizacion:
    """Crea la implementación de MotorDiarizacion configurada por entorno.

    Lee la variable de entorno DIARIZATION_PROVIDER (case-insensitive, stripped):
    - "local" o ausente/vacío: proveedor local basado en diar-engine (Req. 2.2, 2.4).
    - "cloud": proveedor en la nube con canal cifrado (Req. 2.3).

    También lee DIARIZATION_LOCAL_URL para el proveedor local (obligatoria, Req. 2.6).

    Raises:
        ValueError: Si DIARIZATION_PROVIDER tiene un valor no reconocido (Req. 2.5),
            o si se selecciona el proveedor local y DIARIZATION_LOCAL_URL está
            ausente o vacía (Req. 2.6).
    """
    raw = os.environ.get("DIARIZATION_PROVIDER", "")
    provider = raw.strip().lower()

    if provider in ("", "local"):
        from app.diarizacion.proveedor_local import ProveedorLocal

        url = os.environ.get("DIARIZATION_LOCAL_URL", "")
        if not url or not url.strip():
            raise ValueError(
                "DIARIZATION_LOCAL_URL no está definida o está vacía; "
                "es obligatoria para el proveedor local de diarización"
            )
        return ProveedorLocal(url=url.strip())
    elif provider == "cloud":
        from app.diarizacion.proveedor_nube import ProveedorNube

        return ProveedorNube()
    else:
        raise ValueError(f"DIARIZATION_PROVIDER no válido: '{raw.strip()}'")
