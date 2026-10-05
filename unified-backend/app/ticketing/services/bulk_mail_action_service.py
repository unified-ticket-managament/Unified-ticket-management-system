import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.message_read_receipt_repository import (
    MessageReadReceiptRepository,
)
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.attach_interaction import AttachInteractionRequest
from app.ticketing.schemas.bulk_mail_action import (
    BulkMailActionItemResult,
    BulkMailActionRequest,
    BulkMailActionResponse,
)
from app.ticketing.schemas.interaction import FolderAssignRequest, HideInteractionRequest
from app.ticketing.schemas.ticket_from_interaction import TicketFromInteractionCreate
from app.ticketing.services.access_control import (
    ACCOUNT_MANAGER_ROLE_NAME,
    ensure_account_manager_owns_ticket_client,
    ensure_agent_can_view_pending_interaction,
    ensure_agent_can_view_ticket,
)
from app.ticketing.services.assignment_service import AssignmentService
from app.ticketing.services.delegated_access import resolve_delegated_thread_access
from app.ticketing.services.escalation_service import build_escalation_service
from app.ticketing.services.inbox_ticket_service import InboxTicketService
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.mail_folder_service import MailFolderService
from app.ticketing.services.message_mark_service import MessageMarkService
from app.ticketing.repositories.message_mark_repository import MessageMarkRepository
from app.ticketing.services.message_read_status_service import (
    MessageReadStatusService,
)
from app.ticketing.services.sla_service import build_sla_service

logger = logging.getLogger(__name__)

NOT_AVAILABLE = "Not available."
NOT_ELIGIBLE = "Not eligible for this action."
COULD_NOT_PROCESS = "Could not be processed."
FOLDER_NOT_AVAILABLE = "Folder not available."


def _safe_reason(exc: HTTPException) -> str:
    """
    Maps an existing service's HTTPException onto a deliberately
    generic message — the original `detail` can name clients/tickets
    the caller may not be allowed to know about.
    """

    if exc.status_code in (401, 403, 404):
        return NOT_AVAILABLE
    if exc.status_code in (400, 409, 422):
        return NOT_ELIGIBLE
    return COULD_NOT_PROCESS


class BulkMailActionService:
    """
    Thin dispatcher: runs ONE existing single-interaction workflow once
    per selected interaction. It owns no business rules — every
    authorization, state check, SLA/ticket/audit side effect lives in the
    service it calls, so a bulk run behaves exactly like N single runs.

    Each interaction runs inside its own SAVEPOINT (`begin_nested`), so
    one failure rolls back only that item and never the others.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        interaction_repository: InteractionRepository,
        ticket_repository: TicketRepository,
        client_repository: ClientRepository,
        mail_folder_repository: MailFolderRepository,
        rule_repository: RuleRepository,
        distribution_list_repository: DistributionListRepository,
        read_status_service: MessageReadStatusService,
        message_mark_service: MessageMarkService,
        interaction_service: InteractionService,
        inbox_ticket_service: InboxTicketService,
    ):
        self.db = db
        self.interaction_repository = interaction_repository
        self.ticket_repository = ticket_repository
        self.client_repository = client_repository
        self.mail_folder_repository = mail_folder_repository
        self.rule_repository = rule_repository
        self.distribution_list_repository = distribution_list_repository
        self.read_status_service = read_status_service
        self.message_mark_service = message_mark_service
        self.interaction_service = interaction_service
        self.inbox_ticket_service = inbox_ticket_service

    # -----------------------------------------------------------------

    async def run(
        self, request: BulkMailActionRequest, current_user: User
    ) -> BulkMailActionResponse:
        # De-duplicate while keeping the caller's order.
        interaction_ids = list(dict.fromkeys(request.interaction_ids))

        # Move target is checked once: an unauthorized folder fails every
        # item rather than letting set_interaction_folder (which only
        # checks existence) file mail into a folder the caller can't see.
        folder_ok = True
        if request.action == "move" and request.folder_id is not None:
            folder_ok = await self._folder_is_usable(request.folder_id, current_user)

        results: list[BulkMailActionItemResult] = []
        for interaction_id in interaction_ids:
            if request.action == "move" and not folder_ok:
                results.append(
                    BulkMailActionItemResult(
                        interaction_id=interaction_id,
                        status="failed",
                        reason=FOLDER_NOT_AVAILABLE,
                    )
                )
                continue
            results.append(await self._run_one(interaction_id, request, current_user))

        succeeded = sum(1 for r in results if r.status == "success")
        skipped = sum(1 for r in results if r.status == "skipped")
        return BulkMailActionResponse(
            requested=len(interaction_ids),
            succeeded=succeeded,
            failed=len(results) - succeeded - skipped,
            skipped=skipped,
            results=results,
        )

    async def _run_one(
        self,
        interaction_id: UUID,
        request: BulkMailActionRequest,
        current_user: User,
    ) -> BulkMailActionItemResult:
        try:
            async with self.db.begin_nested():
                ticket_id = await self._dispatch(interaction_id, request, current_user)
            return BulkMailActionItemResult(
                interaction_id=interaction_id, status="success", ticket_id=ticket_id
            )
        except HTTPException as exc:
            return BulkMailActionItemResult(
                interaction_id=interaction_id,
                status="failed",
                reason=_safe_reason(exc),
            )
        except Exception:
            logger.exception(
                "Bulk mail action %s failed for interaction %s",
                request.action,
                interaction_id,
            )
            return BulkMailActionItemResult(
                interaction_id=interaction_id,
                status="failed",
                reason=COULD_NOT_PROCESS,
            )

    async def _dispatch(
        self,
        interaction_id: UUID,
        request: BulkMailActionRequest,
        current_user: User,
    ) -> UUID | None:
        action = request.action

        if action in ("mark_read", "mark_unread"):
            await self._ensure_can_view(interaction_id, current_user)
            if action == "mark_read":
                await self.read_status_service.mark_read(interaction_id, current_user)
            else:
                await self.read_status_service.mark_unread(interaction_id, current_user)
            return None

        if action in ("flag", "unflag", "pin", "unpin"):
            await self._ensure_can_view(interaction_id, current_user)
            if action in ("flag", "unflag"):
                await self.message_mark_service.set_flag(
                    interaction_id, action == "flag", current_user
                )
            else:
                await self.message_mark_service.set_pin(
                    interaction_id, action == "pin", current_user
                )
            return None

        if action == "archive":
            await self.interaction_service.archive_interaction(
                interaction_id=interaction_id, current_user=current_user
            )
            return None

        if action == "move":
            await self.interaction_service.set_interaction_folder(
                interaction_id=interaction_id,
                request=FolderAssignRequest(folder_id=request.folder_id),
                current_user=current_user,
            )
            return None

        if action == "delete":
            interaction = await self._get_interaction(interaction_id)
            await self.interaction_service.hide_interaction(
                ticket_id=interaction.ticket_id,
                interaction_id=interaction_id,
                request=HideInteractionRequest(),
                current_user=current_user,
            )
            return None

        if action == "restore":
            interaction = await self._get_interaction(interaction_id)
            await self.interaction_service.restore_interaction(
                ticket_id=interaction.ticket_id,
                interaction_id=interaction_id,
                current_user=current_user,
            )
            return None

        if action == "create_ticket":
            interaction = await self._get_interaction(interaction_id)
            title = (interaction.subject or "").strip() or "(no subject)"
            response = await self.inbox_ticket_service.create_ticket_from_interaction(
                TicketFromInteractionCreate(
                    interaction_id=interaction_id,
                    title=title[:255],
                    ticket_type=request.ticket_type,
                    current_priority=request.current_priority,
                    agent_id=request.agent_id,
                ),
                current_user=current_user,
            )
            return response.ticket_id

        # link_ticket / attach_to_ticket — one existing workflow.
        await self._ensure_same_client(interaction_id, request.ticket_id)
        response = await self.inbox_ticket_service.attach_to_existing_ticket(
            ticket_id=request.ticket_id,
            request=AttachInteractionRequest(
                interaction_id=interaction_id,
                new_agent_id=request.new_agent_id,
                new_priority=request.new_priority,
            ),
            current_user=current_user,
        )
        return response.ticket_id

    # -----------------------------------------------------------------

    async def _get_interaction(self, interaction_id: UUID):
        interaction = await self.interaction_repository.get_by_id(interaction_id)
        if interaction is None:
            raise HTTPException(status_code=404, detail="Interaction not found.")
        return interaction

    async def _ensure_same_client(self, interaction_id: UUID, ticket_id: UUID) -> None:
        """
        A selection can span clients, and the single attach workflow only
        keeps clients apart through the UI (it lists that email's own
        client's tickets) — the API itself never compares them. Bulk has
        no such UI scoping, so each interaction is checked here: a mail
        that belongs to one client must never be attached to another
        client's ticket. Category-mailbox mail (no client) is left to the
        existing workflow, as it is for a single attach.
        """

        interaction = await self._get_interaction(interaction_id)
        if interaction.client_id is None:
            return
        ticket = await self.ticket_repository.get_by_id(ticket_id)
        if ticket is None:
            return  # the existing workflow raises its own 404
        ticket_client_id = ticket.client_company_id
        if ticket_client_id is not None and ticket_client_id != interaction.client_id:
            raise HTTPException(status_code=400, detail="Client mismatch.")

    async def _folder_is_usable(self, folder_id: UUID, current_user: User) -> bool:
        folder = await self.mail_folder_repository.get_by_id(folder_id)
        if folder is None:
            return False
        try:
            await MailFolderService(self.mail_folder_repository).ensure_visible(
                folder,
                current_user,
                self.rule_repository,
                self.distribution_list_repository,
            )
        except HTTPException:
            return False
        return True

    async def _ensure_can_view(self, interaction_id: UUID, current_user: User) -> None:
        """
        The single-item read/unread routes perform no authorization of
        their own. For bulk we require the same view access that opening
        the thread requires (mirrors OpenEmailService.get_email_details),
        so a selection can never mark mail the caller couldn't open.
        """

        interaction = await self._get_interaction(interaction_id)
        if interaction.parent_interaction_id is not None:
            root = await self.interaction_repository.find_thread_root(interaction_id)
            if root is not None:
                interaction = root

        if interaction.ticket_id is not None:
            ticket = await self.ticket_repository.get_by_id(interaction.ticket_id)
            if ticket is None:
                raise HTTPException(status_code=404, detail="Not found.")
            ensure_agent_can_view_ticket(ticket, current_user, view_only=True)
            if current_user.role.name == ACCOUNT_MANAGER_ROLE_NAME:
                await ensure_account_manager_owns_ticket_client(
                    ticket, current_user, self.client_repository
                )
            return

        is_forward_recipient, folder_shared_bypass = (
            await resolve_delegated_thread_access(
                interaction,
                current_user,
                interaction_repository=self.interaction_repository,
                mail_folder_repository=self.mail_folder_repository,
                rule_repository=self.rule_repository,
                distribution_list_repository=self.distribution_list_repository,
            )
        )
        await ensure_agent_can_view_pending_interaction(
            interaction,
            current_user,
            self.client_repository,
            view_only=True,
            folder_shared_bypass=folder_shared_bypass,
            is_forward_recipient=is_forward_recipient,
        )


def build_bulk_mail_action_service(db: AsyncSession) -> BulkMailActionService:
    """Same wiring the single-action routes use, built once per request."""

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    mail_folder_repository = MailFolderRepository(db)
    rule_repository = RuleRepository(db)
    distribution_list_repository = DistributionListRepository(db)
    notification_service = NotificationService(NotificationRepository(db))
    sla_service = build_sla_service(db, notification_service=notification_service)

    interaction_service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
        notification_service=notification_service,
        sla_service=sla_service,
        escalation_service=build_escalation_service(db),
        mail_folder_repository=mail_folder_repository,
        rule_repository=rule_repository,
        distribution_list_repository=distribution_list_repository,
    )

    inbox_ticket_service = InboxTicketService(
        ticket_repository=ticket_repository,
        interaction_repository=interaction_repository,
        assignment_service=AssignmentService(user_repository),
        sla_service=sla_service,
        client_repository=client_repository,
        notification_service=notification_service,
        interaction_service=interaction_service,
        mail_folder_repository=mail_folder_repository,
        rule_repository=rule_repository,
        distribution_list_repository=distribution_list_repository,
    )

    return BulkMailActionService(
        db,
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        client_repository=client_repository,
        mail_folder_repository=mail_folder_repository,
        rule_repository=rule_repository,
        distribution_list_repository=distribution_list_repository,
        read_status_service=MessageReadStatusService(
            interaction_repository, MessageReadReceiptRepository(db)
        ),
        message_mark_service=MessageMarkService(
            interaction_repository, MessageMarkRepository(db)
        ),
        interaction_service=interaction_service,
        inbox_ticket_service=inbox_ticket_service,
    )
