"""Interfaz común Motor_ASR y tipos de datos para transcripción.

Define la abstracción independiente del proveedor concreto (Req. 5.1)
y los tipos de datos compartidos por todas las implementaciones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class OpcionesTranscripcion:
    """Opciones para la transcripción de audio."""

    idioma_prioritario: str = "es-CO"


@dataclass
class SegmentoTranscripcion:
    """Segmento de texto con marcas de tiempo relativas al inicio del audio."""

    texto: str
    inicio_ms: int
    fin_ms: int


@dataclass
class ResultadoTranscripcion:
    """Resultado producido por un Motor_ASR."""

    segmentos: list[SegmentoTranscripcion] = field(default_factory=list)
    idioma: str = "es-CO"
    soporta_turnos: bool = False


@dataclass
class CapacidadesASR:
    """Capacidades declaradas por un proveedor de transcripción."""

    soporta_turnos: bool
    es_local: bool


class MotorASR(ABC):
    """Interfaz común de Motor_ASR (Automatic Speech Recognition).

    El Servicio_De_Reuniones interactúa con el Motor_ASR únicamente a
    través de esta interfaz, independiente del proveedor concreto (Req. 5.1).
    """

    @abstractmethod
    async def transcribir(
        self, audio_ref: str, opciones: OpcionesTranscripcion
    ) -> ResultadoTranscripcion:
        """Transcribe el audio referenciado con las opciones dadas.

        Args:
            audio_ref: Referencia a la Grabacion_De_Audio en el AlmacenDeObjetos.
            opciones: Configuración de transcripción (idioma, etc.).

        Returns:
            ResultadoTranscripcion con segmentos, idioma y flag de turnos.
        """
        ...

    @abstractmethod
    def capacidades(self) -> CapacidadesASR:
        """Declara las capacidades del proveedor.

        Returns:
            CapacidadesASR indicando soporte de turnos y si es local.
        """
        ...
