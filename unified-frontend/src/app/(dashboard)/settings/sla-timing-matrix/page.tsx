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
import { ROLE_NAMES } from "@/lib/role-access";
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
  | "handling_sla_percentage"
  | "warning_1_percentage"
  | "warning_2_percentage";

const MINUTE_FIELDS: EditableField[] = [
  "first_response_target_minutes",
  "resolution_target_minutes",
  "escalation_ack_target_minutes",
];
const PERCENTAGE_FIELDS: EditableField[] = [
  "handling_sla_percentage",
  "warning_1_percentage",
  "warning_2_percentage",
];

type Draft = Record<EditableField, string> & { policy_id: string; priority: TicketPriority };
type Errors = Partial<Record<EditableField, string>>;

function toDraft(policy: SLAPolicyResponse): Draft {
  return {
    policy_id: policy.policy_id,
    priority: policy.priority,
    first_response_target_minutes: String(policy.first_response_target_minutes),
    resolution_target_minutes: String(policy.resolution_target_minutes),
    escalation_ack_target_minutes: String(policy.escalation_ack_target_minutes),
    handling_sla_percentage: String(policy.handling_sla_percentage),
    warning_1_percentage: String(policy.warning_1_percentage),
    warning_2_percentage: String(policy.warning_2_percentage),
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

function validateDraft(draft: Draft): Errors {
  const errors: Errors = {};
  for (const field of [...MINUTE_FIELDS, ...PERCENTAGE_FIELDS]) {
    const message = validateField(field, draft[field]);
    if (message) errors[field] = message;
  }
  return errors;
}

function draftDiffersFromOriginal(draft: Draft, original: SLAPolicyResponse): boolean {
  return [...MINUTE_FIELDS, ...PERCENTAGE_FIELDS].some(
    (field) => draft[field] !== String(original[field])
  );
}

export default function SlaTimingMatrixPage() {
  const currentUser = useAuthStore((s) => s.user);
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
        setPolicies(data);
        setDrafts(data.map(toDraft));
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

  if (currentUser && currentUser.role !== ROLE_NAMES.SUPER_ADMIN) {
    return <AccessDenied message="Only Super Admin can access the SLA Timing Matrix." />;
  }

  function updateField(policyId: string, field: EditableField, value: string) {
    setDrafts((prev) =>
      prev.map((d) => (d.policy_id === policyId ? { ...d, [field]: value } : d))
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
              handling_sla_percentage: Number(draft.handling_sla_percentage),
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
        description="Configure First Response, Resolution, escalation, and warning timing per priority. Changes apply to tickets going forward — already-running ticket timers keep their own snapshotted values."
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
                    <TableHead>Handling SLA (%)</TableHead>
                    <TableHead>Calculated Handling SLA</TableHead>
                    <TableHead>Warning 1 (%)</TableHead>
                    <TableHead>Warning 2 (%)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {orderedDrafts.map((draft) => {
                    const errors = errorsByPolicyId.get(draft.policy_id) ?? {};
                    const resolutionMinutes = Number(draft.resolution_target_minutes);
                    const handlingPct = Number(draft.handling_sla_percentage);
                    const calculatedSeconds =
                      Number.isFinite(resolutionMinutes) && Number.isFinite(handlingPct)
                        ? Math.round(resolutionMinutes * 60 * (handlingPct / 100))
                        : null;

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
                          <Input
                            type="number"
                            min={1}
                            max={100}
                            step={1}
                            value={draft.handling_sla_percentage}
                            onChange={(e) =>
                              updateField(draft.policy_id, "handling_sla_percentage", e.target.value)
                            }
                            className="w-20"
                            aria-invalid={!!errors.handling_sla_percentage}
                          />
                          {errors.handling_sla_percentage && (
                            <p className="mt-1 text-xs text-destructive">
                              {errors.handling_sla_percentage}
                            </p>
                          )}
                        </TableCell>
                        <TableCell>
                          <span className="text-sm font-medium text-muted-foreground">
                            {calculatedSeconds != null ? formatDurationShort(calculatedSeconds) : "—"}
                          </span>
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
