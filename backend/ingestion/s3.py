from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class S3ObjectMetadata:
    content_length: int


class S3Client(Protocol):
    def head_object(self, bucket: str, key: str) -> S3ObjectMetadata:
        ...

    def download_zip(self, bucket: str, key: str, destination: Path) -> None:
        ...


class Boto3S3Client:
    def __init__(self, client=None) -> None:
        if client is None:
            try:
                import boto3
            except ModuleNotFoundError as error:  # pragma: no cover - env-dependent
                raise RuntimeError(
                    "boto3 is required to download S3 imports; install boto3 or "
                    "inject a test S3Client"
                ) from error
            client = boto3.client("s3")
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
