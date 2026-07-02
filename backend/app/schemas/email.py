from pydantic import BaseModel, EmailStr, Field

from app.schemas.attachment import AttachmentMetadata


class EmailRequest(BaseModel):
    """
    Incoming email received from
    the communication platform (N8N).

    This is NOT a database entity.

    The EmailService converts this
    request into an Interaction.
    """

    from_email: EmailStr

    subject: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )

    body: str = Field(
        ...,
        min_length=1,
    )

    message_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )


class EmailResponse(BaseModel):
    """
    Response returned after successfully
    storing the email as a pending
    interaction.
    """

    message: str

    interaction_id: str

    client_name: str

    agent_name: str

    status: str

    attachments: list[AttachmentMetadata] = Field(default_factory=list)