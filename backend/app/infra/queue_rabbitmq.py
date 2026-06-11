"""Implementación de ColaDeTrabajos usando RabbitMQ vía aio-pika.

Proporciona entrega al-menos-una-vez, mensajes persistentes (delivery_mode=2),
y dead-letter automática cuando un manejador falla (nack sin requeue).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractChannel, AbstractRobustConnection

from app.infra.queue import ColaDeTrabajos

logger = logging.getLogger(__name__)


class ColaDeRabbitMQ(ColaDeTrabajos):
    """Implementación de ColaDeTrabajos con RabbitMQ (aio-pika)."""

    def __init__(self, broker_url: str) -> None:
        self._broker_url = broker_url
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None

    async def conectar(self) -> None:
        """Crea una conexión robusta y un canal con el broker RabbitMQ."""
        self._connection = await aio_pika.connect_robust(self._broker_url)
        self._channel = await self._connection.channel()
        logger.info("Conexión a RabbitMQ establecida: %s", self._broker_url)

    async def desconectar(self) -> None:
        """Cierra canal y conexión con RabbitMQ."""
        if self._channel and not self._channel.is_closed:
            await self._channel.close()
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
        self._channel = None
        self._connection = None
        logger.info("Conexión a RabbitMQ cerrada.")

    async def publicar(self, tema: str, mensaje: dict[str, Any]) -> None:
        """Publica un mensaje JSON persistente en la cola durable `tema`."""
        if self._channel is None:
            raise RuntimeError("No hay conexión activa. Llame a `conectar()` primero.")

        queue = await self._channel.declare_queue(tema, durable=True)
        body = json.dumps(mensaje).encode("utf-8")
        message = Message(
            body=body,
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type="application/json",
        )
        await self._channel.default_exchange.publish(
            message,
            routing_key=queue.name,
        )
        logger.debug("Mensaje publicado en '%s': %s", tema, mensaje)

    async def suscribir(
        self,
        tema: str,
        manejador: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Consume mensajes de la cola `tema`, invoca el manejador y ack/nack.

        - Ack tras procesamiento exitoso del manejador.
        - Nack con requeue=False en caso de excepción (envía a dead-letter
          si la cola tiene DLX configurado).
        """
        if self._channel is None:
            raise RuntimeError("No hay conexión activa. Llame a `conectar()` primero.")

        queue = await self._channel.declare_queue(tema, durable=True)

        async def _on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
            try:
                payload: dict[str, Any] = json.loads(message.body.decode("utf-8"))
                await manejador(payload)
                await message.ack()
                logger.debug("Mensaje procesado y ack'd en '%s'.", tema)
            except Exception:
                logger.exception("Error procesando mensaje en '%s'. Nack sin requeue.", tema)
                await message.nack(requeue=False)

        await queue.consume(_on_message)
        logger.info("Suscrito a la cola '%s'.", tema)
