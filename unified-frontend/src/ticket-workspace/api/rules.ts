import { apiClient } from "./client";

// Mail/OTP Rules — see unified-backend/app/ticketing/schemas/rule.py for
// the matching Pydantic shapes these mirror. Trigger is always fixed
// ("Email Received"), so there is no trigger field to send/receive.

export type RuleCategory = "mail_rule" | "otp_rule";
export type RuleCombinator = "AND" | "OR";
export type RuleConditionOperator = "equals" | "contains" | "in";
export type RuleActionType = "create_folder" | "move_to_folder" | "forward_to";

export interface RuleConditionItem {
  field: string;
  operator: RuleConditionOperator;
  value: string | string[] | boolean;
}

export interface RuleConditionGroup {
  combinator: RuleCombinator;
  rules: RuleConditionItem[];
}

export interface RuleActionItem {
  type: RuleActionType;
  folder_name?: string | null;
  employee_user_ids?: string[] | null;
  // Distribution Lists to forward to, resolved to their current
  // active members fresh at every execution — never a snapshot. Only
  // meaningful for forward_to; merged with employee_user_ids at
  // execution time (RuleEngineService), not at save time.
  distribution_list_ids?: string[] | null;
}

export interface RulePayload {
  name: string;
  category: RuleCategory;
  is_enabled: boolean;
  conditions: RuleConditionGroup;
  exceptions: RuleConditionGroup;
  actions: RuleActionItem[];
  stop_processing: boolean;
  // Explicitly added/shared/assigned users — an empty/omitted list
  // means this rule (and its associated folder) is private to
  // created_by. Distinct from a forward_to action's employee_user_ids:
  // a forward destination is never itself a grant of rule access.
  shared_user_ids?: string[];
  // Same grant, extended to Distribution Lists — every current,
  // active member of a listed Distribution List gets the same
  // view/manage access shared_user_ids grants an individual employee,
  // resolved fresh server-side on every request (never a snapshot).
  shared_distribution_list_ids?: string[];
  // One-time command, never stored on the rule: when true, the saved
  // rule is also queued for a single background run against existing
  // mail (see unified-backend's RuleRunService). Omitted/false on a
  // normal save, so editing a rule never re-runs it.
  run_now?: boolean;
}

export type RuleRunStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "capped";

export interface RuleRunRef {
  run_id: string;
  status: RuleRunStatus;
}

// Progress of a "Run rule now" execution — counts only, never email
// content. Mirrors app/ticketing/schemas/rule.py's RuleRunSummary.
export interface RuleRunSummary extends RuleRunRef {
  rule_id: string | null;
  rule_name: string;
  status_reason: string | null;
  phase: string;
  triggered_by: string;
  rule_owner_id: string | null;
  impersonator_id: string | null;
  cutoff_at: string;
  scanned_count: number;
  matched_count: number;
  succeeded_count: number;
  already_applied_count: number;
  skipped_count: number;
  failed_count: number;
  forwards_sent_count: number;
  skipped_by_reason: Record<string, number>;
  error_samples: { interaction_id: string | null; action: string | null; error: string }[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
}

export interface RuleResponse extends RulePayload {
  rule_id: string;
  priority: number;
  created_by: string | null;
  // Display name of created_by — set by GET /rules; null if unknown.
  created_by_name?: string | null;
  shared_user_ids: string[];
  shared_distribution_list_ids: string[];
  created_at: string;
  updated_at: string;
  // Whether the current viewer can edit/delete/toggle/reorder this
  // specific rule — distinct from being able to see it at all. A
  // rule:view_all holder (Super Admin/Site Lead) can see every rule
  // in GET /rules but this is false for one they didn't create and
  // aren't shared on; every mutation still enforces this server-side
  // regardless of what the UI does with this flag.
  can_manage: boolean;
  // The rule's queued/running "Run rule now" execution, if any.
  active_run: RuleRunRef | null;
}

export async function listRules(signal?: AbortSignal): Promise<RuleResponse[]> {
  const { data } = await apiClient.get<RuleResponse[]>("/rules", { signal });
  return data;
}

export async function createRule(
  payload: RulePayload
): Promise<RuleResponse> {
  const { data } = await apiClient.post<RuleResponse>("/rules", payload);
  return data;
}

export async function updateRule(
  ruleId: string,
  payload: Omit<RulePayload, "category">
): Promise<RuleResponse> {
  const { data } = await apiClient.put<RuleResponse>(`/rules/${ruleId}`, payload);
  return data;
}

export async function setRuleEnabled(
  ruleId: string,
  isEnabled: boolean
): Promise<RuleResponse> {
  const { data } = await apiClient.patch<RuleResponse>(`/rules/${ruleId}/enabled`, {
    is_enabled: isEnabled,
  });
  return data;
}

export async function reorderRule(
  ruleId: string,
  direction: "up" | "down"
): Promise<RuleResponse[]> {
  const { data } = await apiClient.post<RuleResponse[]>(`/rules/${ruleId}/reorder`, {
    direction,
  });
  return data;
}

export async function getLatestRuleRun(
  ruleId: string,
  signal?: AbortSignal
): Promise<RuleRunSummary> {
  const { data } = await apiClient.get<RuleRunSummary>(`/rules/${ruleId}/runs/latest`, { signal });
  return data;
}

export async function deleteRule(ruleId: string): Promise<void> {
  await apiClient.delete(`/rules/${ruleId}`);
}
