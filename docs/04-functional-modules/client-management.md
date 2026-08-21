# Client Management Module

## Purpose
Represent the external companies whose emails become tickets, and their ownership by an Account Manager.

## Responsibilities
- Client onboarding (company + inbox distribution address + contacts).
- Account Manager ownership assignment.
- Contact-email resolution (for client identification during email intake, and for the Reply "To" picker when a client has multiple known addresses).
- Lead-role assignment per client (`ClientAssignment` — AR Lead / Coding Lead / Posting Lead).

## Main Components
- `app/ticketing/api/client.py`
- `app/ticketing/services/client_service.py`
- `app/ticketing/repositories/client_repository.py`
- `app/ticketing/models/{client,client_assignment,client_contact}.py`

## Inputs
Client onboarding form (name, distribution inbox address, Account Manager), contact emails.

## Outputs
Client detail views, contact lists for reply/thread pickers.

## Business Rules
- `clients.inbox_email` is a curated distribution address, not auto-picked from a contact — a real historical bug (`inbox_email` previously auto-selected from `client_contacts`) was fixed by a dedicated migration (`a4c6e8f0b2d4_fix_client_inbox_email_distribution`) that made the column nullable and migrated old incorrect values into `client_contacts` instead.
- `GET /clients/{id}/contacts` is deliberately ungated beyond authentication — used by the Reply "To" picker, where restricting it further would break a legitimate cross-role reply flow.
- `ClientAssignment.lead_role` is constrained to exactly `AR_LEAD`/`CODING_LEAD`/`POSTING_LEAD` (DB `CheckConstraint`), one assignment per `(client_id, lead_role)`.
- **Client filtering (added 2026-08-21)**: a `client_company_id` query parameter now narrows the Tickets list, Dashboard stats, SLA overview tiles, ticket-domain Audit Log, and Interactions list to one client — always **within** whatever the caller's own role scope already allows (an Account Manager can only usefully filter to a client they own; the filter never widens visibility). Backed by a single shared frontend component (`ClientFilterSelect.tsx`), sourced from the already-cached `GET /clients` list. See [07-api/tickets.md](../07-api/tickets.md).

## Dependencies
`UserRepository` (Account Manager validation).

## Database Entities
`clients`, `client_assignments`, `client_contacts`.

## APIs
[07-api/clients-categories-rules.md](../07-api/clients-categories-rules.md).

## Important Classes/Services
`ClientService`, `ClientRepository`.

## External Integrations
None directly (client identification during email intake is covered in [04-functional-modules/communication-management.md](communication-management.md)).

## Known Limitations
None specifically identified for this module beyond the historical `inbox_email` bug above (now fixed).

## Related workflows
[03-business-workflows/communication/email-processing.md](../03-business-workflows/communication/email-processing.md) (client identification).
