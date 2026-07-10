"""Property test de conformidad de adaptadores de infraestructura (contract testing).

# Feature: meeting-capture-transcription, Property 13: Conformidad de adaptadores de infraestructura
Task: 7.3 — Validates: Requirements 8.3, 8.4

Ejercita el mismo contrato observable contra múltiples implementaciones conformes
de `AlmacenDeObjetos` y `ColaDeTrabajos` (sin depender de MinIO/RabbitMQ en vivo,
cubiertos por el test de integración 17.3). Cualquier implementación real
(S3/MinIO, RabbitMQ) debe satisfacer el mismo contrato.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.infra.object_store import AlmacenDeObjetos
from app.infra.queue import ColaDeTrabajos


class _AlmacenEnMemoria(AlmacenDeObjetos):
    """Primera implementación conforme: dict en memoria."""

    def __init__(self) -> None:
        self._objetos: dict[str, bytes] = {}

    async def guardar(self, clave: str, contenido: bytes, content_type: str = "application/octet-stream") -> str:
        self._objetos[clave] = contenido
        return clave

    async def obtener(self, referencia: str) -> bytes:
        return self._objetos[referencia]

    async def eliminar(self, referencia: str) -> None:
        self._objetos.pop(referencia, None)

    async def url_temporal_de_lectura(self, referencia: str, ttl_seconds: int = 3600) -> str:
        return f"memoria://{referencia}?ttl={ttl_seconds}"


class _AlmacenListaIndexada(AlmacenDeObjetos):
    """Segunda implementación conforme: lista indexada (estructura interna distinta)."""

    def __init__(self) -> None:
        self._claves: list[str] = []
        self._valores: list[bytes] = []

    def _index(self, referencia: str) -> int:
        return self._claves.index(referencia)

    async def guardar(self, clave: str, contenido: bytes, content_type: str = "application/octet-stream") -> str:
        if clave in self._claves:
            self._valores[self._index(clave)] = contenido
        else:
            self._claves.append(clave)
            self._valores.append(contenido)
        return clave

    async def obtener(self, referencia: str) -> bytes:
        return self._valores[self._index(referencia)]

    async def eliminar(self, referencia: str) -> None:
        if referencia in self._claves:
            i = self._index(referencia)
            del self._claves[i]
            del self._valores[i]

    async def url_temporal_de_lectura(self, referencia: str, ttl_seconds: int = 3600) -> str:
        return f"lista://{referencia}?ttl={ttl_seconds}"


ALMACEN_IMPLEMENTACIONES = [_AlmacenEnMemoria, _AlmacenListaIndexada]


class _ColaEnMemoria(ColaDeTrabajos):
    """Implementación conforme de ColaDeTrabajos: entrega inmediata en memoria."""

    def __init__(self) -> None:
        self._suscriptores: dict[str, list] = {}
        self.entregados: list[tuple[str, dict]] = []

    async def publicar(self, tema: str, mensaje: dict) -> None:
        for manejador in self._suscriptores.get(tema, []):
            await manejador(mensaje)
            self.entregados.append((tema, mensaje))

    async def suscribir(self, tema: str, manejador) -> None:
        self._suscriptores.setdefault(tema, []).append(manejador)

    async def conectar(self) -> None:
        return None

    async def desconectar(self) -> None:
        return None


class _ColaConBuffer(ColaDeTrabajos):
    """Segunda implementación conforme: retiene mensajes publicados sin suscriptor y
    los entrega en cuanto llega uno, además de entregar en vivo a suscriptores activos."""

    def __init__(self) -> None:
        self._suscriptores: dict[str, list] = {}
        self._buffer: dict[str, list[dict]] = {}
        self.entregados: list[tuple[str, dict]] = []

    async def publicar(self, tema: str, mensaje: dict) -> None:
        manejadores = self._suscriptores.get(tema)
        if manejadores:
            for manejador in manejadores:
                await manejador(mensaje)
                self.entregados.append((tema, mensaje))
        else:
            self._buffer.setdefault(tema, []).append(mensaje)

    async def suscribir(self, tema: str, manejador) -> None:
        self._suscriptores.setdefault(tema, []).append(manejador)
        for mensaje in self._buffer.get(tema, []):
            await manejador(mensaje)
            self.entregados.append((tema, mensaje))
        self._buffer[tema] = []

    async def conectar(self) -> None:
        return None

    async def desconectar(self) -> None:
        return None


COLA_IMPLEMENTACIONES = [_ColaEnMemoria, _ColaConBuffer]


# ---------------------------------------------------------------------------
# Property 13: Conformidad de adaptadores de infraestructura
# Feature: meeting-capture-transcription, Property 13: Conformidad de adaptadores de infraestructura
# Validates: Requirements 8.3, 8.4
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    impl_cls=st.sampled_from(ALMACEN_IMPLEMENTACIONES),
    clave=st.text(min_size=1, max_size=30),
    contenido=st.binary(min_size=0, max_size=200),
)
@pytest.mark.asyncio
async def test_property_13_almacen_roundtrip_guardar_obtener(impl_cls, clave: str, contenido: bytes) -> None:
    """Round-trip guardar→obtener devuelve el mismo contenido, para cualquier implementación conforme."""
    almacen: AlmacenDeObjetos = impl_cls()
    referencia = await almacen.guardar(clave, contenido)
    recuperado = await almacen.obtener(referencia)
    assert recuperado == contenido


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    impl_cls=st.sampled_from(ALMACEN_IMPLEMENTACIONES),
    clave=st.text(min_size=1, max_size=30),
    contenido=st.binary(min_size=0, max_size=200),
)
@pytest.mark.asyncio
async def test_property_13_almacen_eliminar_deja_indisponible(impl_cls, clave: str, contenido: bytes) -> None:
    """eliminar deja el objeto indisponible, para cualquier implementación conforme."""
    almacen: AlmacenDeObjetos = impl_cls()
    referencia = await almacen.guardar(clave, contenido)
    await almacen.eliminar(referencia)

    with pytest.raises((KeyError, ValueError, IndexError)):
        await almacen.obtener(referencia)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    impl_cls=st.sampled_from(COLA_IMPLEMENTACIONES),
    tema=st.text(min_size=1, max_size=20),
    mensaje=st.dictionaries(st.text(min_size=1, max_size=10), st.integers(), max_size=5),
)
@pytest.mark.asyncio
async def test_property_13_cola_mensaje_publicado_se_entrega_al_suscriptor(
    impl_cls, tema: str, mensaje: dict
) -> None:
    """Un mensaje publicado en un tema se entrega al suscriptor de ese tema, para cualquier implementación conforme."""
    cola: ColaDeTrabajos = impl_cls()
    recibidos: list[dict] = []

    async def manejador(msg: dict) -> None:
        recibidos.append(msg)

    await cola.suscribir(tema, manejador)
    await cola.publicar(tema, mensaje)

    assert mensaje in recibidos
