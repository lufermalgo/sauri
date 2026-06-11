"""Proveedor local de transcripción basado en faster-whisper.

Procesa la Grabacion_De_Audio sin enviarla a un servicio externo (Req. 5.3).
Se comunica con el contenedor asr-engine propio vía HTTP interno (sin TLS,
servicio-a-servicio dentro de Docker).
"""

from __future__ import annotations

import httpx

from app.transcripcion.motor_asr import (
    CapacidadesASR,
    MotorASR,
    OpcionesTranscripcion,
    ResultadoTranscripcion,
    SegmentoTranscripcion,
)


class ProveedorLocal(MotorASR):
    """Motor_ASR local basado en faster-whisper (contenedor asr-engine).

    Envía la referencia de audio al servicio local para procesamiento
    sin que los datos salgan de la infraestructura propia de sauri.
    """

    def __init__(self, url: str) -> None:
        """Inicializa el proveedor local.

        Args:
            url: URL base del servicio asr-engine local
                 (e.g. http://localhost:8001 o http://asr-engine:8001).
        """
        self._url = url.rstrip("/")

    def capacidades(self) -> CapacidadesASR:
        """Declara capacidades del proveedor local faster-whisper."""
        return CapacidadesASR(soporta_turnos=True, es_local=True)

    async def transcribir(
        self, audio_ref: str, opciones: OpcionesTranscripcion
    ) -> ResultadoTranscripcion:
        """Transcribe el audio invocando el servicio asr-engine local.

        Envía un POST a {url}/transcribe con la referencia de audio y el
        idioma prioritario. El servicio local procesa sin enviar datos a
        ningún servicio externo (Req. 5.3).

        Args:
            audio_ref: Referencia a la Grabacion_De_Audio en el AlmacenDeObjetos.
            opciones: Configuración de transcripción (idioma prioritario).

        Returns:
            ResultadoTranscripcion con segmentos, idioma y soporte de turnos.

        Raises:
            httpx.HTTPStatusError: Si el servicio responde con error HTTP.
        """
        payload = {
            "audio_ref": audio_ref,
            "language": opciones.idioma_prioritario,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._url}/transcribe",
                json=payload,
                timeout=300.0,  # Transcripción puede tardar varios minutos
            )
            response.raise_for_status()

        data = response.json()

        segmentos = [
            SegmentoTranscripcion(
                texto=seg["text"],
                inicio_ms=seg["start_ms"],
                fin_ms=seg["end_ms"],
            )
            for seg in data.get("segments", [])
        ]

        return ResultadoTranscripcion(
            segmentos=segmentos,
            idioma=data.get("language", opciones.idioma_prioritario),
            soporta_turnos=True,
        )
