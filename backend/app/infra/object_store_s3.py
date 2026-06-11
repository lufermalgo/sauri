"""Implementación S3-compatible de AlmacenDeObjetos (MinIO local / S3 / GCS)."""

from __future__ import annotations

import asyncio
import functools

import boto3
from botocore.config import Config

from app.infra.object_store import AlmacenDeObjetos


class AlmacenDeObjetosS3(AlmacenDeObjetos):
    """Almacén de objetos respaldado por un endpoint compatible con S3.

    Funciona con MinIO (desarrollo local), AWS S3 y GCS (interop S3).
    Las operaciones de boto3 (síncronas) se ejecutan en un hilo separado
    para no bloquear el event loop de asyncio.
    """

    def __init__(
        self,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
        )

    # ------------------------------------------------------------------
    # Interfaz AlmacenDeObjetos
    # ------------------------------------------------------------------

    async def guardar(
        self,
        clave: str,
        contenido: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Sube un objeto al bucket y devuelve la clave como referencia."""
        await asyncio.to_thread(
            functools.partial(
                self._client.put_object,
                Bucket=self._bucket,
                Key=clave,
                Body=contenido,
                ContentType=content_type,
            )
        )
        return clave

    async def obtener(self, referencia: str) -> bytes:
        """Descarga el contenido de un objeto del bucket."""
        response = await asyncio.to_thread(
            functools.partial(
                self._client.get_object,
                Bucket=self._bucket,
                Key=referencia,
            )
        )
        body: bytes = response["Body"].read()
        return body

    async def eliminar(self, referencia: str) -> None:
        """Elimina un objeto del bucket."""
        await asyncio.to_thread(
            functools.partial(
                self._client.delete_object,
                Bucket=self._bucket,
                Key=referencia,
            )
        )

    async def url_temporal_de_lectura(
        self,
        referencia: str,
        ttl_seconds: int = 3600,
    ) -> str:
        """Genera una URL pre-firmada de lectura con expiración."""
        url: str = await asyncio.to_thread(
            functools.partial(
                self._client.generate_presigned_url,
                ClientMethod="get_object",
                Params={"Bucket": self._bucket, "Key": referencia},
                ExpiresIn=ttl_seconds,
            )
        )
        return url
