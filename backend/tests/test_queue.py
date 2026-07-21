"""Tests para la Cola de Trabajos (queue_rabbitmq.py).

# Feature: transcripcion-asr
Tasks: 10.3, 10.4
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.infra.queue_rabbitmq import _leer_max_retries, _contar_reintentos


# ---------------------------------------------------------------------------
# Prueba por ejemplo — validación del rango de ASR_MAX_RETRIES (Task 10.3)
# Validates: Requirements 9.2
# ---------------------------------------------------------------------------


class TestMaxRetries:
    """Pruebas de validación del rango ASR_MAX_RETRIES."""

    def test_default_cuando_ausente(self):
        """ASR_MAX_RETRIES ausente → default 3."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASR_MAX_RETRIES", None)
            assert _leer_max_retries() == 3

    def test_default_cuando_vacio(self):
        """ASR_MAX_RETRIES vacío → default 3."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": ""}, clear=False):
            assert _leer_max_retries() == 3

    def test_valor_valido_0(self):
        """ASR_MAX_RETRIES=0 → 0 (sin reintentos)."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "0"}, clear=False):
            assert _leer_max_retries() == 0

    def test_valor_valido_10(self):
        """ASR_MAX_RETRIES=10 → 10 (máximo permitido)."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "10"}, clear=False):
            assert _leer_max_retries() == 10

    def test_valor_valido_5(self):
        """ASR_MAX_RETRIES=5 → 5."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "5"}, clear=False):
            assert _leer_max_retries() == 5

    def test_fuera_de_rango_negativo(self):
        """ASR_MAX_RETRIES=-1 → default 3 (fuera de rango)."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "-1"}, clear=False):
            assert _leer_max_retries() == 3

    def test_fuera_de_rango_mayor_10(self):
        """ASR_MAX_RETRIES=11 → default 3 (fuera de rango)."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "11"}, clear=False):
            assert _leer_max_retries() == 3

    def test_fuera_de_rango_100(self):
        """ASR_MAX_RETRIES=100 → default 3."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "100"}, clear=False):
            assert _leer_max_retries() == 3

    def test_no_entero(self):
        """ASR_MAX_RETRIES='abc' → default 3."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "abc"}, clear=False):
            assert _leer_max_retries() == 3


# ---------------------------------------------------------------------------
# Pruebas de integración de la cola (Task 10.4)
# Validates: Requirements 1.5, 1.6, 1.7, 9.2, 9.3, 9.4
# ---------------------------------------------------------------------------


class TestContarReintentos:
    """Tests unitarios para _contar_reintentos (sin necesidad de RabbitMQ real).

    El conteo se rastrea con un header propio (x-sauri-reintentos), no con el
    x-death de RabbitMQ: x-death solo lo puebla RabbitMQ cuando el mensaje pasa
    por un dead-letter-exchange real, y en este entorno (sin QUEUE_DLX_EXCHANGE
    configurado) un nack(requeue=True) directo nunca lo toca — lo que causaba
    un loop infinito de reintentos, ya que _contar_reintentos siempre veía 0.
    """

    def test_sin_header_retorna_0(self):
        """Mensaje sin x-sauri-reintentos → 0 reintentos."""
        from unittest.mock import MagicMock

        msg = MagicMock()
        msg.headers = {}
        assert _contar_reintentos(msg) == 0

    def test_sin_headers_retorna_0(self):
        """Mensaje sin headers → 0 reintentos."""
        from unittest.mock import MagicMock

        msg = MagicMock()
        msg.headers = None
        assert _contar_reintentos(msg) == 0

    def test_header_con_valor_1(self):
        """x-sauri-reintentos=1 → 1 reintento."""
        from unittest.mock import MagicMock

        msg = MagicMock()
        msg.headers = {"x-sauri-reintentos": 1}
        assert _contar_reintentos(msg) == 1

    def test_header_con_valor_3(self):
        """x-sauri-reintentos=3 → 3 reintentos."""
        from unittest.mock import MagicMock

        msg = MagicMock()
        msg.headers = {"x-sauri-reintentos": 3}
        assert _contar_reintentos(msg) == 3

    def test_header_no_entero_retorna_0(self):
        """x-sauri-reintentos con valor no entero → 0 reintentos."""
        from unittest.mock import MagicMock

        msg = MagicMock()
        msg.headers = {"x-sauri-reintentos": "no-es-un-entero"}
        assert _contar_reintentos(msg) == 0


class TestColaDeRabbitMQBehavior:
    """Tests de comportamiento del consumidor (mock de aio-pika).

    Verifica la lógica de ack/nack/requeue sin conexión real a RabbitMQ.
    """

    @pytest.mark.asyncio
    async def test_ack_tras_exito(self):
        """Req 1.5: Procesamiento exitoso → ack."""
        from unittest.mock import AsyncMock
        from app.infra.queue_rabbitmq import ColaDeRabbitMQ
        import json

        cola = ColaDeRabbitMQ("amqp://guest:guest@localhost/")
        cola._max_retries = 3
        cola._dlx_exchange = None

        handler_called = False

        async def mock_handler(msg):
            nonlocal handler_called
            handler_called = True

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"reunion_id": "abc", "audio_ref": "x"}).encode()
        mock_message.headers = {}
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()

        cola._channel = AsyncMock()
        mock_queue = AsyncMock()
        cola._channel.declare_queue.return_value = mock_queue

        captured_callback = None

        async def capture_consume(callback):
            nonlocal captured_callback
            captured_callback = callback

        mock_queue.consume = capture_consume

        await cola.suscribir("transcribir", mock_handler)
        assert captured_callback is not None

        await captured_callback(mock_message)

        assert handler_called
        mock_message.ack.assert_called_once()
        mock_message.nack.assert_not_called()

    @pytest.mark.asyncio
    async def test_nack_sin_requeue_ante_excepcion_reintentos_agotados(self):
        """Req 1.6: Excepción con reintentos agotados → nack(requeue=False)."""
        from unittest.mock import AsyncMock
        from app.infra.queue_rabbitmq import ColaDeRabbitMQ
        import json

        cola = ColaDeRabbitMQ("amqp://guest:guest@localhost/")
        cola._max_retries = 3
        cola._dlx_exchange = "dlx-exchange"

        async def failing_handler(msg):
            raise RuntimeError("boom")

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"reunion_id": "abc"}).encode()
        mock_message.headers = {"x-sauri-reintentos": 3}
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()

        cola._channel = AsyncMock()
        mock_queue = AsyncMock()
        cola._channel.declare_queue.return_value = mock_queue

        captured_callback = None

        async def capture_consume(callback):
            nonlocal captured_callback
            captured_callback = callback

        mock_queue.consume = capture_consume

        await cola.suscribir("transcribir", failing_handler)
        await captured_callback(mock_message)

        mock_message.nack.assert_called_once_with(requeue=False)
        mock_message.ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_republica_con_reintentos_incrementado_ante_excepcion_reintentos_disponibles(self):
        """Req 9.2: Excepción con reintentos disponibles → republica con contador +1 y ack del original.

        No usa nack(requeue=True): sin DLX configurado eso reencola el mismo
        mensaje sin dejar rastro en x-death, causando un loop infinito de
        reintentos idénticos (bug real observado en vivo). En su lugar, se
        publica una copia con x-sauri-reintentos incrementado y se hace ack
        del mensaje original.
        """
        from unittest.mock import AsyncMock
        from app.infra.queue_rabbitmq import ColaDeRabbitMQ
        import json

        cola = ColaDeRabbitMQ("amqp://guest:guest@localhost/")
        cola._max_retries = 3
        cola._dlx_exchange = None

        async def failing_handler(msg):
            raise RuntimeError("boom")

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"reunion_id": "abc"}).encode()
        mock_message.headers = {"x-sauri-reintentos": 1}
        mock_message.content_type = "application/json"
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()

        cola._channel = AsyncMock()
        mock_queue = AsyncMock()
        cola._channel.declare_queue.return_value = mock_queue
        cola._channel.default_exchange.publish = AsyncMock()

        captured_callback = None

        async def capture_consume(callback):
            nonlocal captured_callback
            captured_callback = callback

        mock_queue.consume = capture_consume

        await cola.suscribir("transcribir", failing_handler)
        await captured_callback(mock_message)

        mock_message.nack.assert_not_called()
        mock_message.ack.assert_called_once()
        cola._channel.default_exchange.publish.assert_called_once()
        published_message, kwargs = cola._channel.default_exchange.publish.call_args
        assert kwargs["routing_key"] == "transcribir"
        assert published_message[0].headers["x-sauri-reintentos"] == 2

    @pytest.mark.asyncio
    async def test_dlx_configurado_en_queue_arguments(self):
        """Req 1.7, 9.3: DLX configurado → se pasa x-dead-letter-exchange."""
        from unittest.mock import AsyncMock
        from app.infra.queue_rabbitmq import ColaDeRabbitMQ

        cola = ColaDeRabbitMQ("amqp://guest:guest@localhost/")
        cola._max_retries = 3
        cola._dlx_exchange = "my-dlx"

        async def noop_handler(msg):
            pass

        cola._channel = AsyncMock()
        mock_queue = AsyncMock()
        cola._channel.declare_queue.return_value = mock_queue
        mock_queue.consume = AsyncMock()

        await cola.suscribir("transcribir", noop_handler)

        # Check declare_queue was called with DLX argument
        call_kwargs = cola._channel.declare_queue.call_args[1]
        arguments = call_kwargs.get("arguments")
        assert arguments is not None
        assert arguments.get("x-dead-letter-exchange") == "my-dlx"

    @pytest.mark.asyncio
    async def test_descarte_sin_dlx(self):
        """Req 9.4: Sin DLX + reintentos agotados → descarte (nack requeue=False)."""
        from unittest.mock import AsyncMock, patch
        from app.infra.queue_rabbitmq import ColaDeRabbitMQ
        import json

        cola = ColaDeRabbitMQ("amqp://guest:guest@localhost/")
        cola._dlx_exchange = None

        async def failing_handler(msg):
            raise RuntimeError("boom")

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"reunion_id": "abc"}).encode()
        mock_message.headers = {"x-sauri-reintentos": 2}
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()

        cola._channel = AsyncMock()
        mock_queue = AsyncMock()
        cola._channel.declare_queue.return_value = mock_queue

        captured_callback = None

        async def capture_consume(callback):
            nonlocal captured_callback
            captured_callback = callback

        mock_queue.consume = capture_consume

        with patch("app.infra.queue_rabbitmq._leer_max_retries", return_value=2):
            await cola.suscribir("transcribir", failing_handler)
        await captured_callback(mock_message)

        mock_message.nack.assert_called_once_with(requeue=False)
