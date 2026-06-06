from __future__ import annotations

from pathlib import Path
from typing import Protocol


class S3Client(Protocol):
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

    def download_zip(self, bucket: str, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(
            Bucket=bucket,
            Key=key,
            Filename=str(destination),
        )
