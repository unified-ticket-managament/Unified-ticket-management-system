"use client";

import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { RotateCcw, Save } from "lucide-react";

import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { PageHeader } from "@/components/layout/dashboard-shell";
import { AccessDenied, ErrorState } from "@/components/shared/stats";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { useAuthStore } from "@/store/auth-store";
import { listSlaPolicies, updateSlaPolicy } from "@tw/api/sla";
import { formatDurationShort } from "@tw/lib/slaMath";
import type { SLAPolicyResponse, SLAPolicyUpdatePayload, TicketPriority } from "@tw/types";

// Display order — most urgent first, matching this app's SLA Timing
// Matrix framing (not the ascending order TicketsListPage's own filter
// dropdown happens to use).
const PRIORITY_ORDER: TicketPriority[] = ["HIGH", "MEDIUM", "LOW"];

type EditableField =
  | "first_response_target_minutes"
  | "resolution_target_minutes"
  | "escalation_ack_target_minutes"
  | "warning_1_percentage"
  | "warning_2_percentage";

const MINUTE_FIELDS: EditableField[] = [
  "first_response_target_minutes",
  "resolution_target_minutes",
  "escalation_ack_target_minutes",
];
const PERCENTAGE_FIELDS: EditableField[] = ["warning_1_percentage", "warning_2_percentage"];

// handling_stage_percentages is a variable-length array (stage 1 =
// index 0, etc.) — edited separately from the scalar EditableFields
// above, since it can't share their Record<EditableField, string>
// shape. handling_sla_percentage itself is deliberately no longer
// editable here — it's superseded and unread by any backend logic
// (see SLAPolicyResponse's own comment in types/index.ts).
type Draft = Record<EditableField, string> & {
  policy_id: string;
  priority: TicketPriority;
  handling_stage_percentages: string[];
};
type Errors = Partial<Record<EditableField, string>> & {
  handling_stage_percentages?: (string | undefined)[];
};

function toDraft(policy: SLAPolicyResponse): Draft {
  return {
    policy_id: policy.policy_id,
    priority: policy.priority,
    first_response_target_minutes: String(policy.first_response_target_minutes),
    resolution_target_minutes: String(policy.resolution_target_minutes),
    escalation_ack_target_minutes: String(policy.escalation_ack_target_minutes),
    warning_1_percentage: String(policy.warning_1_percentage),
    warning_2_percentage: String(policy.warning_2_percentage),
    handling_stage_percentages: policy.handling_stage_percentages.map(String),
  };
}

function validateField(field: EditableField, raw: string): string | undefined {
  if (raw.trim() === "") return "Required";
  const value = Number(raw);
  if (!Number.isFinite(value)) return "Must be a number";

  if (MINUTE_FIELDS.includes(field)) {
    if (!Number.isInteger(value)) return "Whole minutes only";
    if (value <= 0) return "Must be greater than 0";
  } else {
    if (value < 1 || value > 100) return "Must be between 1 and 100";
  }
  return undefined;
}

function validateStagePercentage(raw: string): string | undefined {
  if (raw.trim() === "") return "Required";
  const value = Number(raw);
  if (!Number.isFinite(value)) return "Number";
  if (value < 1 || value > 100) return "1-100";
  return undefined;
}

function validateDraft(draft: Draft): Errors {
  const errors: Errors = {};
  for (const field of [...MINUTE_FIELDS, ...PERCENTAGE_FIELDS]) {
    const message = validateField(field, draft[field]);
    if (message) errors[field] = message;
  }

  const stageErrors = draft.handling_stage_percentages.map(validateStagePercentage);
  if (stageErrors.some((message) => message !== undefined)) {
    errors.handling_stage_percentages = stageErrors;
  }

  // Cross-field: Warning 1 ("Half Elapsed") must fire before Warning 2
  // ("At Risk") as elapsed time increases — an inverted pair (e.g.
  // warning_1=90, warning_2=50) would make "At Risk" trigger before
  // "Half Elapsed" already had. Only checked once both fields are
  // individually valid, so this doesn't stack on top of a "Must be a
  // number"-type error. Mirrors the backend's own merged-value check
  // (SLAService.update_policy) so a save attempt never round-trips
  // just to discover this.
  if (!errors.warning_1_percentage && !errors.warning_2_percentage) {
    const warning1 = Number(draft.warning_1_percentage);
    const warning2 = Number(draft.warning_2_percentage);
    if (warning1 >= warning2) {
      errors.warning_2_percentage = "Must be greater than Warning 1";
    }
  }

  return errors;
}

function draftDiffersFromOriginal(draft: Draft, original: SLAPolicyResponse): boolean {
  const scalarDiffers = [...MINUTE_FIELDS, ...PERCENTAGE_FIELDS].some(
    (field) => draft[field] !== String(original[field])
  );
  const stagesDiffer =
    draft.handling_stage_percentages.length !== original.handling_stage_percentages.length ||
    draft.handling_stage_percentages.some(
      (value, index) => value !== String(original.handling_stage_percentages[index])
    );
  return scalarDiffers || stagesDiffer;
}

function updateStagePercentage(draft: Draft, index: number, value: string): Draft {
  const handling_stage_percentages = [...draft.handling_stage_percentages];
  handling_stage_percentages[index] = value;
  return { ...draft, handling_stage_percentages };
}

export default function SlaTimingMatrixPage() {
  const currentUser = useAuthStore((s) => s.user);
  const hasPermission = useAuthStore((s) => s.hasPermission);
  const { toast } = useToast();

  const [policies, setPolicies] = useState<SLAPolicyResponse[] | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // Fetch once on mount — cancelled on unmount, never re-fetched on a
  // re-render (drafts/save state changes below never re-trigger this
  // effect, since it has no dependencies).
  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    listSlaPolicies(controller.signal)
      .then((data) => {
        // CRITICAL is not an independently configurable SLA tier — a
        // ticket's original priority's timings always apply, even
        // after it escalates and displays as Critical (see
        // EscalationService._set_ticket_priority_to_critical). Filtered
        // out here rather than at the API layer so GET /sla/policies
        // itself stays unchanged for any other consumer.
        const editable = data.filter((policy) => policy.priority !== "CRITICAL");
        setPolicies(editable);
        setDrafts(editable.map(toDraft));
        setLoadError(null);
      })
      .catch((error) => {
        if (axios.isCancel(error)) return;
        setLoadError("Failed to load the SLA Timing Matrix. Please try again.");
      })
      .finally(() => setIsLoading(false));
    return () => controller.abort();
  }, []);

  const policyById = useMemo(() => {
    const map = new Map<string, SLAPolicyResponse>();
    for (const p of policies ?? []) map.set(p.policy_id, p);
    return map;
  }, [policies]);

  const orderedDrafts = useMemo(
    () =>
      [...drafts].sort(
        (a, b) => PRIORITY_ORDER.indexOf(a.priority) - PRIORITY_ORDER.indexOf(b.priority)
      ),
    [drafts]
  );

  const errorsByPolicyId = useMemo(() => {
    const map = new Map<string, Errors>();
    for (const draft of drafts) map.set(draft.policy_id, validateDraft(draft));
    return map;
  }, [drafts]);

  const dirtyPolicyIds = useMemo(() => {
    const ids = new Set<string>();
    for (const draft of drafts) {
      const original = policyById.get(draft.policy_id);
      if (original && draftDiffersFromOriginal(draft, original)) ids.add(draft.policy_id);
    }
    return ids;
  }, [drafts, policyById]);

  const hasAnyError = useMemo(
    () => [...errorsByPolicyId.values()].some((errors) => Object.keys(errors).length > 0),
    [errorsByPolicyId]
  );

  const hasUnsavedChanges = dirtyPolicyIds.size > 0;

  // Mirrors the backend's PATCH /sla/policies/{id} gate (sla:manage_
  // policies — Full for Super Admin/Site Lead, Override-only for
  // everyone else). Previously hardcoded to Super Admin only, which
  // incorrectly excluded Site Lead despite holding this permission by
  // default.
  if (currentUser && !hasPermission("sla:manage_policies")) {
    return <AccessDenied message="You do not have access to the SLA Timing Matrix." />;
  }

  function updateField(policyId: string, field: EditableField, value: string) {
    setDrafts((prev) =>
      prev.map((d) => (d.policy_id === policyId ? { ...d, [field]: value } : d))
    );
  }

  function updateStage(policyId: string, index: number, value: string) {
    setDrafts((prev) =>
      prev.map((d) => (d.policy_id === policyId ? updateStagePercentage(d, index, value) : d))
    );
  }

  function handleReset() {
    if (!policies) return;
    setDrafts(policies.map(toDraft));
  }

  async function handleSave() {
    if (!policies || hasAnyError || !hasUnsavedChanges) return;
    setIsSaving(true);
    try {
      const results = await Promise.allSettled(
        drafts
          .filter((draft) => dirtyPolicyIds.has(draft.policy_id))
          .map((draft) => {
            const payload: SLAPolicyUpdatePayload = {
              first_response_target_minutes: Number(draft.first_response_target_minutes),
              resolution_target_minutes: Number(draft.resolution_target_minutes),
              escalation_ack_target_minutes: Number(draft.escalation_ack_target_minutes),
              handling_stage_percentages: draft.handling_stage_percentages.map(Number),
              warning_1_percentage: Number(draft.warning_1_percentage),
              warning_2_percentage: Number(draft.warning_2_percentage),
            };
            return updateSlaPolicy(draft.policy_id, payload);
          })
      );

      const updated: SLAPolicyResponse[] = [];
      let failureCount = 0;
      for (const result of results) {
        if (result.status === "fulfilled") updated.push(result.value);
        else failureCount++;
      }

      if (updated.length > 0) {
        setPolicies((prev) => {
          const base = prev ?? [];
          const byId = new Map(base.map((p) => [p.policy_id, p]));
          for (const p of updated) byId.set(p.policy_id, p);
          return Array.from(byId.values());
        });
      }

      if (failureCount === 0) {
        toast({
          title: "SLA Timing Matrix saved",
          description: `${updated.length} ${updated.length === 1 ? "priority" : "priorities"} updated.`,
        });
      } else {
        const firstError = results.find((r) => r.status === "rejected") as
          | PromiseRejectedResult
          | undefined;
        const detail =
          axios.isAxiosError(firstError?.reason) && firstError.reason.response?.data?.detail
            ? String(firstError.reason.response.data.detail)
            : "Please check the values and try again.";
        toast({
          title: `${failureCount} update${failureCount === 1 ? "" : "s"} failed`,
          description: detail,
          variant: "destructive",
        });
      }
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <Breadcrumbs
        items={[{ label: "Dashboard", href: "/dashboard" }, { label: "SLA Timing Matrix" }]}
      />

      <PageHeader
        title="SLA Timing Matrix"
        description="Configure First Response, Resolution, escalation, handling-stage, and warning timing per priority. Each handling stage's percentage is of the ticket's ORIGINAL priority's Resolution SLA target — a stage beyond the configured list repeats the last value. Edits apply to new SLA clocks and to any ticket whose priority changes afterward (including via escalation) — they are not applied retroactively to a clock already running at its current, unchanged priority."
        action={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={handleReset}
              disabled={isLoading || isSaving || !hasUnsavedChanges}
            >
              <RotateCcw className="mr-2 h-4 w-4" />
              Reset
            </Button>
            <Button onClick={handleSave} disabled={isLoading || isSaving || hasAnyError || !hasUnsavedChanges}>
              <Save className="mr-2 h-4 w-4" />
              {isSaving ? "Saving..." : "Save Changes"}
            </Button>
          </div>
        }
      />

      {loadError && <ErrorState message={loadError} />}

      {!loadError && (
        <Card>
          <CardContent className="p-0">
            {isLoading ? (
              <div className="space-y-3 p-6">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-16 w-full" />
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Priority</TableHead>
                    <TableHead>First Response SLA (min)</TableHead>
                    <TableHead>Resolution SLA (min)</TableHead>
                    <TableHead>Escalation Ack Window (min)</TableHead>
                    <TableHead>Handling Stage Percentages (%)</TableHead>
                    <TableHead>Warning 1 (%)</TableHead>
                    <TableHead>Warning 2 (%)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {orderedDrafts.map((draft) => {
                    const errors = errorsByPolicyId.get(draft.policy_id) ?? {};
                    const resolutionMinutes = Number(draft.resolution_target_minutes);
                    const stageErrors = errors.handling_stage_percentages ?? [];

                    return (
                      <TableRow key={draft.policy_id}>
                        <TableCell className="font-semibold">{draft.priority}</TableCell>
                        {MINUTE_FIELDS.map((field) => (
                          <TableCell key={field}>
                            <Input
                              type="number"
                              min={1}
                              step={1}
                              value={draft[field]}
                              onChange={(e) => updateField(draft.policy_id, field, e.target.value)}
                              className="w-24"
                              aria-invalid={!!errors[field]}
                            />
                            {!errors[field] && Number.isFinite(Number(draft[field])) && (
                              <p className="mt-1 text-xs text-muted-foreground">
                                {formatDurationShort(Number(draft[field]) * 60)}
                              </p>
                            )}
                            {errors[field] && (
                              <p className="mt-1 text-xs text-destructive">{errors[field]}</p>
                            )}
                          </TableCell>
                        ))}
                        <TableCell>
                          <div className="flex flex-wrap gap-3">
                            {draft.handling_stage_percentages.map((value, index) => {
                              const stagePct = Number(value);
                              const calculatedSeconds =
                                Number.isFinite(resolutionMinutes) && Number.isFinite(stagePct)
                                  ? Math.round(resolutionMinutes * 60 * (stagePct / 100))
                                  : null;
                              const stageError = stageErrors[index];

                              return (
                                <div key={index} className="flex flex-col">
                                  <span className="mb-1 text-[11px] text-muted-foreground">
                                    Stage {index + 1}
                                  </span>
                                  <Input
                                    type="number"
                                    min={1}
                                    max={100}
                                    step={1}
                                    value={value}
                                    onChange={(e) => updateStage(draft.policy_id, index, e.target.value)}
                                    className="w-16"
                                    aria-invalid={!!stageError}
                                  />
                                  {stageError ? (
                                    <p className="mt-1 text-xs text-destructive">{stageError}</p>
                                  ) : (
                                    <p className="mt-1 text-xs text-muted-foreground">
                                      {calculatedSeconds != null
                                        ? formatDurationShort(calculatedSeconds)
                                        : "—"}
                                    </p>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </TableCell>
                        {(["warning_1_percentage", "warning_2_percentage"] as const).map((field) => (
                          <TableCell key={field}>
                            <Input
                              type="number"
                              min={1}
                              max={100}
                              step={1}
                              value={draft[field]}
                              onChange={(e) => updateField(draft.policy_id, field, e.target.value)}
                              className="w-20"
                              aria-invalid={!!errors[field]}
                            />
                            {errors[field] && (
                              <p className="mt-1 text-xs text-destructive">{errors[field]}</p>
                            )}
                          </TableCell>
                        ))}
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
