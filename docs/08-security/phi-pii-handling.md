# PHI/PII Handling

## Context

The seeded/demo client and employee data referenced throughout root `CLAUDE.md` (email domains like `probeps.com`, `painmedpa.com`, client categories including `AR` (Accounts Receivable), `Authorization`, `Coding`, `Credentialing`, `Payment Posting`) strongly suggests this system serves a **medical billing / revenue-cycle-management** business context — categories like "Coding" (medical coding) and "Authorization" (prior authorization) are standard healthcare RCM terminology. **This is an inference from naming conventions and domain names actually present in the codebase's own seed data/documentation, not a confirmed business classification** — no explicit HIPAA/PHI compliance statement or policy document was found in the repository.

## What this means if the inference is correct

If client communications (email subject/body, attachments) ever contain Protected Health Information (patient names, dates of service, diagnosis/procedure codes, insurance details), then:

- `interactions.payload` (email body) and `attachments` (files) are the primary PHI-bearing tables.
- Access to these is governed by the same category/client-ownership ticket-visibility rules documented in [08-security/authorization-rbac.md](authorization-rbac.md) — there is no PHI-specific additional access control layer found in the code.
- The audit trail (`ticket_audit_logs`) captures metadata about who accessed/changed what, but **does not itself log read access to email bodies/attachments** — only mutating actions are audited; viewing a ticket or downloading an attachment is not a recorded audit event (attachment download/delete was explicitly noted elsewhere in this documentation as deliberately not logged — see [04-functional-modules/audit-management.md](../04-functional-modules/audit-management.md)).
- No field-level encryption-at-rest beyond whatever Neon/Supabase provide at the infrastructure level was found in application code.
- No automated PHI redaction/masking exists anywhere in the pipeline (email intake, storage, or Timeline display).

## What is NOT confirmed

- Whether this deployment operates under a Business Associate Agreement (BAA) with Microsoft (Graph), Neon, Supabase, or any SMTP provider — this is a legal/contractual question outside what source code can confirm.
- Whether any of the organization's actual clients' data constitutes PHI under HIPAA, or whether this system is even subject to HIPAA at all.
- Whether any compliance audit (SOC 2, HIPAA risk assessment, etc.) has been performed.

## Recommendation

If this system does handle PHI in production, a formal compliance review (access logging for reads, not just writes; encryption-at-rest verification; BAA confirmation with every third-party processor — Microsoft Graph, Neon, Supabase, SMTP provider) is strongly recommended and was not found to have been done as part of this codebase's own documented history. Treat this entire document as a flag for further investigation, not a compliance certification.
