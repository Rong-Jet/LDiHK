from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, Protocol


@dataclass(frozen=True)
class S3ObjectMetadata:
    content_length: int


class S3Client(Protocol):
    def head_object(self, bucket: str, key: str) -> S3ObjectMetadata:
        ...

    def download_zip(self, bucket: str, key: str, destination: Path) -> None:
        ...


def create_boto3_s3_client(environ: Mapping[str, str] = os.environ):
    """Build a boto3 S3 client for AWS or any S3-compatible store.

    Set ``S3_ENDPOINT_URL`` for Cloudflare R2, Backblaze B2 or MinIO, e.g.
    ``https://<account-id>.r2.cloudflarestorage.com``. Checksums are only
    sent when an operation requires them: the defaults of newer SDKs break
    several S3-compatible stores.
    """
    try:
        import boto3
        from botocore.config import Config
    except ModuleNotFoundError as error:  # pragma: no cover - env-dependent
        raise RuntimeError(
            "boto3 is required to download S3 imports; install boto3 or "
            "inject a test S3Client"
        ) from error

    endpoint_url = environ.get("S3_ENDPOINT_URL", "").strip() or None
    region_name = (
        environ.get("AWS_REGION", "").strip()
        or environ.get("AWS_DEFAULT_REGION", "").strip()
        or ("auto" if endpoint_url else None)
    )
    config = Config(
        signature_version="s3v4",
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
        s3={"addressing_style": "path"} if endpoint_url else None,
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region_name,
        config=config,
    )


class Boto3S3Client:
    def __init__(self, client=None) -> None:
        if client is None:
            client = create_boto3_s3_client()
        self._client = client

    def head_object(self, bucket: str, key: str) -> S3ObjectMetadata:
        response = self._client.head_object(Bucket=bucket, Key=key)
        try:
            content_length = int(response["ContentLength"])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("S3 HeadObject response missing ContentLength") from error
        return S3ObjectMetadata(content_length=content_length)

    def download_zip(self, bucket: str, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(
            Bucket=bucket,
            Key=key,
            Filename=str(destination),
        )
