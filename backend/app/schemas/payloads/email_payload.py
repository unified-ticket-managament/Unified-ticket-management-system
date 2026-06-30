from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class EmailPayload(BaseModel):
    """
    Internal representation of an incoming
    email stored inside Interaction.payload.
    """

    model_config = ConfigDict(
        extra="ignore",
    )

    client_id: UUID

    client_name: str = Field(
        ...,
        min_length=1,
    )

    agent_id: UUID

    agent_name: str = Field(
        ...,
        min_length=1,
    )

    from_email: EmailStr

    subject: str = Field(
        ...,
        min_length=1,
    )

    body: str = Field(
        ...,
        min_length=1,
    )