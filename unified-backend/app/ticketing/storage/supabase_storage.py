# storage/supabase_storage.py

from urllib.parse import quote

import httpx

from app.ticketing.storage.base import StorageService


class SupabaseStorageService(StorageService):
    """
    Supabase Storage-backed StorageService, talking to its REST API
    directly (Supabase Storage isn't S3-compatible for the average
    project — that requires separately-provisioned S3 credentials —
    so this uses the project URL + service_role key instead of
    boto3). The service_role key is server-only and must never reach
    the frontend; it authorizes every call here as a trusted client.
    """

    def __init__(
        self,
        *,
        bucket: str,
        project_url: str,
        service_role_key: str,
        url_expiry_seconds: int,
    ):
        self.bucket = bucket
        self.url_expiry_seconds = url_expiry_seconds
        self._storage_url = f"{project_url.rstrip('/')}/storage/v1"
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {service_role_key}",
                "apikey": service_role_key,
            },
            timeout=30.0,
        )

    async def upload(self, *, data: bytes, object_key: str, content_type: str) -> None:
        response = await self._client.post(
            f"{self._storage_url}/object/{self.bucket}/{object_key}",
            content=data,
            headers={"Content-Type": content_type},
        )
        response.raise_for_status()

    async def download(self, *, object_key: str) -> bytes:
        response = await self._client.get(
            f"{self._storage_url}/object/{self.bucket}/{object_key}"
        )
        response.raise_for_status()
        return response.content

    async def delete(self, *, object_key: str) -> None:
        response = await self._client.request(
            "DELETE",
            f"{self._storage_url}/object/{self.bucket}/{object_key}",
        )
        response.raise_for_status()

    async def exists(self, *, object_key: str) -> bool:
        response = await self._client.get(
            f"{self._storage_url}/object/info/{self.bucket}/{object_key}"
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    async def presigned_get_url(
        self, *, object_key: str, filename: str, inline: bool = False
    ) -> str:
        response = await self._client.post(
            f"{self._storage_url}/object/sign/{self.bucket}/{object_key}",
            json={"expiresIn": self.url_expiry_seconds},
        )
        response.raise_for_status()
        signed_path = response.json()["signedURL"]
        url = f"{self._storage_url}{signed_path}"

        if not inline:
            # Supabase only sets Content-Disposition: attachment when
            # a `download` query param is present on the *signed* URL
            # itself — it's not a field the /sign request body reads.
            separator = "&" if "?" in url else "?"
            url += f"{separator}download={quote(filename)}"

        return url
