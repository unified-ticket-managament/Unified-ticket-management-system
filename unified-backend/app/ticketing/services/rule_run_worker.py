"""
Background processing for "Run rule now" — driven by
app.core.rule_run_scheduler (an APScheduler interval job, the same
in-process architecture as the SLA sweep; there is no separate queue).

One tick claims one run and works through it page by page until it
finishes or the tick's time budget runs out; the next tick resumes it.
A run is safe to resume anywhere: the cursor is persisted only after a
whole page, and every per-email effect is idempotent (rule_run_items
records what was already done, move_to_folder never re-files, forward_to
is at-most-once).

Per email, the run:
  1. rebuilds the RuleEmailContext from the stored Interaction with the
     same builder intake uses (build_rule_email_context);
  2. skips it if a higher-priority stop_processing rule from the
     trigger-time snapshot matches (the live pipeline would never reach
     this rule);
  3. evaluates the snapshotted conditions/exceptions (rule_matches);
  4. for each action, requires BOTH the rule owner and the triggering
     user to pass the manual-action gate on the thread root
     (RunScopeGate) — out-of-scope mail is skipped, never touched;
  5. executes the action through the live engine's own dispatcher
     (RuleEngineService._execute_action, with a RunNowActionContext).
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, tuple_, update
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.impersonation_context import set_impersonator
from app.rbac.repositories.audit_log_repository import AuditLogRepository as RbacAuditLogRepository
from app.rbac.schemas.audit_log import AuditLogCreate as RbacAuditLogCreate
from app.rbac.services.audit_log_service import AuditLogService as RbacAuditLogService
from app.ticketing.enums import InteractionDirection
from app.ticketing.enums.rule_enums import RuleActionType
from app.ticketing.models.attachment import Attachment
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.rule import Rule
from app.ticketing.models.rule_run import (
    RuleRun,
    RuleRunItem,
    RuleRunItemStatus,
    RuleRunPhase,
    RuleRunStatus,
)
from app.ticketing.repositories.distribution_list_repository import DistributionListRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.schemas.rule import RuleActionItem, RuleConditionGroup
from app.ticketing.services.access_control import has_permission
from app.ticketing.services.otp_classifier import classify_otp_email
from app.ticketing.services.rule_access import can_manage_rule
from app.ticketing.services.rule_conditions import build_rule_email_context, rule_matches
from app.ticketing.services.rule_engine_service import (
    RULE_FORWARD_LOCK_NAMESPACE,
    RunNowActionContext,
    build_rule_engine_service,
)
from app.ticketing.services.rule_folder_sync import ensure_folder
from app.ticketing.services.rule_run_authorization import (
    RunScopeGate,
    build_scope_prefilter,
    can_use_folder_for_run,
    load_authorized_user,
)
from app.ticketing.services.rule_run_service import HISTORICAL_FORWARD_CAP

logger = logging.getLogger(__name__)

PAGE_SIZE = 200
MAX_ERROR_SAMPLES = 50
# Infrastructure-level (whole-page) failures retried from the saved
# cursor before the run is marked failed.
MAX_INFRA_ATTEMPTS = 5
# A running run whose heartbeat is older than this is considered
# orphaned (process restart/crash) and may be re-claimed.
STALE_HEARTBEAT = timedelta(minutes=2)
# Reconciliation: once the main scan is done and this long has passed
# since cutoff_at, re-scan the RECONCILE_WINDOW before cutoff_at once,
# to catch an intake transaction that began before the rule was
# committed (so the live engine didn't see the rule) but committed after
# the main scan had already passed its created_at. Idempotent.
RECONCILE_GRACE = timedelta(seconds=60)
RECONCILE_WINDOW = timedelta(minutes=5)

RULE_MANAGE_PERMISSION = "rule:manage"

# Authorization (rule still enabled, both users still active and
# authorized, folder access, scope) is re-checked from the database at
# the start of every tick and at least this often while a tick runs —
# never trusted from trigger time. Bounded rather than per-page because
# each re-check is ~a dozen round trips.
REVALIDATE_INTERVAL_SECONDS = 30.0

_NIL_UUID = UUID(int=0)

_RULE_FORWARD_SESSION_LOCK_SQL = text("SELECT pg_advisory_lock(:ns, hashtext(:key))")
_RULE_FORWARD_SESSION_UNLOCK_SQL = text("SELECT pg_advisory_unlock(:ns, hashtext(:key))")


class _InfrastructureError(Exception):
    """A failure of the run's own machinery, not of one email."""


class _StopRun(Exception):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _is_infrastructure_error(exc: BaseException) -> bool:
    if isinstance(exc, (OperationalError, InterfaceError)):
        return True
    return isinstance(exc, DBAPIError) and bool(getattr(exc, "connection_invalidated", False))


@dataclass
class _RunState:
    """
    In-memory copy of the run row's mutable fields. Persisted with an
    explicit UPDATE (never through the ORM object), because per-email
    rollbacks expire every ORM instance in the session.
    """

    run_id: UUID
    rule_id: UUID | None
    rule_owner_id: UUID | None
    triggered_by: UUID
    impersonator_id: UUID | None
    impersonator_name: str | None
    rule_snapshot: dict
    precedence_snapshot: list
    cutoff_at: datetime
    phase: str
    cursor_created_at: datetime | None
    cursor_interaction_id: UUID | None
    attempts: int
    counts: dict = field(default_factory=dict)
    skipped_by_reason: dict = field(default_factory=dict)
    error_samples: list = field(default_factory=list)

    COUNT_FIELDS = (
        "scanned_count",
        "matched_count",
        "succeeded_count",
        "already_applied_count",
        "skipped_count",
        "failed_count",
        "forwards_sent_count",
    )

    @classmethod
    def from_run(cls, run: RuleRun) -> "_RunState":
        return cls(
            run_id=run.run_id,
            rule_id=run.rule_id,
            rule_owner_id=run.rule_owner_id,
            triggered_by=run.triggered_by,
            impersonator_id=run.impersonator_id,
            impersonator_name=run.impersonator_name,
            rule_snapshot=run.rule_snapshot,
            precedence_snapshot=run.precedence_snapshot or [],
            cutoff_at=run.cutoff_at,
            phase=run.phase,
            cursor_created_at=run.cursor_created_at,
            cursor_interaction_id=run.cursor_interaction_id,
            attempts=run.attempts,
            counts={name: getattr(run, name) or 0 for name in cls.COUNT_FIELDS},
            skipped_by_reason=dict(run.skipped_by_reason or {}),
            error_samples=list(run.error_samples or []),
        )

    def bump(self, name: str, by: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + by

    def skip(self, reason: str) -> None:
        self.skipped_by_reason[reason] = self.skipped_by_reason.get(reason, 0) + 1

    def record_error(self, interaction_id: UUID | None, action: str | None, error: str) -> None:
        if len(self.error_samples) < MAX_ERROR_SAMPLES:
            self.error_samples.append(
                {
                    "interaction_id": str(interaction_id) if interaction_id else None,
                    "action": action,
                    "error": error[:500],
                }
            )

    def persisted_values(self) -> dict:
        return {
            **self.counts,
            "phase": self.phase,
            "cursor_created_at": self.cursor_created_at,
            "cursor_interaction_id": self.cursor_interaction_id,
            "skipped_by_reason": self.skipped_by_reason,
            "error_samples": self.error_samples,
            "attempts": self.attempts,
            "heartbeat_at": datetime.now(timezone.utc),
        }


@dataclass
class _PageContext:
    gate: RunScopeGate
    prefilter: dict
    # action index -> skip reason, for folder actions whose target folder
    # either user may not use (see can_use_folder_for_run).
    blocked_actions: dict[int, str]


_EMAIL_OUTCOME_PRIORITY = ("failed", "succeeded", "already_applied", "skipped")


class RuleRunProcessor:
    def __init__(
        self,
        db: AsyncSession,
        run: RuleRun,
        *,
        page_size: int | None = None,
        forward_cap: int | None = None,
    ):
        self.db = db
        self.state = _RunState.from_run(run)
        # Resolved at construction (not as default args) so the module
        # constants stay the single tunable source.
        self.page_size = page_size or PAGE_SIZE
        self.forward_cap = forward_cap if forward_cap is not None else HISTORICAL_FORWARD_CAP
        self.engine = build_rule_engine_service(db)
        self.interaction_repository = InteractionRepository(db)
        self.snapshot_rule = SimpleNamespace(
            rule_id=UUID(self.state.rule_snapshot["rule_id"]),
            name=self.state.rule_snapshot["name"],
            category=self.state.rule_snapshot["category"],
            created_by=(
                UUID(self.state.rule_snapshot["created_by"])
                if self.state.rule_snapshot.get("created_by")
                else None
            ),
        )
        self.conditions = RuleConditionGroup.model_validate(self.state.rule_snapshot["conditions"])
        self.exceptions = RuleConditionGroup.model_validate(self.state.rule_snapshot["exceptions"])
        self.precedence = []
        for entry in self.state.precedence_snapshot:
            try:
                self.precedence.append(
                    (
                        RuleConditionGroup.model_validate(entry["conditions"]),
                        RuleConditionGroup.model_validate(entry["exceptions"]),
                    )
                )
            except Exception:
                # Same as the live pipeline: a malformed rule is skipped,
                # never treated as a match.
                logger.warning(
                    "RULE_RUN_PRECEDENCE_RULE_MALFORMED run_id=%s rule_id=%s",
                    self.state.run_id,
                    entry.get("rule_id"),
                )
        self.otp_threshold = get_settings().otp_nlp_confidence_threshold
        # rule_run_items rows this processor created — see _process_row's
        # `reconciling` flag.
        self._new_items = 0
        self._page_context: _PageContext | None = None
        self._validated_at: float | None = None

    # ------------------------------------------------------------------
    # Driving loop
    # ------------------------------------------------------------------

    async def process(self, *, deadline: float) -> str:
        """
        Works the run until it finishes, has to wait (reconciliation
        grace period), or `deadline` (time.monotonic()) passes. Returns
        "finished", "wait" or "continue".
        """

        set_impersonator(self.state.impersonator_id, self.state.impersonator_name)
        try:
            while time.monotonic() < deadline:
                try:
                    outcome = await self._step()
                except _StopRun as stop:
                    await self._finish(stop.status, stop.reason)
                    return "finished"
                except Exception as exc:
                    await self._handle_infrastructure_failure(exc)
                    return "finished" if self.state.attempts > MAX_INFRA_ATTEMPTS else "wait"
                if outcome != "continue":
                    return outcome
            return "continue"
        finally:
            set_impersonator(None, None)

    async def _step(self) -> str:
        now = time.monotonic()
        if (
            self._page_context is None
            or self._validated_at is None
            or now - self._validated_at >= REVALIDATE_INTERVAL_SECONDS
        ):
            self._page_context = await self._revalidate()
            self._validated_at = time.monotonic()
        page = self._page_context

        if self.state.phase == RuleRunPhase.SCAN:
            rows = await self._fetch_page(page, lower_bound=None)
            if not rows:
                self.state.phase = RuleRunPhase.RECONCILE
                self.state.cursor_created_at = self.state.cutoff_at - RECONCILE_WINDOW
                self.state.cursor_interaction_id = _NIL_UUID
                await self._persist()
                return "continue"
            await self._process_page(rows, page, count_scanned=True)
            return "continue"

        if self.state.phase == RuleRunPhase.RECONCILE:
            if datetime.now(timezone.utc) < self.state.cutoff_at + RECONCILE_GRACE:
                await self._persist()
                return "wait"
            rows = await self._fetch_page(page, lower_bound=self.state.cutoff_at - RECONCILE_WINDOW)
            if not rows:
                self.state.phase = RuleRunPhase.DONE
                await self._finish(RuleRunStatus.COMPLETED, None)
                return "finished"
            await self._process_page(rows, page, count_scanned=False)
            return "continue"

        await self._finish(RuleRunStatus.COMPLETED, None)
        return "finished"

    # ------------------------------------------------------------------
    # Revalidation (never trust trigger-time authorization) — see
    # REVALIDATE_INTERVAL_SECONDS
    # ------------------------------------------------------------------

    async def _revalidate(self) -> _PageContext:
        rule = None
        if self.state.rule_id is not None:
            rule = await self.db.get(Rule, self.state.rule_id, populate_existing=True)
        if rule is None:
            raise _StopRun(RuleRunStatus.CANCELLED, "rule_deleted")
        if not rule.is_enabled:
            raise _StopRun(RuleRunStatus.CANCELLED, "rule_disabled")

        owner = await load_authorized_user(self.db, self.state.rule_owner_id)
        if owner is None:
            raise _StopRun(RuleRunStatus.CANCELLED, "rule_owner_inactive")

        trigger = await load_authorized_user(self.db, self.state.triggered_by)
        if trigger is None:
            raise _StopRun(RuleRunStatus.CANCELLED, "triggering_user_inactive")

        trigger_dl_ids = await DistributionListRepository(self.db).list_active_list_ids_for_user(
            trigger.user_id
        )
        if not has_permission(trigger, RULE_MANAGE_PERMISSION) or not can_manage_rule(
            rule, trigger, trigger_dl_ids
        ):
            raise _StopRun(RuleRunStatus.CANCELLED, "triggering_user_unauthorized")

        gate = RunScopeGate(owner=owner, trigger=trigger, db=self.db)
        prefilter = await build_scope_prefilter(self.db, gate.users)

        blocked: dict[int, str] = {}
        owner_dl_ids = await DistributionListRepository(self.db).list_active_list_ids_for_user(
            owner.user_id
        )
        mail_folder_repository = MailFolderRepository(self.db)
        for index, raw_action in enumerate(self.state.rule_snapshot.get("actions") or []):
            if not isinstance(raw_action, dict):
                continue
            if raw_action.get("type") not in (
                RuleActionType.CREATE_FOLDER,
                RuleActionType.MOVE_TO_FOLDER,
            ):
                continue
            name = (raw_action.get("folder_name") or "").strip()
            folder = await mail_folder_repository.get_by_name(name) if name else None
            for user, dl_ids in ((owner, owner_dl_ids), (trigger, trigger_dl_ids)):
                if not await can_use_folder_for_run(
                    self.db,
                    folder=folder,
                    user=user,
                    target_rule_id=self.snapshot_rule.rule_id,
                    user_distribution_list_ids=dl_ids,
                ):
                    blocked[index] = "folder_unauthorized"
                    break
            if index not in blocked and raw_action.get("type") == RuleActionType.CREATE_FOLDER:
                # create_folder has no per-email effect: the run performs
                # it once here, with the same get-or-create the live
                # engine and RuleService use.
                await ensure_folder(
                    name,
                    created_by=self.snapshot_rule.created_by,
                    mail_folder_repository=mail_folder_repository,
                )
        await self.db.commit()

        return _PageContext(gate=gate, prefilter=prefilter, blocked_actions=blocked)

    # ------------------------------------------------------------------
    # Candidate scan
    # ------------------------------------------------------------------

    async def _fetch_page(self, page: _PageContext, *, lower_bound: datetime | None):
        """
        Next keyset page of eligible inbound mail, (created_at,
        interaction_id) ascending, strictly after the cursor and never
        after cutoff_at. Only the payload keys the conditions read are
        selected — never html_body or the full payload. Narrowed by the
        scope prefilter (a superset of what the gate admits); the gate
        still decides every row.
        """

        pf = page.prefilter
        root = pf["root"]

        query = (
            select(
                Interaction.interaction_id,
                Interaction.created_at,
                Interaction.client_id,
                Interaction.payload["from_email"].astext.label("from_email"),
                Interaction.payload["subject"].astext.label("subject"),
                Interaction.payload["body"].astext.label("body"),
                Interaction.payload["cc"].label("cc"),
            )
            .join(
                root,
                root.interaction_id
                == func.coalesce(Interaction.parent_interaction_id, Interaction.interaction_id),
            )
            .outerjoin(pf["root_client"], pf["root_client"].client_id == root.client_id)
            .outerjoin(pf["root_ticket"], pf["root_ticket"].ticket_id == root.ticket_id)
            .outerjoin(
                pf["ticket_client"],
                pf["ticket_client"].client_id == pf["root_ticket"].client_company_id,
            )
            .where(
                Interaction.interaction_type == "EMAIL",
                Interaction.direction == InteractionDirection.INBOUND,
                Interaction.is_bounce.is_(False),
                Interaction.is_draft.is_(False),
                Interaction.is_visible.is_(True),
                Interaction.created_at <= self.state.cutoff_at,
                *pf["clauses"],
            )
            .order_by(Interaction.created_at.asc(), Interaction.interaction_id.asc())
            .limit(self.page_size)
        )

        if self.state.cursor_created_at is not None:
            query = query.where(
                tuple_(Interaction.created_at, Interaction.interaction_id)
                > tuple_(
                    self.state.cursor_created_at,
                    self.state.cursor_interaction_id or _NIL_UUID,
                )
            )
        elif lower_bound is not None:
            query = query.where(Interaction.created_at >= lower_bound)

        result = await self.db.execute(query)
        return result.all()

    async def _attachments_for(self, interaction_ids: list[UUID]) -> dict[UUID, list]:
        if not interaction_ids:
            return {}
        result = await self.db.execute(
            select(Attachment.interaction_id, Attachment.filename, Attachment.mime_type).where(
                Attachment.interaction_id.in_(interaction_ids)
            )
        )
        by_id: dict[UUID, list] = {}
        for interaction_id, filename, mime_type in result.all():
            by_id.setdefault(interaction_id, []).append((filename or "", mime_type))
        return by_id

    # ------------------------------------------------------------------
    # Page / email processing
    # ------------------------------------------------------------------

    async def _process_page(self, rows, page: _PageContext, *, count_scanned: bool) -> None:
        attachments = await self._attachments_for([row.interaction_id for row in rows])

        for row in rows:
            if count_scanned:
                self.state.bump("scanned_count")
            await self._process_row(
                row, attachments.get(row.interaction_id, []), page, reconciling=not count_scanned
            )

        last = rows[-1]
        self.state.cursor_created_at = last.created_at
        self.state.cursor_interaction_id = last.interaction_id
        await self._persist()

    async def _process_row(
        self, row, attachments: list, page: _PageContext, *, reconciling: bool = False
    ) -> None:
        """
        `reconciling`: the reconciliation pass re-visits rows the main
        scan may already have handled, so it only counts an email when it
        produced a new rule_run_items row (i.e. was genuinely missed).
        """

        try:
            cc = row.cc if isinstance(row.cc, list) else []
            context = build_rule_email_context(
                from_email=row.from_email,
                subject=row.subject,
                body=row.body,
                client_id=row.client_id,
                cc=[addr for addr in cc if isinstance(addr, str)],
                attachments=attachments,
                otp_detected=classify_otp_email(
                    row.subject, row.body, threshold=self.otp_threshold
                ).is_otp,
            )
            if not rule_matches(self.conditions, self.exceptions, context):
                return
        except Exception as exc:
            if _is_infrastructure_error(exc):
                raise
            logger.exception(
                "RULE_RUN_ITEM_FAILED run_id=%s interaction_id=%s stage=evaluate",
                self.state.run_id,
                row.interaction_id,
            )
            if not reconciling:
                self.state.bump("matched_count")
                self.state.bump("failed_count")
                self.state.record_error(row.interaction_id, None, f"evaluate: {exc!r}")
            return

        if any(rule_matches(c, e, context) for c, e in self.precedence):
            if not reconciling:
                self.state.bump("matched_count")
                self.state.bump("skipped_count")
                self.state.skip("stopped_by_higher_priority_rule")
            return

        new_items_before = self._new_items
        try:
            outcome = await self._process_matched(row.interaction_id, page)
        except _StopRun:
            raise
        except Exception as exc:
            if _is_infrastructure_error(exc):
                raise
            await self.db.rollback()
            logger.exception(
                "RULE_RUN_ITEM_FAILED run_id=%s interaction_id=%s stage=actions",
                self.state.run_id,
                row.interaction_id,
            )
            self.state.record_error(row.interaction_id, None, f"actions: {exc!r}")
            outcome = "failed"

        if reconciling and self._new_items == new_items_before:
            return
        self.state.bump("matched_count")
        self.state.bump(f"{outcome}_count")

    async def _process_matched(self, interaction_id: UUID, page: _PageContext) -> str:
        interaction = await self.db.get(Interaction, interaction_id, populate_existing=True)
        if interaction is None or not interaction.is_visible:
            self.state.skip("no_longer_eligible")
            return "skipped"

        root = await self.interaction_repository.find_thread_root(interaction_id) or interaction

        existing_items = {
            item.action_index: item
            for item in (
                await self.db.execute(
                    select(RuleRunItem).where(
                        RuleRunItem.run_id == self.state.run_id,
                        RuleRunItem.interaction_id == interaction_id,
                    )
                )
            ).scalars().all()
        }

        statuses: list[str] = []
        for index, raw_action in enumerate(self.state.rule_snapshot.get("actions") or []):
            statuses.append(
                await self._process_action(
                    index, raw_action, interaction, root, page, existing_items.get(index)
                )
            )

        for outcome in _EMAIL_OUTCOME_PRIORITY:
            if outcome in statuses:
                return outcome
        return "already_applied"

    async def _process_action(
        self,
        index: int,
        raw_action,
        interaction: Interaction,
        root: Interaction,
        page: _PageContext,
        existing: RuleRunItem | None,
    ) -> str:
        action_type = raw_action.get("type") if isinstance(raw_action, dict) else None

        # Resume / reconciliation: this action was already handled for
        # this email by this run — never repeat it.
        if existing is not None:
            if existing.status == RuleRunItemStatus.SENDING:
                existing.status = RuleRunItemStatus.UNKNOWN
                existing.error = "Run resumed with this forward still marked sending; not re-sent."
                await self.db.commit()
                self.state.skip("send_state_unknown")
                return "failed"
            return _item_status_to_outcome(existing.status)

        try:
            action = RuleActionItem.model_validate(raw_action)
        except Exception as exc:
            await self._record_item(
                interaction, index, str(action_type), RuleRunItemStatus.FAILED,
                error=f"invalid action: {exc!r}",
            )
            self.state.record_error(interaction.interaction_id, str(action_type), repr(exc))
            return "failed"

        if action.type == RuleActionType.CREATE_FOLDER:
            # Done once per page in _revalidate (no per-email effect).
            if index in page.blocked_actions:
                self.state.skip(page.blocked_actions[index])
                return "skipped"
            return "already_applied"

        if index in page.blocked_actions:
            reason = page.blocked_actions[index]
            await self._record_item(
                interaction, index, action.type, RuleRunItemStatus.SKIPPED, skip_reason=reason
            )
            self.state.skip(reason)
            return "skipped"

        if not await page.gate.allows(action_type=action.type, root=root):
            await self._record_item(
                interaction, index, action.type, RuleRunItemStatus.SKIPPED, skip_reason="out_of_scope"
            )
            self.state.skip("out_of_scope")
            return "skipped"

        if action.type == RuleActionType.MOVE_TO_FOLDER:
            return await self._run_move(index, action, interaction)

        if action.type == RuleActionType.FORWARD_TO:
            return await self._run_forward(index, action, interaction)

        return "skipped"

    async def _run_move(self, index: int, action: RuleActionItem, interaction: Interaction) -> str:
        ctx = RunNowActionContext(run_id=self.state.run_id, triggered_by=self.state.triggered_by)
        try:
            async with self.db.begin_nested():
                await self.engine._execute_action(
                    action, interaction=interaction, rule=self.snapshot_rule, run_now=ctx
                )
        except Exception as exc:
            if _is_infrastructure_error(exc):
                raise
            logger.exception(
                "RULE_RUN_ITEM_FAILED run_id=%s interaction_id=%s action=move_to_folder",
                self.state.run_id,
                interaction.interaction_id,
            )
            await self._record_item(
                interaction, index, action.type, RuleRunItemStatus.FAILED, error=repr(exc)
            )
            self.state.record_error(interaction.interaction_id, action.type, repr(exc))
            return "failed"

        status = ctx.outcome.get("status", RuleRunItemStatus.FAILED)
        skip_reason = ctx.outcome.get("skip_reason")
        await self._record_item(
            interaction,
            index,
            action.type,
            status,
            skip_reason=skip_reason,
            result={"folder_id": _str(ctx.outcome.get("folder_id"))},
        )
        if skip_reason:
            self.state.skip(skip_reason)
        return _item_status_to_outcome(status)

    async def _prior_unresolved_forward(self, interaction_id: UUID) -> bool:
        result = await self.db.execute(
            select(RuleRunItem.item_id).where(
                RuleRunItem.interaction_id == interaction_id,
                RuleRunItem.action_type == RuleActionType.FORWARD_TO,
                RuleRunItem.status.in_((RuleRunItemStatus.SENDING, RuleRunItemStatus.UNKNOWN)),
            ).limit(1)
        )
        return result.first() is not None

    async def _run_forward(self, index: int, action: RuleActionItem, interaction: Interaction) -> str:
        if self.state.counts.get("forwards_sent_count", 0) >= self.forward_cap:
            raise _StopRun(
                RuleRunStatus.CAPPED,
                f"Stopped at the safety limit of {self.forward_cap} historical forwards.",
            )

        if await self._prior_unresolved_forward(interaction.interaction_id):
            await self._record_item(
                interaction, index, action.type, RuleRunItemStatus.SKIPPED,
                skip_reason="prior_send_state_unknown",
            )
            self.state.skip("prior_send_state_unknown")
            return "skipped"

        lock_key = {"ns": RULE_FORWARD_LOCK_NAMESPACE, "key": str(interaction.interaction_id)}
        sending_item_id: list[UUID] = []

        async def _mark_sending(recipient_user_ids: list[UUID]) -> None:
            # Durably record intent BEFORE the first external send — the
            # at-most-once guarantee hinges on this commit.
            item = RuleRunItem(
                run_id=self.state.run_id,
                interaction_id=interaction.interaction_id,
                rule_id=self.snapshot_rule.rule_id,
                action_index=index,
                action_type=action.type,
                status=RuleRunItemStatus.SENDING,
                result={"recipient_user_ids": [str(u) for u in recipient_user_ids]},
            )
            self.db.add(item)
            await self.db.commit()
            self._new_items += 1
            sending_item_id.append(item.item_id)

        ctx = RunNowActionContext(
            run_id=self.state.run_id,
            triggered_by=self.state.triggered_by,
            before_forward_send=_mark_sending,
        )

        # A session-level advisory lock on its own connection, so it
        # survives the SENDING commit above (a transaction-scoped lock
        # would be released by it) — the live engine takes the same key
        # transaction-scoped, so the two paths can't both pass dedup.
        async with self.db.bind.connect() as lock_conn:
            await lock_conn.execute(_RULE_FORWARD_SESSION_LOCK_SQL, lock_key)
            await lock_conn.commit()
            try:
                return await self._forward_locked(index, action, interaction, ctx, sending_item_id)
            finally:
                try:
                    await lock_conn.execute(_RULE_FORWARD_SESSION_UNLOCK_SQL, lock_key)
                    await lock_conn.commit()
                except Exception:
                    # Never return a connection still holding the lock
                    # to the pool.
                    await lock_conn.invalidate()

    async def _forward_locked(
        self,
        index: int,
        action: RuleActionItem,
        interaction: Interaction,
        ctx: RunNowActionContext,
        sending_item_id: list[UUID],
    ) -> str:
        try:
            await self.engine._execute_action(
                action, interaction=interaction, rule=self.snapshot_rule, run_now=ctx
            )
            await self.db.flush()
        except Exception as exc:
            infra = _is_infrastructure_error(exc)
            await self.db.rollback()
            logger.exception(
                "RULE_RUN_ITEM_FAILED run_id=%s interaction_id=%s action=forward_to sending=%s",
                self.state.run_id,
                interaction.interaction_id,
                bool(sending_item_id),
            )
            if sending_item_id:
                # The external send may already have happened — never
                # resend; leave it visible for review instead.
                await self.db.execute(
                    update(RuleRunItem)
                    .where(RuleRunItem.item_id == sending_item_id[0])
                    .values(status=RuleRunItemStatus.UNKNOWN, error=repr(exc)[:2000])
                )
                await self.db.commit()
                self.state.skip("send_state_unknown")
            else:
                await self._record_item(
                    interaction, index, action.type, RuleRunItemStatus.FAILED, error=repr(exc)
                )
            self.state.record_error(interaction.interaction_id, action.type, repr(exc))
            if infra:
                raise
            return "failed"

        outcome = ctx.outcome
        status = outcome.get("status", RuleRunItemStatus.FAILED)
        result = {
            "sent_user_ids": [_str(u) for u in outcome.get("sent_user_ids", [])],
            "failed_user_ids": [_str(u) for u in outcome.get("failed_user_ids", [])],
            "skipped_duplicate_user_ids": [
                _str(u) for u in outcome.get("skipped_duplicate_user_ids", [])
            ],
        }

        if sending_item_id:
            await self.db.execute(
                update(RuleRunItem)
                .where(RuleRunItem.item_id == sending_item_id[0])
                .values(
                    status=status,
                    result=result,
                    error="Graph send failed for every recipient." if status == RuleRunItemStatus.FAILED else None,
                )
            )
            await self.db.commit()
        else:
            await self._record_item(
                interaction, index, action.type, status,
                skip_reason=outcome.get("skip_reason"), result=result,
            )

        if status == RuleRunItemStatus.SENT:
            self.state.bump("forwards_sent_count")
        elif status == RuleRunItemStatus.FAILED:
            self.state.record_error(interaction.interaction_id, action.type, "send failed")
        if outcome.get("skip_reason"):
            self.state.skip(outcome["skip_reason"])
        return _item_status_to_outcome(status)

    async def _record_item(
        self,
        interaction: Interaction,
        index: int,
        action_type: str,
        status: str,
        *,
        skip_reason: str | None = None,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        self.db.add(
            RuleRunItem(
                run_id=self.state.run_id,
                interaction_id=interaction.interaction_id,
                rule_id=self.snapshot_rule.rule_id,
                action_index=index,
                action_type=action_type,
                status=status,
                skip_reason=skip_reason,
                result=result or {},
                error=error[:2000] if error else None,
            )
        )
        await self.db.commit()
        self._new_items += 1

    # ------------------------------------------------------------------
    # Persistence / completion
    # ------------------------------------------------------------------

    async def _persist(self) -> None:
        await self.db.execute(
            update(RuleRun)
            .where(RuleRun.run_id == self.state.run_id)
            .values(**self.state.persisted_values())
        )
        await self.db.commit()

    async def _handle_infrastructure_failure(self, exc: Exception) -> None:
        logger.exception("RULE_RUN_INFRASTRUCTURE_FAILURE run_id=%s", self.state.run_id)
        try:
            await self.db.rollback()
        except Exception:
            logger.exception("RULE_RUN_ROLLBACK_FAILED run_id=%s", self.state.run_id)
        self.state.attempts += 1
        self.state.record_error(None, None, f"infrastructure: {exc!r}")
        try:
            if self.state.attempts > MAX_INFRA_ATTEMPTS:
                await self._finish(RuleRunStatus.FAILED, f"Infrastructure failure: {exc!r}"[:500])
            else:
                # Leave it running from the last persisted cursor; only
                # attempts/errors are written (not the in-memory cursor,
                # which may be ahead of committed work).
                await self.db.execute(
                    update(RuleRun)
                    .where(RuleRun.run_id == self.state.run_id)
                    .values(
                        attempts=self.state.attempts,
                        error_samples=self.state.error_samples,
                        heartbeat_at=datetime.now(timezone.utc),
                    )
                )
                await self.db.commit()
        except Exception:
            logger.exception("RULE_RUN_STATE_WRITE_FAILED run_id=%s", self.state.run_id)

    async def _finish(self, status: str, reason: str | None) -> None:
        await self.db.rollback()
        values = self.state.persisted_values()
        values.update(status=status, status_reason=reason, finished_at=datetime.now(timezone.utc))
        await self.db.execute(
            update(RuleRun).where(RuleRun.run_id == self.state.run_id).values(**values)
        )
        await RbacAuditLogService(audit_log_repository=RbacAuditLogRepository(self.db)).create_log(
            RbacAuditLogCreate(
                user_id=self.state.triggered_by,
                action=f"rule.run_now.{status}",
                entity_type="rule",
                entity_id=str(self.snapshot_rule.rule_id),
                new_value=_json(
                    {
                        "run_id": str(self.state.run_id),
                        "rule_owner_id": _str(self.state.rule_owner_id),
                        "triggered_by": str(self.state.triggered_by),
                        "impersonator_id": _str(self.state.impersonator_id),
                        "status_reason": reason,
                        "cutoff_at": self.state.cutoff_at.isoformat(),
                        "actions": [
                            a.get("type") for a in self.state.rule_snapshot.get("actions") or []
                            if isinstance(a, dict)
                        ],
                        **self.state.counts,
                        "skipped_by_reason": self.state.skipped_by_reason,
                    }
                ),
            )
        )
        await self.db.commit()
        logger.info(
            "RULE_RUN_FINISHED run_id=%s status=%s reason=%s counts=%s skipped=%s",
            self.state.run_id,
            status,
            reason,
            self.state.counts,
            self.state.skipped_by_reason,
        )


def _str(value) -> str | None:
    return str(value) if value is not None else None


def _json(value: dict) -> str:
    return json.dumps(value, default=str)


def _item_status_to_outcome(status: str) -> str:
    if status in (RuleRunItemStatus.APPLIED, RuleRunItemStatus.SENT):
        return "succeeded"
    if status == RuleRunItemStatus.ALREADY_APPLIED:
        return "already_applied"
    if status == RuleRunItemStatus.SKIPPED:
        return "skipped"
    return "failed"


# ----------------------------------------------------------------------
# Claiming (one tick)
# ----------------------------------------------------------------------


@dataclass
class _WorkerState:
    # The run this process is currently working through across ticks.
    current_run_id: UUID | None = None


_worker_state = _WorkerState()


async def claim_next_run(db: AsyncSession) -> RuleRun | None:
    """
    Picks the run this tick should work on: the one this process was
    already working through, else the oldest queued run, else a running
    run whose heartbeat has gone stale (its process died). FOR UPDATE
    SKIP LOCKED keeps two processes from claiming the same row. The
    cutoff is fixed at a run's first claim — after its rule's commit —
    and never changes on resume.
    """

    now = datetime.now(timezone.utc)
    conditions = [
        RuleRun.status == RuleRunStatus.QUEUED,
        and_(
            RuleRun.status == RuleRunStatus.RUNNING,
            or_(RuleRun.heartbeat_at.is_(None), RuleRun.heartbeat_at < now - STALE_HEARTBEAT),
        ),
    ]
    if _worker_state.current_run_id is not None:
        conditions.append(
            and_(
                RuleRun.run_id == _worker_state.current_run_id,
                RuleRun.status == RuleRunStatus.RUNNING,
            )
        )

    result = await db.execute(
        select(RuleRun)
        .where(or_(*conditions))
        .order_by(
            (RuleRun.run_id == _worker_state.current_run_id).desc()
            if _worker_state.current_run_id is not None
            else RuleRun.created_at.asc(),
            RuleRun.created_at.asc(),
        )
        .limit(1)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    run = result.scalar_one_or_none()
    if run is None:
        _worker_state.current_run_id = None
        await db.commit()
        return None

    if run.status == RuleRunStatus.QUEUED:
        run.status = RuleRunStatus.RUNNING
        run.started_at = now
        run.cutoff_at = now
        logger.info("RULE_RUN_STARTED run_id=%s rule_id=%s cutoff_at=%s", run.run_id, run.rule_id, now)
    elif run.run_id != _worker_state.current_run_id:
        logger.warning("RULE_RUN_RESUMED_STALE run_id=%s heartbeat_at=%s", run.run_id, run.heartbeat_at)
    run.heartbeat_at = now
    await db.flush()
    await db.commit()
    _worker_state.current_run_id = run.run_id
    return run


async def run_worker_tick(session_factory, *, budget_seconds: float = 40.0) -> str | None:
    """One scheduler tick. Returns the processor's result, or None if idle."""

    deadline = time.monotonic() + budget_seconds
    async with session_factory() as db:
        run = await claim_next_run(db)
        if run is None:
            return None
        processor = RuleRunProcessor(db, run)
        outcome = await processor.process(deadline=deadline)
        if outcome == "finished":
            _worker_state.current_run_id = None
        return outcome


def reset_worker_state() -> None:
    """Test hook."""
    _worker_state.current_run_id = None


