"""Interfaz común Motor_De_Diarizacion y tipos de datos para diarización.

Define la abstracción independiente del proveedor concreto (Req. 2.7)
y los tipos de datos compartidos por todas las implementaciones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class OpcionesDiarizacion:
    """Opciones para la diarización de audio.

    Attributes:
        duracion_ms: Duracion_De_Grabacion en milisegundos; permite al motor
            acotar fin_ms de los segmentos (Req. 5.4). None si no se conoce.
    """

    duracion_ms: int | None = None


@dataclass
class SegmentoDeHablante:
    """Unidad temporal producida por el Motor_De_Diarizacion.

    Indica que un hablante (identificado por etiqueta_cruda) estuvo activo
    en el intervalo [inicio_ms, fin_ms] (Req. 5.2, 5.3).
    """

    etiqueta_cruda: str
    inicio_ms: int
    fin_ms: int


@dataclass
class ResultadoDiarizacion:
    """Resultado producido por un Motor_De_Diarizacion.

    La lista de segmentos se ordena ascendente por inicio_ms en __post_init__
    (Req. 5.1). num_hablantes refleja la cantidad de etiquetas crudas distintas
    (Req. 5.5).
    """

    segmentos: list[SegmentoDeHablante] = field(default_factory=list)
    num_hablantes: int = 0

    def __post_init__(self) -> None:
        """Ordena segmentos por inicio_ms ascendente (Property 6)."""
        self.segmentos = sorted(self.segmentos, key=lambda s: s.inicio_ms)


@dataclass
class CapacidadesDiarizacion:
    """Capacidades declaradas por un proveedor de diarización (Req. 8.4)."""

    es_local: bool
    nombre_proveedor: str


class MotorDiarizacion(ABC):
    """Interfaz común de Motor_De_Diarizacion.

    El Worker_De_Diarizacion interactúa con el Motor_De_Diarizacion únicamente
    a través de esta interfaz, independiente del proveedor concreto (Req. 2.7).
    """

    @abstractmethod
    async def diarizar(
        self, audio_ref: str, opciones: OpcionesDiarizacion
    ) -> ResultadoDiarizacion:
        """Diariza el audio referenciado con las opciones dadas.

        Args:
            audio_ref: Referencia a la Grabacion_De_Audio en el AlmacenDeObjetos.
            opciones: Configuración de diarización (duración, etc.).

        Returns:
            ResultadoDiarizacion con segmentos ordenados y num_hablantes.
        """
        ...

    @abstractmethod
    def capacidades(self) -> CapacidadesDiarizacion:
        """Declara las capacidades del proveedor.

        Returns:
            CapacidadesDiarizacion indicando si es local y nombre del proveedor.
        """
        ...
