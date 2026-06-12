"""Proveedor local de diarización — comunicación con diar-engine.

Procesa la Grabacion_De_Audio sin enviarla fuera de la infraestructura de sauri
(Req. 3.2). Se comunica con el contenedor diar-engine propio vía HTTP interno
(servicio-a-servicio dentro de Docker).

Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import httpx

from app.diarizacion.motor_diarizacion import (
    CapacidadesDiarizacion,
    MotorDiarizacion,
    OpcionesDiarizacion,
    ResultadoDiarizacion,
    SegmentoDeHablante,
)


class ProveedorLocal(MotorDiarizacion):
    """Motor_De_Diarizacion local basado en diar-engine (contenedor propio).

    Envía la referencia de audio al servicio local para procesamiento
    sin que los datos salgan de la infraestructura propia de sauri (Req. 3.2).
    """

    def __init__(self, url: str) -> None:
        """Inicializa el proveedor local.

        Args:
            url: URL base del servicio diar-engine local
                 (e.g. http://localhost:8002 o http://diar-engine:8002).
        """
        self._url = url.rstrip("/")

    def capacidades(self) -> CapacidadesDiarizacion:
        """Declara capacidades del proveedor local diar-engine."""
        return CapacidadesDiarizacion(es_local=True, nombre_proveedor="diar-engine-local")

    async def diarizar(
        self, audio_ref: str, opciones: OpcionesDiarizacion
    ) -> ResultadoDiarizacion:
        """Diariza el audio invocando el servicio diar-engine local.

        Envía un POST a {url}/diarize con la referencia de audio.
        El servicio local procesa sin enviar datos a ningún servicio externo
        (Req. 3.2).

        Args:
            audio_ref: Referencia a la Grabacion_De_Audio en el AlmacenDeObjetos.
            opciones: Configuración de diarización.

        Returns:
            ResultadoDiarizacion con segmentos y num_hablantes.

        Raises:
            httpx.HTTPStatusError: Si el servicio responde con error HTTP (Req. 3.5).
            httpx.TimeoutException: Si el servicio no responde en 600s (Req. 3.6).
            httpx.ConnectError: Si el servicio es inalcanzable (Req. 3.6).
            ValueError: Si la respuesta no contiene la clave 'segments' (Req. 3.7).
        """
        payload = {"audio_ref": audio_ref}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._url}/diarize",
                json=payload,
                timeout=600.0,  # Diarización puede tardar varios minutos (Req. 3.1)
            )
            response.raise_for_status()

        data = response.json()

        # Req. 3.7: distinguir ausencia de clave "segments" (error) de lista vacía (válido)
        if "segments" not in data:
            raise ValueError(
                "Respuesta del servicio de diarización local sin la clave 'segments': "
                "estructura inválida"
            )

        segmentos = [
            SegmentoDeHablante(
                etiqueta_cruda=seg["speaker"],
                inicio_ms=seg["start_ms"],
                fin_ms=seg["end_ms"],
            )
            for seg in data["segments"]
        ]

        return ResultadoDiarizacion(
            segmentos=segmentos,
            num_hablantes=len({seg["speaker"] for seg in data["segments"]}),
        )
