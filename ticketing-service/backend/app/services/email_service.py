from fastapi import UploadFile

from app.enums import (
    ActorRole,
    AuditEntityType,
    AuditEventType,
    InteractionDirection,
    InteractionStatus,
)
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.user_repository import UserRepository
from app.schemas.attachment import AttachmentMetadata
from app.schemas.email import (
    EmailRequest,
    EmailResponse,
)
from app.schemas.interaction import (
    InteractionCreate,
)
from app.services.agent_assignment_service import AgentAssignmentService
from app.services.attachment_service import (
    AttachmentService,
    attachments_to_metadata,
)
from app.services.audit_log_service import AuditLogService

VIEWER_ROLE_NAME = "Viewer"


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
    Lookup Client (users table, role = Viewer)
            │
            ▼
    Assign Agent (interim rule — see AgentAssignmentService)
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
        user_repository: UserRepository,
        agent_assignment_service: AgentAssignmentService,
        attachment_service: AttachmentService,
    ):
        self.interaction_repository = interaction_repository
        self.user_repository = user_repository
        self.agent_assignment_service = agent_assignment_service
        self.attachment_service = attachment_service

    async def receive_email(
        self,
        email: EmailRequest,
        files: list[UploadFile] | None = None,
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
        # Client Lookup (real users table)
        # ---------------------------------------

        client = await self.user_repository.get_by_email(
            email.from_email
        )

        if client is None or client.role.name != VIEWER_ROLE_NAME:
            raise ValueError(
                "Unknown client email."
            )

        # ---------------------------------------
        # Agent Assignment (interim rule)
        # ---------------------------------------

        agent = await self.agent_assignment_service.select_agent()

        if agent is None:
            raise ValueError(
                "No active agents available."
            )

        # ---------------------------------------
        # Build Interaction Payload
        # ---------------------------------------

        payload = {

            "from_email": email.from_email,

            "subject": email.subject,

            "body": email.body,

            "client_id": str(
                client.user_id
            ),

            "client_name": client.name,

            "agent_id": str(
                agent.user_id
            ),

            "agent_name": agent.name,
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
        # Audit Trail — the client is the actor here,
        # not the assigning agent.
        # ---------------------------------------

        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=created.interaction_id,
            event_type=AuditEventType.EMAIL_RECEIVED,
            actor_id=client.user_id,
            actor_name=client.name,
            actor_role=ActorRole.CLIENT,
            new_values={
                "subject": email.subject,
                "message_id": email.message_id,
                "assigned_agent_id": agent.user_id,
                "assigned_agent_name": agent.name,
            },
        )

        # ---------------------------------------
        # Attachments (optional)
        # ---------------------------------------

        attachment_metas: list[AttachmentMetadata] = []

        if files:
            attachments = await self.attachment_service.validate_and_store_files(
                files, created.interaction_id
            )
            attachment_metas = await attachments_to_metadata(
                attachments, self.attachment_service.storage_service
            )

        # ---------------------------------------
        # Response
        # ---------------------------------------

        return EmailResponse(

            message="Email received successfully.",

            interaction_id=str(
                created.interaction_id
            ),

            client_name=client.name,

            agent_name=agent.name,

            status=created.status.value,

            attachments=attachment_metas,
        )
