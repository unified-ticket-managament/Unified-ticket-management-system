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
}

export interface RulePayload {
  name: string;
  category: RuleCategory;
  is_enabled: boolean;
  conditions: RuleConditionGroup;
  exceptions: RuleConditionGroup;
  actions: RuleActionItem[];
  stop_processing: boolean;
}

export interface RuleResponse extends RulePayload {
  rule_id: string;
  priority: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
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
