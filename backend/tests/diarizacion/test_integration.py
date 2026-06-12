"""Tests de integración del módulo identificacion-hablantes (diarización).

# Feature: identificacion-hablantes
Tasks: 15.1, 15.2, 15.4
Validates: Requirements 1.1, 1.2, 1.7, 1.8, 4.1, 4.3, 10.2

NOTA: Los mocks/transports simulados aquí actúan SOLO en los tests para aislar
fronteras de I/O (cola, motor, red). El código de producción es 100% real.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infra.models import Reunion
from app.diarizacion.worker import iniciar_worker


# ---------------------------------------------------------------------------
# Task 15.1 — Suscripción al tema "diarizar" (Req 1.1)
# ---------------------------------------------------------------------------


class TestSuscripcionWorkerDiarizacion:
    """El worker de diarización se suscribe al tema 'diarizar' al iniciar."""

    @pytest.mark.asyncio
    async def test_worker_se_suscribe_a_tema_diarizar(self):
        """Al iniciar, el worker se suscribe al tema 'diarizar' (Req 1.1)."""
        mock_cola = AsyncMock()
        mock_cola.suscribir = AsyncMock()
        mock_session_factory = AsyncMock()

        await iniciar_worker(mock_cola, mock_session_factory)

        mock_cola.suscribir.assert_called_once()
        call_args = mock_cola.suscribir.call_args
        assert call_args[0][0] == "diarizar"
        assert callable(call_args[0][1])


# ---------------------------------------------------------------------------
# Task 15.1 — Publicación del Mensaje_De_Diarizacion al completar transcripción (Req 1.2)
# ---------------------------------------------------------------------------


class TestPublicacionMensajeDiarizacion:
    """Al quedar disponible una Transcripcion, se publica un Mensaje_De_Diarizacion."""

    @pytest.mark.asyncio
    async def test_publica_diarizar_al_completar_transcripcion(
        self, session_factory: async_sessionmaker
    ):
        """Tras persistir la Transcripcion, se publica {reunion_id} al tema 'diarizar' (Req 1.2)."""
        from app.transcripcion.motor_asr import (
            CapacidadesASR,
            ResultadoTranscripcion,
            SegmentoTranscripcion,
        )
        from app.transcripcion.worker import _procesar_transcripcion

        reunion_id = str(uuid.uuid4())
        async with session_factory() as session:
            async with session.begin():
                session.add(
                    Reunion(
                        id=reunion_id,
                        enlace_meet="https://meet.google.com/abc-defg-hij",
                        origen="enlace",
                        id_invitacion_calendario=None,
                        hora_inicio_programada=None,
                        estado_proceso="grabando",
                        causa_fallo=None,
                        creada_por="test-user",
                        creada_en=datetime.now(timezone.utc),
                    )
                )

        segmentos = [SegmentoTranscripcion(texto="hola", inicio_ms=0, fin_ms=1000)]
        resultado = ResultadoTranscripcion(segmentos=segmentos, idioma="es-CO", soporta_turnos=True)
        motor = AsyncMock()
        motor.transcribir.return_value = resultado
        motor.capacidades = MagicMock(return_value=CapacidadesASR(soporta_turnos=True, es_local=True))

        mock_cola = AsyncMock()
        mock_cola.publicar = AsyncMock()

        mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}
        with patch("app.transcripcion.worker.crear_motor_asr", return_value=motor):
            await _procesar_transcripcion(mensaje, session_factory, mock_cola)

        # Debe haberse publicado el Mensaje_De_Diarizacion con el reunion_id
        publicaciones_diarizar = [
            c for c in mock_cola.publicar.call_args_list if c[0][0] == "diarizar"
        ]
        assert len(publicaciones_diarizar) == 1
        assert publicaciones_diarizar[0][0][1] == {"reunion_id": reunion_id}

    @pytest.mark.asyncio
    async def test_no_publica_si_no_hay_transcripcion(
        self, session_factory: async_sessionmaker
    ):
        """Si la transcripción falla (sin segmentos), no se publica a 'diarizar'."""
        from app.transcripcion.motor_asr import (
            CapacidadesASR,
            ResultadoTranscripcion,
        )
        from app.transcripcion.worker import _procesar_transcripcion

        reunion_id = str(uuid.uuid4())
        async with session_factory() as session:
            async with session.begin():
                session.add(
                    Reunion(
                        id=reunion_id,
                        enlace_meet="https://meet.google.com/abc-defg-hij",
                        origen="enlace",
                        id_invitacion_calendario=None,
                        hora_inicio_programada=None,
                        estado_proceso="grabando",
                        causa_fallo=None,
                        creada_por="test-user",
                        creada_en=datetime.now(timezone.utc),
                    )
                )

        resultado = ResultadoTranscripcion(segmentos=[], idioma="es-CO", soporta_turnos=True)
        motor = AsyncMock()
        motor.transcribir.return_value = resultado
        motor.capacidades = MagicMock(return_value=CapacidadesASR(soporta_turnos=True, es_local=True))

        mock_cola = AsyncMock()
        mock_cola.publicar = AsyncMock()

        mensaje = {"reunion_id": reunion_id, "audio_ref": "audio/test.webm"}
        with patch("app.transcripcion.worker.crear_motor_asr", return_value=motor):
            await _procesar_transcripcion(mensaje, session_factory, mock_cola)

        publicaciones_diarizar = [
            c for c in mock_cola.publicar.call_args_list if c[0][0] == "diarizar"
        ]
        assert len(publicaciones_diarizar) == 0


# ---------------------------------------------------------------------------
# Task 15.2 — ack/nack y reintentos acotados por DIARIZATION_MAX_RETRIES
# Validates: Requirements 1.7, 1.8, 10.2
# ---------------------------------------------------------------------------


class TestAckNackReintentosDiarizar:
    """Integración con la ColaDeRabbitMQ: ack en éxito, nack en fallo, reintentos."""

    @pytest.mark.asyncio
    async def test_ack_tras_exito(self):
        """Manejador exitoso → ack (Req 1.7)."""
        import json
        from app.infra.queue_rabbitmq import ColaDeRabbitMQ

        cola = ColaDeRabbitMQ("amqp://guest:guest@localhost/")
        cola._dlx_exchange = None

        async def manejador_ok(_msg):
            return None

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"reunion_id": "abc"}).encode()
        mock_message.headers = {}
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()

        cola._channel = AsyncMock()
        mock_queue = AsyncMock()
        cola._channel.declare_queue.return_value = mock_queue

        captured = {}

        async def capture_consume(cb):
            captured["cb"] = cb

        mock_queue.consume = capture_consume

        await cola.suscribir("diarizar", manejador_ok)
        await captured["cb"](mock_message)

        mock_message.ack.assert_awaited_once()
        mock_message.nack.assert_not_called()

    @pytest.mark.asyncio
    async def test_nack_tras_excepcion_con_reintentos_diarization(self):
        """Manejador con excepción → nack reencolando mientras hay reintentos (Req 1.8, 10.2)."""
        import json
        from app.infra.queue_rabbitmq import ColaDeRabbitMQ

        with patch.dict(os.environ, {"DIARIZATION_MAX_RETRIES": "3"}, clear=False):
            cola = ColaDeRabbitMQ("amqp://guest:guest@localhost/")
            cola._dlx_exchange = None

            async def manejador_falla(_msg):
                raise RuntimeError("fallo del motor")

            mock_message = AsyncMock()
            mock_message.body = json.dumps({"reunion_id": "abc"}).encode()
            mock_message.headers = {}  # 0 reintentos previos
            mock_message.ack = AsyncMock()
            mock_message.nack = AsyncMock()

            cola._channel = AsyncMock()
            mock_queue = AsyncMock()
            cola._channel.declare_queue.return_value = mock_queue

            captured = {}

            async def capture_consume(cb):
                captured["cb"] = cb

            mock_queue.consume = capture_consume

            await cola.suscribir("diarizar", manejador_falla)
            await captured["cb"](mock_message)

            # 0 < 3 reintentos → nack con requeue=True
            mock_message.nack.assert_awaited_once_with(requeue=True)
            mock_message.ack.assert_not_called()


# ---------------------------------------------------------------------------
# Task 15.4 — Egreso HTTPS + autenticación Bearer del Proveedor_Nube
# Validates: Requirements 4.1, 4.3
# ---------------------------------------------------------------------------


class TestEgresoHTTPSProveedorNube:
    """El Proveedor_Nube transmite por HTTPS con cabecera Authorization: Bearer."""

    @pytest.mark.asyncio
    async def test_transmite_https_con_bearer(self):
        """El request sale por HTTPS con 'Authorization: Bearer {api_key}' (Req 4.1, 4.3)."""
        from app.diarizacion.motor_diarizacion import OpcionesDiarizacion

        capturado: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            capturado["url"] = str(request.url)
            capturado["scheme"] = request.url.scheme
            capturado["auth"] = request.headers.get("Authorization")
            return httpx.Response(
                200,
                json={
                    "segments": [{"speaker": "S0", "start_ms": 0, "end_ms": 1000}],
                    "num_speakers": 1,
                },
            )

        transport = httpx.MockTransport(handler)

        env = {
            "DIARIZATION_CLOUD_ENDPOINT": "https://api.diarization.example.com/diarize",
            "DIARIZATION_CLOUD_API_KEY": "sk-secreta-123",
        }
        with patch.dict(os.environ, env, clear=False):
            from app.diarizacion.proveedor_nube import ProveedorNube

            proveedor = ProveedorNube()

            # Inyectar el transporte simulado SOLO en el test
            original_client = httpx.AsyncClient

            def client_factory(*args, **kwargs):
                kwargs["transport"] = transport
                return original_client(*args, **kwargs)

            with patch("app.diarizacion.proveedor_nube.httpx.AsyncClient", client_factory):
                await proveedor.diarizar("audio/test.wav", OpcionesDiarizacion(duracion_ms=10000))

        assert capturado["scheme"] == "https"
        assert capturado["url"].startswith("https://")
        assert capturado["auth"] == "Bearer sk-secreta-123"
