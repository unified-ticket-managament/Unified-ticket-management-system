import type { ReactNode } from "react";

// Shared across both audit domains (ticket-scoped and RBAC-native/
// centralized) — see normalizeAuditEvent.ts for the two adapters that
// build this from each domain's own API response shape, and
// AuditEventRow.tsx/AuditEventDetailsDrawer.tsx for the two places it's
// actually rendered. Neither domain's raw fields leak past the
// adapters — this is the one shape every presentation component reads.
export type AuditEventTone = "default" | "success" | "warning" | "danger" | "info" | "accent";

// One row of a before/after (or "value observed") change, rendered as
// a single summary line on the row (`to` only) and a full from→to pair
// in the details drawer. A domain with no meaningful per-field diff
// (e.g. a single opaque old/new string) still fits this shape as one
// field with a generic label — see normalizeAuditEvent.ts.
export interface AuditEventField {
  key: string;
  label: string;
  from: unknown;
  to: unknown;
}

// An extra label/value pair shown only in the details drawer's summary
// grid — this is where domain-specific facts live (a ticket's related-
// ticket title, an RBAC row's IP address/email) without the shared row
// or drawer *structure* ever needing to know which domain produced
// them. Absent/omitted fields simply don't render — never fabricated.
export interface AuditEventMetadataItem {
  label: string;
  value: string;
  mono?: boolean;
}

export interface AuditEventPrimaryAction {
  label: string;
  icon?: ReactNode;
  onClick: () => void;
}

export interface UnifiedAuditEvent {
  id: string;
  // A single glyph (emoji string or a lucide icon element both work —
  // the row/drawer only ever place this inside one shared icon circle).
  icon: ReactNode;
  tone: AuditEventTone;
  // Rendered as the tone-colored badge — "Ticket Created" for a ticket
  // event, the raw action string (e.g. "user.create") for a centralized
  // one.
  actionLabel: string;
  // The "on <entityLabel>" text next to the badge.
  entityLabel: string;
  // Optional trailing "· <entityMeta>" text after entityLabel (a
  // ticket's client company name; a centralized row's short entity id).
  entityMeta?: string | null;
  // The type/category of the affected entity — surfaced in the details
  // drawer's badge row (ticket: AuditEntityType; centralized: the raw
  // entity_type string).
  entityTypeLabel?: string;
  fields: AuditEventField[];
  timestamp: string;
  actorName: string;
  actorRole?: string | null;
  // See root CLAUDE.md's impersonation section — set only when this
  // row was written during an active "Login as User" session, for
  // either domain.
  impersonatorName?: string | null;
  metadata?: AuditEventMetadataItem[];
  primaryAction?: AuditEventPrimaryAction;
}
