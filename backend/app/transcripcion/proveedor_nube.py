"""Proveedor de transcripción en la nube con canal cifrado (TLS).

Implementa Motor_ASR enviando el audio a un servicio externo ASR
por HTTPS, garantizando cifrado en tránsito (Req. 4.1, 4.2).
"""

from __future__ import annotations

import os

import httpx

from app.transcripcion.motor_asr import (
    CapacidadesASR,
    MotorASR,
    OpcionesTranscripcion,
    ResultadoTranscripcion,
    SegmentoTranscripcion,
)


class ErrorServicioExterno(Exception):
    """Error que indica falla del servicio ASR externo."""

    pass


class ProveedorNube(MotorASR):
    """Proveedor ASR en la nube — canal cifrado TLS (Req. 4.1, 4.2).

    Lee la configuración desde variables de entorno:
    - ASR_CLOUD_API_KEY: clave de autenticación para el servicio externo.
    - ASR_CLOUD_ENDPOINT: URL HTTPS del servicio de transcripción.

    El endpoint DEBE usar HTTPS para garantizar cifrado en tránsito.
    La API key DEBE estar presente y no vacía.
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("ASR_CLOUD_API_KEY", "").strip()
        self._endpoint = os.environ.get("ASR_CLOUD_ENDPOINT", "").strip()

        if not self._api_key:
            raise ValueError(
                "ASR_CLOUD_API_KEY debe estar definida y no vacía "
                "para autenticar con el servicio ASR externo (Req. 4.4)"
            )

        if not self._endpoint.startswith("https://"):
            raise ValueError(
                "ASR_CLOUD_ENDPOINT debe usar HTTPS para garantizar "
                f"cifrado en tránsito; esquema recibido no soportado: "
                f"'{self._endpoint}' (Req. 4.2)"
            )

    def capacidades(self) -> CapacidadesASR:
        """Declara capacidades: soporta turnos, no es local."""
        return CapacidadesASR(soporta_turnos=True, es_local=False)

    async def transcribir(
        self, audio_ref: str, opciones: OpcionesTranscripcion
    ) -> ResultadoTranscripcion:
        """Envía audio al servicio externo por canal cifrado (HTTPS/TLS).

        Transmite con autenticación mediante API key y timeout de 30s.
        Valida cada segmento de la respuesta antes de incluirlo.

        Args:
            audio_ref: Referencia al objeto de audio en el AlmacenDeObjetos.
            opciones: Configuración de transcripción (idioma, etc.).

        Returns:
            ResultadoTranscripcion con los segmentos transcritos validados.

        Raises:
            ErrorServicioExterno: Si el servicio no responde en 30s,
                responde con error, o no devuelve segmentos válidos.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "audio_ref": audio_ref,
                        "language": opciones.idioma_prioritario,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            raise ErrorServicioExterno(
                "El servicio ASR externo no respondió dentro del "
                "timeout de 30 segundos"
            )
        except httpx.HTTPStatusError as exc:
            raise ErrorServicioExterno(
                f"El servicio ASR externo respondió con error: "
                f"HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.ConnectError, httpx.RequestError) as exc:
            raise ErrorServicioExterno(
                f"No fue posible conectar con el servicio ASR externo: {exc}"
            ) from exc

        segmentos = self._parsear_y_validar_respuesta(data)

        if not segmentos:
            raise ErrorServicioExterno(
                "El servicio ASR externo no devolvió segmentos válidos"
            )

        return ResultadoTranscripcion(
            segmentos=segmentos,
            idioma=opciones.idioma_prioritario,
            soporta_turnos=True,
        )

    def _parsear_y_validar_respuesta(
        self, data: dict
    ) -> list[SegmentoTranscripcion]:
        """Parsea y valida la respuesta JSON del servicio cloud.

        Solo incluye segmentos que cumplan:
        - texto no vacío
        - inicio_ms entero >= 0
        - fin_ms entero >= 0
        - fin_ms >= inicio_ms

        Returns:
            Lista de SegmentoTranscripcion validados (puede ser vacía
            si ningún segmento pasa la validación).
        """
        segmentos_raw = data.get("segments")
        if not isinstance(segmentos_raw, list):
            return []

        segmentos_validos: list[SegmentoTranscripcion] = []
        for seg in segmentos_raw:
            if not isinstance(seg, dict):
                continue

            texto = seg.get("text", "")
            inicio_ms = seg.get("start_ms")
            fin_ms = seg.get("end_ms")

            # Validar texto no vacío
            if not isinstance(texto, str) or not texto.strip():
                continue

            # Validar inicio_ms y fin_ms son enteros >= 0
            if not isinstance(inicio_ms, int) or inicio_ms < 0:
                continue
            if not isinstance(fin_ms, int) or fin_ms < 0:
                continue

            # Validar fin_ms >= inicio_ms
            if fin_ms < inicio_ms:
                continue

            segmentos_validos.append(
                SegmentoTranscripcion(
                    texto=texto,
                    inicio_ms=inicio_ms,
                    fin_ms=fin_ms,
                )
            )

        return segmentos_validos
