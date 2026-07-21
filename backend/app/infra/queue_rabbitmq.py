"""Implementación de ColaDeTrabajos usando RabbitMQ vía aio-pika.

Proporciona entrega al-menos-una-vez, mensajes persistentes (delivery_mode=2),
reintentos acotados por ASR_MAX_RETRIES con conteo vía un header propio
(x-sauri-reintentos), y dead-letter automática cuando se agotan los
reintentos (nack sin requeue).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractChannel, AbstractRobustConnection

from app.infra.queue import ColaDeTrabajos

logger = logging.getLogger(__name__)

_MAX_RETRIES_MIN = 0
_MAX_RETRIES_MAX = 10
_MAX_RETRIES_DEFAULT = 3

# Mapa de tema → variable de entorno para reintentos
_TEMA_A_ENV_RETRIES: dict[str, str] = {
    "transcribir": "ASR_MAX_RETRIES",
    "diarizar": "DIARIZATION_MAX_RETRIES",
}


def _leer_max_retries(tema: str = "transcribir") -> int:
    """Lee la variable de reintentos del entorno para el tema dado.

    Mapa de temas:
    - "transcribir" → ASR_MAX_RETRIES
    - "diarizar" → DIARIZATION_MAX_RETRIES

    Rango válido: 0–10. Default: 3.
    """
    env_var = _TEMA_A_ENV_RETRIES.get(tema, "ASR_MAX_RETRIES")
    raw = os.environ.get(env_var, "")
    if not raw.strip():
        return _MAX_RETRIES_DEFAULT
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning(
            "%s='%s' no es un entero válido. Usando default %d.",
            env_var,
            raw,
            _MAX_RETRIES_DEFAULT,
        )
        return _MAX_RETRIES_DEFAULT
    if value < _MAX_RETRIES_MIN or value > _MAX_RETRIES_MAX:
        logger.warning(
            "%s=%d fuera de rango [%d, %d]. Usando default %d.",
            env_var,
            value,
            _MAX_RETRIES_MIN,
            _MAX_RETRIES_MAX,
            _MAX_RETRIES_DEFAULT,
        )
        return _MAX_RETRIES_DEFAULT
    return value


_HEADER_REINTENTOS = "x-sauri-reintentos"


def _contar_reintentos(message: aio_pika.abc.AbstractIncomingMessage) -> int:
    """Cuenta los reintentos acumulados de un mensaje usando un header propio.

    No se puede usar el x-death de RabbitMQ para esto: ese header solo lo puebla
    RabbitMQ cuando un mensaje pasa por un dead-letter-exchange real. Sin DLX
    configurado (QUEUE_DLX_EXCHANGE vacío, el caso por defecto), un
    nack(requeue=True) directo reencola el mismo mensaje sin dejar rastro alguno,
    por lo que _contar_reintentos siempre devolvía 0 y el mensaje se reintentaba
    para siempre. Por eso el conteo se rastrea explícitamente en el header
    x-sauri-reintentos, que este módulo incrementa al republicar cada reintento.
    """
    headers = message.headers or {}
    count = headers.get(_HEADER_REINTENTOS, 0)
    return count if isinstance(count, int) else 0


def _leer_dlx_exchange() -> str | None:
    """Lee QUEUE_DLX_EXCHANGE del entorno. Retorna None si no está configurado o está vacío."""
    raw = os.environ.get("QUEUE_DLX_EXCHANGE", "")
    return raw.strip() if raw.strip() else None


class ColaDeRabbitMQ(ColaDeTrabajos):
    """Implementación de ColaDeTrabajos con RabbitMQ (aio-pika)."""

    def __init__(self, broker_url: str) -> None:
        self._broker_url = broker_url
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._dlx_exchange: str | None = _leer_dlx_exchange()

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
        - Si reintentos acumulados < max_retries para el tema: se republica una
          copia del mensaje con x-sauri-reintentos incrementado y se hace ack
          del original (ver _contar_reintentos para el porqué de no usar
          nack(requeue=True) aquí).
        - Nack con requeue=False al alcanzar max_retries (envía a dead-letter
          si la cola tiene DLX configurado; de lo contrario se descarta).
        """
        if self._channel is None:
            raise RuntimeError("No hay conexión activa. Llame a `conectar()` primero.")
        channel = self._channel

        max_retries = _leer_max_retries(tema)

        queue_arguments: dict[str, Any] = {}
        if self._dlx_exchange:
            queue_arguments["x-dead-letter-exchange"] = self._dlx_exchange

        queue = await channel.declare_queue(
            tema, durable=True, arguments=queue_arguments or None
        )

        async def _on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
            try:
                payload: dict[str, Any] = json.loads(message.body.decode("utf-8"))
                await manejador(payload)
                await message.ack()
                logger.debug("Mensaje procesado y ack'd en '%s'.", tema)
            except Exception:
                reintentos = _contar_reintentos(message)
                if reintentos < max_retries:
                    logger.warning(
                        "Error procesando mensaje en '%s'. Reintento %d/%d. Requeue.",
                        tema,
                        reintentos + 1,
                        max_retries,
                    )
                    retry_message = Message(
                        body=message.body,
                        delivery_mode=DeliveryMode.PERSISTENT,
                        content_type=message.content_type,
                        headers={**(message.headers or {}), _HEADER_REINTENTOS: reintentos + 1},
                    )
                    await channel.default_exchange.publish(retry_message, routing_key=tema)
                    await message.ack()
                else:
                    if self._dlx_exchange:
                        logger.error(
                            "Error procesando mensaje en '%s'. Reintentos agotados (%d/%d). "
                            "Derivando a dead-letter (DLX='%s').",
                            tema,
                            reintentos,
                            max_retries,
                            self._dlx_exchange,
                        )
                    else:
                        logger.error(
                            "Error procesando mensaje en '%s'. Reintentos agotados (%d/%d). "
                            "Mensaje descartado (sin DLX configurado).",
                            tema,
                            reintentos,
                            max_retries,
                        )
                    await message.nack(requeue=False)

        await queue.consume(_on_message)
        logger.info("Suscrito a la cola '%s'. Max reintentos: %d.", tema, max_retries)
