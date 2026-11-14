"""Wait for the configured S3-compatible service and ensure its bucket exists."""

from __future__ import annotations

import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError

from app.infra.secrets import object_store_credentials


def ensure_bucket() -> None:
    endpoint = os.environ["OBJECT_STORE_ENDPOINT"]
    bucket = os.environ["OBJECT_STORE_BUCKET"]
    access_key, secret_key = object_store_credentials()
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", connect_timeout=2, read_timeout=2),
    )
    deadline = time.monotonic() + 60
    while True:
        try:
            if not client.head_bucket(Bucket=bucket):
                client.create_bucket(Bucket=bucket)
            print(f"Object-store bucket ready: {bucket}")
            return
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchBucket", "Not Found"}:
                try:
                    client.create_bucket(Bucket=bucket)
                except ClientError as create_error:
                    if create_error.response.get("Error", {}).get("Code") not in {
                        "BucketAlreadyOwnedByYou",
                        "BucketAlreadyExists",
                    }:
                        raise
                print(f"Object-store bucket ready: {bucket}")
                return
            raise
        except EndpointConnectionError as error:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Object-store endpoint did not become ready: {endpoint}") from error
            time.sleep(1)


if __name__ == "__main__":
    ensure_bucket()
