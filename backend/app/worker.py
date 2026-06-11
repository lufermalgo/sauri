"""Entrypoint del worker asíncrono de sauri.

Ejecutable como: python -m app.worker

Conecta la cola de trabajos, inicia el worker de transcripción y
mantiene el loop hasta interrupción (SIGINT/SIGTERM).
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.infra.database import create_engine, create_session_factory
from app.infra.object_store import crear_almacen_de_objetos
from app.infra.queue import crear_cola_de_trabajos
from app.retencion.worker import iniciar_worker_retencion
from app.transcripcion.worker import iniciar_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Arranca la cola, suscribe workers y espera hasta shutdown."""
    logger.info("Iniciando worker de sauri...")

    # Infraestructura
    engine = create_engine()
    session_factory = create_session_factory(engine)
    cola = crear_cola_de_trabajos()

    almacen = crear_almacen_de_objetos()

    await cola.conectar()
    logger.info("Conexión a la cola establecida")

    # Suscribir worker de transcripción
    await iniciar_worker(cola, session_factory)

    # Iniciar worker de retención como tarea en segundo plano
    retencion_task = asyncio.create_task(
        iniciar_worker_retencion(session_factory, almacen)
    )

    # Esperar señal de shutdown
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Señal de shutdown recibida, cerrando...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await stop_event.wait()

    # Limpieza
    retencion_task.cancel()
    await cola.desconectar()
    await engine.dispose()
    logger.info("Worker de sauri finalizado")


if __name__ == "__main__":
    asyncio.run(main())
