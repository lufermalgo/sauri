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
    """Tests unitarios para _contar_reintentos (sin necesidad de RabbitMQ real)."""

    def test_sin_x_death_retorna_0(self):
        """Mensaje sin x-death → 0 reintentos."""
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

    def test_x_death_con_count_1(self):
        """x-death con count=1 → 1 reintento."""
        from unittest.mock import MagicMock

        msg = MagicMock()
        msg.headers = {"x-death": [{"count": 1, "queue": "transcribir"}]}
        assert _contar_reintentos(msg) == 1

    def test_x_death_con_multiples_entries(self):
        """x-death con múltiples entries → suma de counts."""
        from unittest.mock import MagicMock

        msg = MagicMock()
        msg.headers = {
            "x-death": [
                {"count": 2, "queue": "transcribir"},
                {"count": 1, "queue": "transcribir"},
            ]
        }
        assert _contar_reintentos(msg) == 3

    def test_x_death_lista_vacia(self):
        """x-death vacío → 0 reintentos."""
        from unittest.mock import MagicMock

        msg = MagicMock()
        msg.headers = {"x-death": []}
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
        mock_message.headers = {"x-death": [{"count": 3, "queue": "transcribir"}]}
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
    async def test_nack_con_requeue_ante_excepcion_reintentos_disponibles(self):
        """Req 9.2: Excepción con reintentos disponibles → nack(requeue=True)."""
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
        mock_message.headers = {"x-death": [{"count": 1, "queue": "transcribir"}]}
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

        mock_message.nack.assert_called_once_with(requeue=True)

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
        from unittest.mock import AsyncMock
        from app.infra.queue_rabbitmq import ColaDeRabbitMQ
        import json

        cola = ColaDeRabbitMQ("amqp://guest:guest@localhost/")
        cola._max_retries = 2
        cola._dlx_exchange = None

        async def failing_handler(msg):
            raise RuntimeError("boom")

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"reunion_id": "abc"}).encode()
        mock_message.headers = {"x-death": [{"count": 2, "queue": "transcribir"}]}
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
