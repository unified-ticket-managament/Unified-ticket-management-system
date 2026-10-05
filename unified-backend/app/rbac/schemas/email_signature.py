from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# Same ceiling the legacy single-signature field (UpdateProfileRequest.
# signature_html) has always had — this string is copied into every
# outbound email the user sends.
SIGNATURE_HTML_MAX_LENGTH = 20000
SIGNATURE_NAME_MAX_LENGTH = 100


def _strip_name(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("Signature name cannot be blank.")
    return stripped


class EmailSignatureCreate(BaseModel):
    name: str = Field(..., max_length=SIGNATURE_NAME_MAX_LENGTH)
    html: str = Field(..., max_length=SIGNATURE_HTML_MAX_LENGTH)
    # Optional explicit "make this my default too" — never required: a
    # user's very first signature becomes the default regardless (see
    # EmailSignatureService.create_signature).
    is_default: bool = False

    _name = field_validator("name")(_strip_name)


class EmailSignatureUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=SIGNATURE_NAME_MAX_LENGTH)
    html: str | None = Field(default=None, max_length=SIGNATURE_HTML_MAX_LENGTH)

    _name = field_validator("name")(_strip_name)


class EmailSignatureResponse(BaseModel):
    signature_id: UUID
    name: str
    html: str
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EmailSignatureListResponse(BaseModel):
    signatures: list[EmailSignatureResponse]
    default_signature_id: UUID | None = None
    # Only set when `signatures` is empty: the legacy users.signature_html
    # (plus the company logo block it has always been composed with),
    # so a user with no saved signatures keeps exactly today's
    # composer behavior instead of suddenly composing with nothing.
    fallback_signature_html: str | None = None
    # content_id ("sigimg-<hex>") -> short-lived presigned preview URL,
    # for every signature image referenced by any signature above — the
    # composer/Settings editor show these on screen; what's actually
    # sent is always the `cid:` reference.
    image_urls: dict[str, str] = Field(default_factory=dict)


class EmailSignatureImageResponse(BaseModel):
    image_id: UUID
    content_id: str
    filename: str
    mime_type: str
    size_bytes: int
    preview_url: str | None = None
