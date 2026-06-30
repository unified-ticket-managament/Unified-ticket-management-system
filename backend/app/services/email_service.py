from app.data.dummy_client_mapping import CLIENT_ASSIGNMENTS
from app.enums import (
    InteractionDirection,
    InteractionStatus,
)
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.schemas.email import (
    EmailRequest,
    EmailResponse,
)
from app.schemas.interaction import (
    InteractionCreate,
)


class EmailService:
    """
    Handles incoming emails.

    Workflow

    Receive Email
            │
            ▼
    Validate Duplicate
            │
            ▼
    Lookup Client → Agent
            │
            ▼
    Create Pending Interaction
            │
            ▼
    Return Response
    """

    def __init__(
        self,
        interaction_repository: InteractionRepository,
    ):
        self.interaction_repository = interaction_repository

    async def receive_email(
        self,
        email: EmailRequest,
    ) -> EmailResponse:

        # ---------------------------------------
        # Duplicate Message-ID Check
        # ---------------------------------------

        exists = (
            await self.interaction_repository
            .exists_by_message_id(
                email.message_id
            )
        )

        if exists:
            raise ValueError(
                "Email already processed."
            )

        # ---------------------------------------
        # Dummy Client Lookup
        # ---------------------------------------

        mapping = CLIENT_ASSIGNMENTS.get(
            email.from_email.lower()
        )

        if mapping is None:
            raise ValueError(
                "Unknown client email."
            )

        # ---------------------------------------
        # Build Interaction Payload
        # ---------------------------------------

        payload = {

            "from_email": email.from_email,

            "subject": email.subject,

            "body": email.body,

            "client_id": str(
                mapping["client_id"]
            ),

            "client_name": mapping[
                "client_name"
            ],

            "agent_id": str(
                mapping["agent_id"]
            ),

            "agent_name": mapping[
                "agent_name"
            ],
        }

        # ---------------------------------------
        # Convert Email → Interaction
        # ---------------------------------------

        interaction = InteractionCreate(

    ticket_id=None,

    interaction_type="EMAIL",

    status=InteractionStatus.PENDING,

    direction=InteractionDirection.INBOUND,

    # No authenticated user exists yet.
    # The email has only been received.
    # The client information is stored inside payload.
    performed_by=None,

    payload=payload,

    is_visible=True,

    message_id=email.message_id,
)

        created = (
            await self.interaction_repository
            .create(interaction)
        )

        # ---------------------------------------
        # Response
        # ---------------------------------------

        return EmailResponse(

            message="Email received successfully.",

            interaction_id=str(
                created.interaction_id
            ),

            client_name=mapping[
                "client_name"
            ],

            agent_name=mapping[
                "agent_name"
            ],

            status=created.status.value,
        )