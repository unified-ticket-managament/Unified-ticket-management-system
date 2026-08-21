# Workflow Testing

Coverage mapped against the core end-to-end flow documented in [03-business-workflows](../03-business-workflows/README.md).

| Workflow stage | Test coverage |
|---|---|
| Incoming email / Graph integration | `test_graph_mail_integration.py` (55 tests), `test_graph_email_sender.py` (8), `test_graph_mail_poller_multi_mailbox.py` (4), `test_attachment_envelope_loading.py` (5) |
| Client identification / thread detection | `test_email_service_client_matching.py` (5), `test_interaction_threading.py` (6) |
| Ticket creation / numbering | `test_ticket_number.py` (16), `test_inbox_ticket_service.py` (3) |
| Assignment / transfer / claim | `test_assigned_by.py` (9), `test_transfer_candidates.py` (8), `test_transfer_agent_ownership.py` (6), `test_ticket_status_on_assignment.py` (14) |
| SLA calculation and breach | `test_sla_clock_math.py` (30), `test_sla_sweep_service.py` (11), `test_sla_breach_notification_repository.py` (8), `test_resolution_sla_resolved_transition.py` (5) |
| Escalation | `test_escalation_service.py` (39), `test_escalation_rules.py` (12), `test_sla_escalation_rules.py` (27), `test_acknowledge_and_assign_escalation.py` (10), `test_escalation_read_only_access.py` (2), `test_escalation_handling_sla.py` (8), `test_assignment_chain_escalation.py` (4), `test_view_escalated_permission.py` (15) |
| Notification | `test_notification_email_dispatch.py` (15), `test_notification_clear_all.py` (5), `test_escalation_service_email_dedup.py` (1) |
| Audit / permissions | `test_permission_request_ticket_owner_routing.py` (9), `test_scoped_ticket_access_visibility.py` (5), `test_roles_page_user_visibility.py` (4), `test_user_listing_hierarchy.py` (6), `test_user_creation_role_matrix.py` (13) |
| Organization structure | `test_organization_chart_hierarchy.py` (14) |
| Internal notes / attachments | `test_internal_note_recipients.py` (15), `test_ticket_attachments.py` (9), `test_attachment_upload_authorization.py` (8) |
| Category transfer | `test_category_transfer.py` (7) |
| RBAC session cache | `test_rbac_cache.py` (7), `test_get_current_user_cache.py` (4) |

## What this table shows

Every workflow group in [03-business-workflows](../03-business-workflows/README.md) has real, non-trivial test coverage **except**:
- Notification delivery via SSE (`sse_manager.py`) — no dedicated test file found; the notification tests cover creation/dispatch logic, not the real-time push mechanism itself.
- The RBAC-domain audit-log writers (`auth.login`, `user.create`, etc.) — no dedicated test file confirms these write the correct rows for every action; this documentation pass could not confirm coverage here.
- Reports/Dashboard aggregation queries — no test file matched this area by name.

## Cross-reference

Each [03-business-workflows](../03-business-workflows/README.md) document's own "Edge Cases" section names the specific test file(s) most relevant to that workflow, where known.
