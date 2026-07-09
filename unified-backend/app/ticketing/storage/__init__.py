# storage/__init__.py

from app.core.config import get_settings
from app.ticketing.storage.base import StorageConfigurationError, StorageService
from app.ticketing.storage.s3_storage import S3StorageService
from app.ticketing.storage.supabase_storage import SupabaseStorageService


def get_storage_service() -> StorageService:
    settings = get_settings()

    if settings.storage_backend == "supabase":
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise StorageConfigurationError(
                "STORAGE_BACKEND=supabase requires SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY to be set."
            )
        return SupabaseStorageService(
            bucket=settings.storage_bucket,
            project_url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            url_expiry_seconds=settings.storage_url_expiry_seconds,
        )

    if settings.storage_backend == "s3":
        if not settings.storage_access_key or not settings.storage_secret_key:
            raise StorageConfigurationError(
                "STORAGE_BACKEND=s3 requires STORAGE_ACCESS_KEY and "
                "STORAGE_SECRET_KEY to be set."
            )

    return S3StorageService(
        bucket=settings.storage_bucket,
        endpoint_url=settings.storage_endpoint_url,
        access_key=settings.storage_access_key,
        secret_key=settings.storage_secret_key,
        region=settings.storage_region,
        use_ssl=settings.storage_use_ssl,
        url_expiry_seconds=settings.storage_url_expiry_seconds,
    )
