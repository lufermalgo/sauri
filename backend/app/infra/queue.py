"""Abstracción cloud-agnóstica de cola de trabajos / mensajería.

Define la interfaz `ColaDeTrabajos` con semántica de entrega al-menos-una-vez,
reintentos y dead-letter. La implementación concreta se selecciona por configuración
(variable de entorno QUEUE_BROKER_URL) sin modificar la lógica de negocio.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any


class ColaDeTrabajos(ABC):
    """Interfaz abstracta de cola de trabajos con entrega al-menos-una-vez."""

    @abstractmethod
    async def publicar(self, tema: str, mensaje: dict[str, Any]) -> None:
        """Publica un mensaje/trabajo en el tema (queue) indicado."""
        ...

    @abstractmethod
    async def suscribir(
        self,
        tema: str,
        manejador: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Suscribe un manejador para consumir mensajes de un tema.

        El manejador recibe el mensaje deserializado. La implementación
        hace ack tras procesamiento exitoso del manejador; en caso de
        excepción, hace nack sin requeue (dead-letter si configurado).
        """
        ...

    @abstractmethod
    async def conectar(self) -> None:
        """Establece la conexión con el broker."""
        ...

    @abstractmethod
    async def desconectar(self) -> None:
        """Cierra la conexión con el broker."""
        ...


def crear_cola_de_trabajos() -> ColaDeTrabajos:
    """Factory que crea la implementación configurada de ColaDeTrabajos.

    Lee QUEUE_BROKER_URL del entorno para determinar la URL del broker.
    """
    from app.infra.queue_rabbitmq import ColaDeRabbitMQ

    broker_url = os.environ.get("QUEUE_BROKER_URL", "amqp://guest:guest@localhost:5672/")
    return ColaDeRabbitMQ(broker_url=broker_url)
