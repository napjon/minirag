from __future__ import annotations

import asyncio
import time
from pathlib import Path

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from backend.config import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL_ROOT = REPO_ROOT / "data" / "local" / "objects"


class ObjectStore:
    """S3-compatible object store with a local-directory fallback."""

    def __init__(self, settings: Settings | None = None, local_root: Path | None = None) -> None:
        self.settings = settings or get_settings()
        self.local_root = Path(local_root) if local_root is not None else DEFAULT_LOCAL_ROOT
        self._client: BaseClient | None = None
        self._s3_available: bool | None = None
        self._s3_retry_at: float = 0.0

    def _s3(self) -> BaseClient:
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.settings.object_store_endpoint,
                aws_access_key_id=self.settings.object_store_access_key,
                aws_secret_access_key=self.settings.object_store_secret_key.get_secret_value(),
                region_name=self.settings.object_store_region,
                config=Config(
                    s3={"addressing_style": "path"},
                    connect_timeout=1,
                    read_timeout=3,
                    retries={"max_attempts": 1},
                ),
            )
        return self._client

    def _local_path(self, key: str) -> Path:
        if not key or key.startswith("/") or ".." in Path(key).parts:
            raise ValueError(f"invalid object key: {key}")
        root = self.local_root.resolve()
        path = (root / key).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"invalid object key: {key}")
        return path

    def _put_local(self, key: str, data: bytes) -> None:
        path = self._local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _get_local(self, key: str) -> bytes:
        return self._local_path(key).read_bytes()

    def _s3_should_try(self) -> bool:
        if self._s3_available is not False:
            return True
        return time.monotonic() >= self._s3_retry_at

    def _mark_s3_down(self) -> None:
        self._s3_available = False
        self._s3_retry_at = time.monotonic() + 30

    @staticmethod
    def _missing_object_error(exc: ClientError) -> bool:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        return code in {"404", "NoSuchBucket", "NoSuchKey", "NotFound"}

    def _ensure_bucket(self) -> None:
        client = self._s3()
        bucket = self.settings.object_store_bucket
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            extra: dict[str, object] = {}
            if self.settings.object_store_region != "us-east-1":
                extra["CreateBucketConfiguration"] = {
                    "LocationConstraint": self.settings.object_store_region
                }
            try:
                client.create_bucket(Bucket=bucket, **extra)
            except ClientError as create_exc:
                create_code = str(create_exc.response.get("Error", {}).get("Code", ""))
                if create_code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                    raise

    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        if self._s3_should_try():
            try:
                self._ensure_bucket()
                self._s3().put_object(
                    Bucket=self.settings.object_store_bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                )
                self._s3_available = True
                return
            except ClientError as exc:
                # A missing local development bucket/object can use the local
                # fallback. Permission and credential errors must fail closed.
                if not self._missing_object_error(exc):
                    raise
            except (BotoCoreError, OSError, TimeoutError):
                self._mark_s3_down()
        self._put_local(key, data)

    def get_bytes(self, key: str) -> bytes:
        if self._s3_should_try():
            try:
                response = self._s3().get_object(
                    Bucket=self.settings.object_store_bucket,
                    Key=key,
                )
                self._s3_available = True
                return response["Body"].read()
            except ClientError as exc:
                if not self._missing_object_error(exc):
                    raise
            except (BotoCoreError, OSError, TimeoutError):
                self._mark_s3_down()
        return self._get_local(key)

    async def aput_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        await asyncio.to_thread(self.put_bytes, key, data, content_type)

    async def aget_bytes(self, key: str) -> bytes:
        return await asyncio.to_thread(self.get_bytes, key)


_store: ObjectStore | None = None


def get_object_store(settings: Settings | None = None) -> ObjectStore:
    global _store
    if _store is None:
        _store = ObjectStore(settings or get_settings())
    return _store


def reset_object_store() -> None:
    global _store
    _store = None
