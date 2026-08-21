# Troubleshooting: Escalation

## Problem: An overseer role (Site Lead/Super Admin) sees or acts on an escalation before the chain has reached them

**Symptoms** (historical, fixed): A ticket freshly escalated to `TEAM_LEAD` shows up in an Account Manager's/Site Lead's/Super Admin's Escalated queue immediately, and they can even acknowledge it early.

**Possible Causes**: `TicketRepository`'s `view == "escalated"` condition previously only checked "does a non-CLOSED escalation exist," not "is the viewer actually a current owner." Separately, `EscalationService.acknowledge()`/`confirm_assignment()` had a `GLOBAL_INBOX_ROLE_NAMES` bypass allowing early action by overseer roles.

**Resolution**: Both fixed — the repository now uses an `owner_ids` JSONB-containment check (`_escalated_owner_condition`), and the overseer bypass was removed entirely from both service methods (and the matching frontend bypass, `SlaCard.tsx`'s `ESCALATION_OVERSEER_ROLES`).

**Prevention**: `test_view_escalated_permission.py` (15 tests) guards against a regression of this exact scoping.

**Related Documentation**: [03-business-workflows/escalation/escalation-handoff.md](../../03-business-workflows/escalation/escalation-handoff.md).

---

## Problem: The Resolution SLA clock restarted, but nobody actually owns the ticket yet

**Symptoms** (historical, fixed): A supervisor acknowledges an escalation but never assigns it; the Resolution SLA clock has already reshifted, and the previous owner has already lost the ability to act.

**Possible Causes**: `acknowledge()` used to reshift the Resolution SLA and start the Handling SLA itself — step 1 alone, before real acceptance (assignment) happened.

**Resolution**: `acknowledge()` now only stops the ack-window auto-advance; only `_complete_acceptance` (reached via claim/transfer/`confirm_assignment`) actually reshifts the clock and starts the Handling SLA. The freeze on the previous owner now checks for an actual `EscalationHandlingSLA` row's existence, not just `status`.

**Related Documentation**: [03-business-workflows/escalation/escalation-handoff.md](../../03-business-workflows/escalation/escalation-handoff.md).

---

## Potential Issue: `AttachmentService.upload_attachment` uses a coarser freeze check than other actions

**Symptoms**: An attachment upload might succeed on a ticket where reply/note/status-change would correctly be frozen (or vice versa), during the narrow "acknowledged but not yet assigned" window.

**Possible Causes**: This method has never been updated to pass an `EscalationHandlingSlaRepository` into `ensure_agent_can_act_on_ticket`, so it falls back to the older, coarser `status == ACTIVE` check.

**Resolution**: Known and accepted as-is — the fallback is still safe (never incorrectly frozen forever), just less precise than the newer check. Not scheduled for a fix as of this pass.

**Related Documentation**: [03-business-workflows/escalation/escalation-handoff.md](../../03-business-workflows/escalation/escalation-handoff.md).
