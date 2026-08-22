import logging
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService, NotificationType
from app.ticketing.enums.rule_enums import RuleActionType, RuleCategory
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.rule import Rule
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.schemas.rule import RuleActionItem, RuleConditionGroup
from app.ticketing.services.mail_provider import get_mail_provider_client
from app.ticketing.services.rule_conditions import RuleEmailContext, rule_matches
from app.ticketing.services.rule_folder_sync import ensure_folder

logger = logging.getLogger(__name__)


class RuleEngineService:
    """
    Evaluates every enabled Mail/OTP Rule against one just-received
    email and executes the matching rules' actions, in the fixed
    pipeline the product spec describes: all enabled Mail Rules (by
    priority) first, then all enabled OTP Rules (by priority) — never
    interleaved. "Stop processing more rules" halts this entire
    pipeline for this email (Outlook's own semantic — it stops
    everything for the message, not just the rest of one category),
    not just the rest of the current category.

    Runs inline, in the same DB session/transaction as
    EmailService.receive_email that calls it — the actions here are a
    handful of cheap, idempotent writes (ensure-folder-exists,
    file-into-folder) plus a real outbound send for "Forward To";
    unlike a ticket-mutating rules engine, there's no multi-step
    consequence here that would justify deferring evaluation itself
    the way notification emails are deferred.
    """

    def __init__(
        self,
        rule_repository: RuleRepository,
        mail_folder_repository: MailFolderRepository,
        interaction_repository: InteractionRepository,
        user_repository: UserRepository,
        notification_service: NotificationService,
    ):
        self.rule_repository = rule_repository
        self.mail_folder_repository = mail_folder_repository
        self.interaction_repository = interaction_repository
        self.user_repository = user_repository
        self.notification_service = notification_service

    async def evaluate_and_execute_for_email(
        self,
        *,
        interaction: Interaction,
        context: RuleEmailContext,
    ) -> bool:
        """
        Returns whether an OTP Rule recognized this email (matched),
        regardless of whether its forward_to action's send later
        succeeds or fails. Informational/logging only today —
        EmailService.receive_email no longer uses this return value to
        stop the interaction's Response SLA clock; that decision is
        now made independently by the semantic classifier in
        app.ticketing.services.otp_classifier, precisely so SLA
        completion never depends on whether an OTP Rule is configured
        or matches.
        """

        rules = await self.rule_repository.list_enabled_ordered()
        otp_recognized = False

        for rule in rules:
            try:
                conditions = RuleConditionGroup.model_validate(rule.conditions)
                exceptions = RuleConditionGroup.model_validate(rule.exceptions)
            except Exception:
                logger.exception(
                    "Rule %s (%s) has a malformed condition/exception tree — skipping.",
                    rule.rule_id,
                    rule.name,
                )
                continue

            if not rule_matches(conditions, exceptions, context):
                continue

            if rule.category == RuleCategory.OTP_RULE:
                otp_recognized = True

            logger.info(
                "Rule %r (%s) matched interaction %s",
                rule.name,
                rule.category,
                interaction.interaction_id,
            )

            for raw_action in rule.actions:
                try:
                    action = RuleActionItem.model_validate(raw_action)
                    await self._execute_action(action, interaction=interaction, rule=rule)
                except Exception:
                    # One action failing (e.g. a stale employee id)
                    # never blocks the rest of this rule's actions, or
                    # any other rule — matches the SLA sweep's own
                    # per-item isolation convention.
                    logger.exception(
                        "Rule %r action %r failed on interaction %s — continuing.",
                        rule.name,
                        raw_action.get("type") if isinstance(raw_action, dict) else raw_action,
                        interaction.interaction_id,
                    )

            if rule.stop_processing:
                logger.info(
                    "Rule %r has 'Stop processing more rules' enabled — "
                    "halting rule evaluation for this email.",
                    rule.name,
                )
                return otp_recognized

        return otp_recognized

    async def _execute_action(
        self, action: RuleActionItem, *, interaction: Interaction, rule: Rule
    ) -> None:
        # Folder creation is normally already done eagerly by
        # RuleService.create/update the moment the rule was saved —
        # this call is a safety net (idempotent get-or-create, via the
        # same shared helper) for a rule saved before that eager path
        # existed, or a folder deleted after the rule that names it
        # was saved. It's never the primary path in the common case.
        if action.type == RuleActionType.CREATE_FOLDER:
            await ensure_folder(
                action.folder_name,
                created_by=rule.created_by,
                mail_folder_repository=self.mail_folder_repository,
            )

        elif action.type == RuleActionType.MOVE_TO_FOLDER:
            folder = await ensure_folder(
                action.folder_name,
                created_by=rule.created_by,
                mail_folder_repository=self.mail_folder_repository,
            )
            await self.interaction_repository.set_folder(interaction, folder.folder_id)

        elif action.type == RuleActionType.FORWARD_TO:
            await self._forward_to_employees(
                action.employee_user_ids or [],
                interaction=interaction,
                rule_category=rule.category,
            )

    async def _forward_to_employees(
        self,
        employee_user_ids: list[UUID],
        *,
        interaction: Interaction,
        rule_category: str,
    ) -> None:
        """
        Shared by OTP Rules and Mail Rules alike (`rule_category`
        selects only the notification title/type below) — two
        distinct, complementary effects, not one or the other: a real
        outbound send via the same Microsoft Graph mailbox every
        other outbound path in this app already sends through (so
        the forward genuinely lands in the recipient's real Outlook
        inbox, not just a log line — the plain EmailSender/SMTP seam
        this used to go through is a no-op with no SMTP host
        configured, which this app's dev environment never has), plus
        an in-app Notification so the forward is also visible inside
        this app (for OTP specifically, merged into the recipient's
        own Inbox — see unified-frontend's SYSTEM_NOTIFICATION_TYPES/
        otpNotificationToInboxItem) for whoever it was sent to, not
        just their external inbox.
        """

        emails_by_id = await self.user_repository.get_active_emails_by_ids(employee_user_ids)

        if not emails_by_id:
            logger.warning(
                "%s forward_to rule matched interaction %s but none of the "
                "selected employees resolved to an active user — nothing sent.",
                rule_category,
                interaction.interaction_id,
            )
            return

        payload = interaction.payload or {}
        subject = payload.get("subject") or "(no subject)"
        body = payload.get("body") or ""
        from_email = payload.get("from_email") or "unknown sender"

        forward_subject = f"FW: {subject}"
        forward_body = (
            "---------- Forwarded message ----------\n"
            f"From: {from_email}\n"
            f"Subject: {subject}\n\n"
            f"{body}"
        )

        # Deferred import — email_service.py imports this module (for
        # the rule-evaluation hook inside receive_email), so a
        # module-level import the other way would be circular. Same
        # pattern mail_provider.py's own get_mail_provider_client()
        # already uses for graph_client/graph_auth.
        from app.ticketing.services.email_service import resolve_shared_mailbox_address

        settings = get_settings()
        mailbox_address = resolve_shared_mailbox_address(settings)
        mail_provider = get_mail_provider_client(settings)
        message_domain = mailbox_address.split("@", 1)[-1] or "probeps.com"

        for user_id, recipient_email in emails_by_id.items():
            envelope = OutboundEnvelope(
                from_email=mailbox_address,
                to_email=recipient_email,
                subject=forward_subject,
                message_id=f"<rule-forward-{uuid4().hex}@{message_domain}>",
                body=forward_body,
            )
            try:
                await mail_provider.send_email(envelope)
                logger.info(
                    "RULE_FORWARD_SENT category=%s user_id=%s to=%s subject=%r",
                    rule_category,
                    user_id,
                    recipient_email,
                    forward_subject,
                )
            except Exception:
                logger.exception(
                    "RULE_FORWARD_FAILED category=%s user_id=%s to=%s subject=%r",
                    rule_category,
                    user_id,
                    recipient_email,
                    forward_subject,
                )

        # The full forwarded text (same content the real email above
        # carries, headers included) — not a truncated snippet.
        # Notification.message is an unbounded Text column specifically
        # so this never needs capping the way title (String(255)) does.
        #
        # Only the notification label distinguishes an OTP Rule's
        # forward from a Mail Rule's — OTP's own copy/type is
        # untouched from before this branch existed.
        if rule_category == RuleCategory.OTP_RULE:
            notification_type = NotificationType.OTP_FORWARDED
            title = f"OTP forwarded: {subject}"
        else:
            notification_type = NotificationType.MAIL_RULE_FORWARDED
            title = f"Mail forwarded: {subject}"

        await self.notification_service.notify(
            set(emails_by_id.keys()),
            notification_type,
            title=title,
            message=forward_body,
        )


def build_rule_engine_service(db: AsyncSession) -> RuleEngineService:
    """
    Convenience factory mirroring build_sla_service — every mail-intake
    call site (EmailService's three construction sites, plus tests)
    constructs one of these rather than hand-assembling five
    repositories/services inline at each.
    """

    return RuleEngineService(
        rule_repository=RuleRepository(db),
        mail_folder_repository=MailFolderRepository(db),
        interaction_repository=InteractionRepository(db),
        user_repository=UserRepository(db),
        notification_service=NotificationService(NotificationRepository(db)),
    )
