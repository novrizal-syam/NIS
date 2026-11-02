"""S3-compatible object storage (MinIO in dev). boto3 is sync, so calls run in a thread."""

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.errors import NotFoundError

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


@dataclass(frozen=True)
class StoredObject:
    key: str
    data: bytes
    content_type: str


class Storage:
    def __init__(self, client: "S3Client", bucket: str) -> None:
        self._client = client
        self.bucket = bucket

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)

    async def ensure_bucket(self) -> None:
        await asyncio.to_thread(self._ensure_bucket)

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    def _get(self, key: str) -> StoredObject:
        try:
            obj = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise NotFoundError("FILE_NOT_FOUND", "Berkas tidak ditemukan.") from exc
            raise
        return StoredObject(key=key, data=obj["Body"].read(), content_type=obj["ContentType"])

    async def get(self, key: str) -> StoredObject:
        return await asyncio.to_thread(self._get, key)

    async def presigned_url(self, key: str, expires_in: int = 300) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return Storage(client, s.s3_bucket)
