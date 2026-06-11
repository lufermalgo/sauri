"""Interfaz abstracta AlmacenDeObjetos y fábrica de creación."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class AlmacenDeObjetos(ABC):
    """Abstracción cloud-agnóstica para almacenamiento de objetos.

    Contrato:
    - guardar: persiste un objeto y devuelve la clave de referencia.
    - obtener: recupera el contenido de un objeto por referencia.
    - eliminar: borra un objeto por referencia.
    - url_temporal_de_lectura: genera una URL pre-firmada de lectura con TTL.
    """

    @abstractmethod
    async def guardar(
        self,
        clave: str,
        contenido: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Almacena un objeto y devuelve la clave de referencia."""
        ...

    @abstractmethod
    async def obtener(self, referencia: str) -> bytes:
        """Recupera el contenido de un objeto almacenado."""
        ...

    @abstractmethod
    async def eliminar(self, referencia: str) -> None:
        """Elimina un objeto del almacén."""
        ...

    @abstractmethod
    async def url_temporal_de_lectura(
        self,
        referencia: str,
        ttl_seconds: int = 3600,
    ) -> str:
        """Genera una URL temporal pre-firmada para lectura del objeto."""
        ...


def crear_almacen_de_objetos() -> AlmacenDeObjetos:
    """Fábrica que crea la implementación configurada de AlmacenDeObjetos.

    Lee las variables de entorno:
    - OBJECT_STORE_ENDPOINT: URL del endpoint S3/MinIO.
    - OBJECT_STORE_BUCKET: nombre del bucket.
    - MINIO_ROOT_USER: clave de acceso (access key).
    - MINIO_ROOT_PASSWORD: clave secreta (secret key).
    """
    from app.infra.object_store_s3 import AlmacenDeObjetosS3

    endpoint_url = os.environ["OBJECT_STORE_ENDPOINT"]
    bucket = os.environ["OBJECT_STORE_BUCKET"]
    access_key = os.environ["MINIO_ROOT_USER"]
    secret_key = os.environ["MINIO_ROOT_PASSWORD"]

    return AlmacenDeObjetosS3(
        endpoint_url=endpoint_url,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
    )
