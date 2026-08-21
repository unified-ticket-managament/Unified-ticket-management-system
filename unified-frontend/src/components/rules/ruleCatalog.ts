import type { RuleActionType, RuleCategory, RuleConditionOperator } from "@tw/api/rules";

// Mirrors unified-backend/app/ticketing/enums/rule_enums.py exactly —
// keep both in sync by hand, since the backend deliberately keeps
// this vocabulary as plain strings (not a native Postgres enum) for
// the same reason this file isn't generated from it.

export interface ConditionFieldDef {
  value: string;
  label: string;
  // Fields with a fixed operator (subject/body "contains", client
  // "in") never show an operator picker — Outlook-style, the verb is
  // baked into the field name itself.
  fixedOperator?: RuleConditionOperator;
  kind: "text" | "client-single" | "client-multi" | "boolean";
}

export const CONDITION_FIELDS: Record<string, ConditionFieldDef> = {
  sender_email: { value: "sender_email", label: "Sender Email", kind: "text" },
  sender_domain: { value: "sender_domain", label: "Sender Domain", kind: "text" },
  subject_contains: {
    value: "subject_contains",
    label: "Subject contains",
    fixedOperator: "contains",
    kind: "text",
  },
  body_contains: {
    value: "body_contains",
    label: "Body contains",
    fixedOperator: "contains",
    kind: "text",
  },
  client: { value: "client", label: "Client", fixedOperator: "in", kind: "client-single" },
  client_multi: {
    value: "client",
    label: "Client",
    fixedOperator: "in",
    kind: "client-multi",
  },
  has_attachment: {
    value: "has_attachment",
    label: "Has attachment(s)",
    fixedOperator: "equals",
    kind: "boolean",
  },
  recipient_cc: {
    value: "recipient_cc",
    label: "Cc contains",
    fixedOperator: "contains",
    kind: "text",
  },
  attachment_name_contains: {
    value: "attachment_name_contains",
    label: "Attachment name contains",
    fixedOperator: "contains",
    kind: "text",
  },
  attachment_type_contains: {
    value: "attachment_type_contains",
    label: "Attachment type contains",
    fixedOperator: "contains",
    kind: "text",
  },
};

export const CONDITION_FIELDS_BY_CATEGORY: Record<RuleCategory, ConditionFieldDef[]> = {
  mail_rule: [
    CONDITION_FIELDS.sender_email,
    CONDITION_FIELDS.sender_domain,
    CONDITION_FIELDS.subject_contains,
    CONDITION_FIELDS.body_contains,
    CONDITION_FIELDS.client,
    CONDITION_FIELDS.has_attachment,
    CONDITION_FIELDS.recipient_cc,
    CONDITION_FIELDS.attachment_name_contains,
    CONDITION_FIELDS.attachment_type_contains,
  ],
  otp_rule: [
    CONDITION_FIELDS.subject_contains,
    CONDITION_FIELDS.body_contains,
    CONDITION_FIELDS.client_multi,
  ],
};

export interface ActionTypeDef {
  value: RuleActionType;
  label: string;
}

export const ACTION_TYPES: Record<RuleActionType, ActionTypeDef> = {
  create_folder: { value: "create_folder", label: "Create Folder" },
  move_to_folder: { value: "move_to_folder", label: "Move to Folder" },
  forward_to: { value: "forward_to", label: "Forward To" },
};

export const ACTION_TYPES_BY_CATEGORY: Record<RuleCategory, ActionTypeDef[]> = {
  mail_rule: [ACTION_TYPES.create_folder, ACTION_TYPES.move_to_folder],
  otp_rule: [ACTION_TYPES.forward_to],
};

export const CATEGORY_LABELS: Record<RuleCategory, string> = {
  mail_rule: "Mail Rule",
  otp_rule: "OTP Rule",
};
