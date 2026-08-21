# Client Tables

## `clients`

| Column | Type | Null? | Business meaning |
|---|---|---|---|
| client_id | UUID | PK | |
| name | String(255) | | Company name |
| inbox_email | String(255) | UNIQUE, nullable | The curated distribution address for this client — **not** auto-derived from contacts (a real bug, since fixed, once made it so); lowercased |
| account_manager_id | UUID | indexed, NOT NULL | FK→users — ownership; drives Account-Manager-scoped ticket visibility |
| is_active | Boolean | default True | |
| created_at / updated_at | | | |

## `client_assignments`

`id` (PK), `client_id` (FK→clients CASCADE, indexed), `lead_role` (String(50), `CheckConstraint IN ('AR_LEAD','CODING_LEAD','POSTING_LEAD')`), `user_id` (FK→users CASCADE, indexed), `created_at`/`updated_at`. `UNIQUE(client_id, lead_role)` — one holder per lead role per client.

## `client_contacts`

`contact_id` (PK), `client_id` (FK CASCADE, indexed), `email` (String(255)), `is_primary` (Boolean, default False), `created_at`/`updated_at`. `UNIQUE(client_id, email)`.

## Business context

A `Client` (this table) is the external company; it is **not** the same as the RBAC `Client` role (formerly "Viewer") — see [18-glossary](../../18-glossary/README.md). `Ticket.client_id` (legacy, FK→users) and `Ticket.client_company_id` (FK→this table) coexist on the `Ticket` model — verify which one is authoritative for new code before writing against either; this documentation pass did not fully resolve which is considered primary going forward.
