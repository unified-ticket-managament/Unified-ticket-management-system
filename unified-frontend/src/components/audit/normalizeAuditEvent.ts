import { Ticket as TicketIcon } from "lucide-react";
import { createElement } from "react";

import { ActionIcon, centralizedAuditTone } from "@/components/shared/audit";
import type { UnifiedAuditEvent, AuditEventField } from "@/components/audit/auditEvent.types";
import type { AuditLog } from "@/types";
import { auditMetaFor, diffFields, humanizeFieldKey } from "@tw/lib/auditLogMeta";
import { shortId } from "@tw/lib/format";
import type { ActorRole, AuditEntityType, AuditEventType } from "@tw/types";

// A ticket audit event's old/new_values diff routinely carries raw FK
// UUIDs (agent_id, client_company_id, category_id, ...) that mean
// nothing to a person reading the log — see the root CLAUDE.md-style
// note this was added for: "Agent Id: 1de0f8c4-..." / "Client Company
// Id: d09a244a-..." shown verbatim in the row/drawer. AuditLogPage.tsx
// already has agents/clients/categories loaded via WorkflowContext for
// its own filter dropdowns, so this resolves those same ids to names
// purely at the presentation layer — no backend change, and nothing is
// fabricated: an id that isn't found in the lookup (a deleted agent/
// client/category) falls back to a short id, never a made-up name.
export interface AuditFieldLookup {
  agents?: Map<string, string>;
  clients?: Map<string, string>;
  categories?: Map<string, string>;
}

const ID_FIELD_LABELS: Record<string, { label: string; lookup: keyof AuditFieldLookup }> = {
  agent_id: { label: "Agent", lookup: "agents" },
  account_manager_id: { label: "Account Manager", lookup: "agents" },
  manager_id: { label: "Manager", lookup: "agents" },
  teamlead_id: { label: "Team Lead", lookup: "agents" },
  client_company_id: { label: "Client", lookup: "clients" },
  category_id: { label: "Category", lookup: "categories" },
};

function resolveIdValue(value: unknown, map?: Map<string, string>): unknown {
  if (value === null || value === undefined || value === "") return value;
  const id = String(value);
  return map?.get(id) ?? shortId(id, 8);
}

function humanizeAuditFields(
  rawFields: { key: string; from: unknown; to: unknown }[],
  lookup: AuditFieldLookup
): AuditEventField[] {
  const keys = new Set(rawFields.map((field) => field.key));

  return rawFields
    .filter((field) => {
      const idMatch = field.key.match(/^(.*)_id$/);
      if (!idMatch) return true;
      // A sibling `<prefix>_name` field already carries the
      // human-readable version of this same id in this same diff — the
      // raw id would just be a redundant, less-readable duplicate.
      return !keys.has(`${idMatch[1]}_name`);
    })
    .map((field) => {
      const idConfig = ID_FIELD_LABELS[field.key];
      if (!idConfig) {
        return { key: field.key, label: humanizeFieldKey(field.key), from: field.from, to: field.to };
      }
      const map = lookup[idConfig.lookup];
      return {
        key: field.key,
        label: idConfig.label,
        from: resolveIdValue(field.from, map),
        to: resolveIdValue(field.to, map),
      };
    });
}

// ---------------------------------------------------------------------------
// Ticket-scoped audit events (GET /tickets/audit-logs) — the shape
// AuditLogPage.tsx already builds from TicketAuditLogResponse before this
// module existed; kept here so the adapter and its input type live next to
// each other, and AuditLogPage.tsx imports this instead of declaring its own.
// ---------------------------------------------------------------------------
export interface TicketAuditEventInput {
  auditId: string;
  createdAt: string;
  entityType: AuditEntityType;
  eventType: AuditEventType;
  actorName: string;
  actorRole: ActorRole;
  impersonatorName: string | null;
  ticketId: string;
  ticketTitle: string;
  clientCompanyName: string | null;
  oldValues: Record<string, unknown> | null;
  newValues: Record<string, unknown> | null;
}

const TICKET_ACTOR_ROLE_LABEL: Record<ActorRole, string> = {
  AGENT: "Agent",
  CLIENT: "Client",
  SYSTEM: "System",
};

export function normalizeTicketAuditEvent(
  row: TicketAuditEventInput,
  onViewTicket: (ticketId: string) => void,
  fieldLookup: AuditFieldLookup = {}
): UnifiedAuditEvent {
  const meta = auditMetaFor(row.eventType);
  const fields = humanizeAuditFields(diffFields(row.oldValues, row.newValues), fieldLookup);

  return {
    id: row.auditId,
    icon: meta.icon,
    tone: meta.tone,
    actionLabel: meta.label,
    entityLabel: row.ticketTitle,
    entityMeta: row.clientCompanyName,
    entityTypeLabel: row.entityType,
    fields,
    timestamp: row.createdAt,
    actorName: row.actorName,
    actorRole: TICKET_ACTOR_ROLE_LABEL[row.actorRole],
    impersonatorName: row.impersonatorName,
    metadata: [{ label: "Related Ticket", value: row.ticketTitle }],
    primaryAction: {
      label: "View Ticket",
      icon: createElement(TicketIcon, { size: 14 }),
      onClick: () => onViewTicket(row.ticketId),
    },
  };
}

// ---------------------------------------------------------------------------
// Centralized/RBAC-native audit events (GET /audit-logs) — the shape
// CentralizedAuditLogPanel.tsx builds by joining AuditLog rows against the
// users/roles lists it already fetches (userName/userRole/impersonatorName).
// ---------------------------------------------------------------------------
export interface CentralizedAuditEventInput extends AuditLog {
  userName: string;
  userEmail: string | null;
  userRole: string | null;
  impersonatorName: string | null;
}

// Same outcome heuristic CentralizedAuditLogPanel/its drawer used before
// this module existed — every logged action other than a failed
// login/rejected request only ever gets written after it already
// succeeded, so anything else is genuinely "Success," not an assumption.
function isFailureAction(action: string): boolean {
  const value = action.toLowerCase();
  return value.includes("failed") || value.includes("reject");
}

export function normalizeCentralizedAuditEvent(row: CentralizedAuditEventInput): UnifiedAuditEvent {
  const fields =
    row.old_value || row.new_value
      ? [{ key: "value", label: "Value", from: row.old_value, to: row.new_value }]
      : [];

  const metadata: UnifiedAuditEvent["metadata"] = [
    { label: "Status", value: isFailureAction(row.action) ? "Failed" : "Success" },
  ];
  if (row.userEmail) metadata.push({ label: "Email", value: row.userEmail });
  if (row.ip_address) metadata.push({ label: "IP Address", value: row.ip_address, mono: true });

  return {
    id: row.audit_log_id,
    icon: createElement(ActionIcon, { action: row.action }),
    tone: centralizedAuditTone(row.action),
    actionLabel: row.action,
    entityLabel: row.entity_type,
    entityMeta: row.entity_id ? row.entity_id.slice(0, 8) : null,
    entityTypeLabel: row.entity_type,
    fields,
    timestamp: row.timestamp,
    actorName: row.userName,
    actorRole: row.userRole,
    impersonatorName: row.impersonatorName,
    metadata,
  };
}
