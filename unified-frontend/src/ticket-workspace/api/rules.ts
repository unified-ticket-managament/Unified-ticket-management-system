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
}

export interface RuleResponse extends RulePayload {
  rule_id: string;
  priority: number;
  created_by: string | null;
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

export async function deleteRule(ruleId: string): Promise<void> {
  await apiClient.delete(`/rules/${ruleId}`);
}
