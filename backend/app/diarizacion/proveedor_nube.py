"""Proveedor de diarización en la nube con canal cifrado (TLS).

Implementa MotorDiarizacion enviando el audio a un servicio externo
por HTTPS, garantizando cifrado en tránsito (Req. 4.1, 4.2).

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
"""

from __future__ import annotations

import os

import httpx

from app.diarizacion.motor_diarizacion import (
    CapacidadesDiarizacion,
    MotorDiarizacion,
    OpcionesDiarizacion,
    ResultadoDiarizacion,
    SegmentoDeHablante,
)


class ErrorServicioExterno(Exception):
    """Error que indica falla del servicio de diarización externo."""

    pass


class ProveedorNube(MotorDiarizacion):
    """Proveedor de diarización en la nube — canal cifrado TLS (Req. 4.1, 4.2).

    Lee la configuración desde variables de entorno:
    - DIARIZATION_CLOUD_API_KEY: clave de autenticación para el servicio externo.
    - DIARIZATION_CLOUD_ENDPOINT: URL HTTPS del servicio de diarización.

    El endpoint DEBE usar HTTPS para garantizar cifrado en tránsito.
    La API key DEBE estar presente y no vacía.
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("DIARIZATION_CLOUD_API_KEY", "").strip()
        self._endpoint = os.environ.get("DIARIZATION_CLOUD_ENDPOINT", "").strip()

        if not self._api_key:
            raise ValueError(
                "DIARIZATION_CLOUD_API_KEY debe estar definida y no vacía "
                "para autenticar con el servicio de diarización externo (Req. 4.4)"
            )

        if not self._endpoint.startswith("https://"):
            raise ValueError(
                "DIARIZATION_CLOUD_ENDPOINT debe usar HTTPS para garantizar "
                f"cifrado en tránsito; esquema recibido no soportado: "
                f"'{self._endpoint}' (Req. 4.2)"
            )

    def capacidades(self) -> CapacidadesDiarizacion:
        """Declara capacidades: no es local, nombre del proveedor cloud."""
        return CapacidadesDiarizacion(es_local=False, nombre_proveedor="diarization-cloud")

    async def diarizar(
        self, audio_ref: str, opciones: OpcionesDiarizacion
    ) -> ResultadoDiarizacion:
        """Envía audio al servicio externo por canal cifrado (HTTPS/TLS).

        Transmite con autenticación mediante API key y timeout de 120s (Req. 4.6).
        Valida cada segmento de la respuesta antes de incluirlo (Req. 4.5).

        Args:
            audio_ref: Referencia al objeto de audio en el AlmacenDeObjetos.
            opciones: Configuración de diarización (duración, etc.).

        Returns:
            ResultadoDiarizacion con los segmentos diarizados validados.

        Raises:
            ErrorServicioExterno: Si el servicio no responde en 120s,
                responde con error, o no devuelve segmentos válidos (Req. 4.6).
        """
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"audio_ref": audio_ref},
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            raise ErrorServicioExterno(
                "El servicio de diarización externo no respondió dentro del "
                "timeout de 120 segundos"
            )
        except httpx.HTTPStatusError as exc:
            raise ErrorServicioExterno(
                f"El servicio de diarización externo respondió con error: "
                f"HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.ConnectError, httpx.RequestError) as exc:
            raise ErrorServicioExterno(
                f"No fue posible conectar con el servicio de diarización externo: {exc}"
            ) from exc

        segmentos = self._parsear_y_validar_respuesta(data, opciones.duracion_ms)

        return ResultadoDiarizacion(
            segmentos=segmentos,
            num_hablantes=len({s.etiqueta_cruda for s in segmentos}),
        )

    def _parsear_y_validar_respuesta(
        self, data: dict, duracion_ms: int | None
    ) -> list[SegmentoDeHablante]:
        """Parsea y valida la respuesta JSON del servicio cloud (Req. 4.5).

        Solo incluye segmentos que cumplan:
        - etiqueta_cruda (speaker) no vacía
        - inicio_ms entero >= 0
        - fin_ms entero >= 0
        - fin_ms >= inicio_ms
        - fin_ms <= duracion_ms (si se conoce la duración)

        Returns:
            Lista de SegmentoDeHablante validados (puede ser vacía).
        """
        segmentos_raw = data.get("segments")
        if not isinstance(segmentos_raw, list):
            return []

        segmentos_validos: list[SegmentoDeHablante] = []
        for seg in segmentos_raw:
            if not isinstance(seg, dict):
                continue

            speaker = seg.get("speaker", "")
            inicio_ms = seg.get("start_ms")
            fin_ms = seg.get("end_ms")

            # Validar etiqueta_cruda no vacía
            if not isinstance(speaker, str) or not speaker.strip():
                continue

            # Validar inicio_ms y fin_ms son enteros >= 0
            if not isinstance(inicio_ms, int) or inicio_ms < 0:
                continue
            if not isinstance(fin_ms, int) or fin_ms < 0:
                continue

            # Validar fin_ms >= inicio_ms
            if fin_ms < inicio_ms:
                continue

            # Validar fin_ms <= duracion_ms si se conoce
            if duracion_ms is not None and fin_ms > duracion_ms:
                continue

            segmentos_validos.append(
                SegmentoDeHablante(
                    etiqueta_cruda=speaker,
                    inicio_ms=inicio_ms,
                    fin_ms=fin_ms,
                )
            )

        return segmentos_validos
