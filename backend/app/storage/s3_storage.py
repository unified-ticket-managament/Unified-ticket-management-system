# storage/s3_storage.py

import boto3
from anyio import to_thread
from botocore.client import Config
from botocore.exceptions import ClientError

from app.storage.base import StorageService


class S3StorageService(StorageService):
    """
    boto3-backed StorageService. Works against MinIO when
    `endpoint_url` is set (local dev), and against AWS S3 or any
    S3-compatible host (e.g. Cloudflare R2) when pointed at that
    host's endpoint — same code path either way.
    """

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        access_key: str | None,
        secret_key: str | None,
        region: str,
        use_ssl: bool,
        url_expiry_seconds: int,
    ):
        self.bucket = bucket
        self.url_expiry_seconds = url_expiry_seconds
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            use_ssl=use_ssl,
            config=Config(signature_version="s3v4"),
        )

    async def upload(self, *, data: bytes, object_key: str, content_type: str) -> None:
        await to_thread.run_sync(
            lambda: self._client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=data,
                ContentType=content_type,
            )
        )

    async def download(self, *, object_key: str) -> bytes:
        def _get() -> bytes:
            response = self._client.get_object(Bucket=self.bucket, Key=object_key)
            return response["Body"].read()

        return await to_thread.run_sync(_get)

    async def delete(self, *, object_key: str) -> None:
        await to_thread.run_sync(
            lambda: self._client.delete_object(Bucket=self.bucket, Key=object_key)
        )

    async def exists(self, *, object_key: str) -> bool:
        def _head() -> bool:
            try:
                self._client.head_object(Bucket=self.bucket, Key=object_key)
                return True
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                    return False
                raise

        return await to_thread.run_sync(_head)

    async def presigned_get_url(
        self, *, object_key: str, filename: str, inline: bool = False
    ) -> str:
        # No network round-trip here — boto3 signs locally — but the
        # interface is async so every backend (e.g. Supabase, which
        # does need a round-trip) has the same shape.
        disposition = "inline" if inline else f'attachment; filename="{filename}"'
        return self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": object_key,
                "ResponseContentDisposition": disposition,
            },
            ExpiresIn=self.url_expiry_seconds,
        )
