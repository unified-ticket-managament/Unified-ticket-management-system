# storage/base.py

from abc import ABC, abstractmethod


class StorageConfigurationError(RuntimeError):
    """
    Raised when the selected STORAGE_BACKEND is missing required
    settings (e.g. SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY). A
    dedicated type so app/main.py can register a handler that
    returns a proper JSON 503 instead of this crashing as an
    unhandled exception — which some deployment proxies turn into a
    bare response with no CORS headers, surfacing to the browser as
    an opaque "network error" instead of a readable message.
    """


class StorageService(ABC):
    """
    Object storage abstraction. Concrete implementations talk to a
    specific backend (Supabase Storage, MinIO, AWS S3, Cloudflare
    R2, ...) — callers only ever see this interface, so swapping the
    backend later is a config change, not a code change.
    """

    @abstractmethod
    async def upload(self, *, data: bytes, object_key: str, content_type: str) -> None:
        ...

    @abstractmethod
    async def download(self, *, object_key: str) -> bytes:
        ...

    @abstractmethod
    async def delete(self, *, object_key: str) -> None:
        ...

    @abstractmethod
    async def exists(self, *, object_key: str) -> bool:
        ...

    @abstractmethod
    async def presigned_get_url(
        self, *, object_key: str, filename: str, inline: bool = False
    ) -> str:
        # Async because backends like Supabase Storage mint signed
        # URLs via a real API call — unlike boto3, which signs
        # locally with no network round-trip.
        ...
