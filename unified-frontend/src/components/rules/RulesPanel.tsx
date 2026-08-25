"use client";

import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { PageHeader } from "@/components/layout/dashboard-shell";
import { AccessDenied, EmptyState, ErrorState } from "@/components/shared/stats";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { useAuthStore } from "@/store/auth-store";
import {
  deleteRule,
  listRules,
  reorderRule,
  setRuleEnabled,
  type RuleCategory,
  type RuleResponse,
} from "@tw/api/rules";

import { RuleBuilderDialog } from "@/components/rules/RuleBuilderDialog";
import { DistributionListsPanel } from "@/components/rules/DistributionListsPanel";
import { CATEGORY_LABELS } from "@/components/rules/ruleCatalog";

const CONDITION_FIELD_LABELS: Record<string, string> = {
  sender_email: "Sender Email",
  sender_domain: "Sender Domain",
  subject_contains: "Subject contains",
  body_contains: "Body contains",
  client: "Client",
};

function summarizeConditions(rule: RuleResponse): string {
  const parts = rule.conditions.rules.map((c) => {
    const label = CONDITION_FIELD_LABELS[c.field] ?? c.field;
    const value = Array.isArray(c.value) ? `${c.value.length} selected` : c.value;
    return `${label} ${c.operator} "${value}"`;
  });
  return parts.join(` ${rule.conditions.combinator} `) || "—";
}

function summarizeActions(rule: RuleResponse): string {
  return (
    rule.actions
      .map((a) => {
        if (a.type === "forward_to") {
          const parts: string[] = [];
          const employeeCount = (a.employee_user_ids ?? []).length;
          const listCount = (a.distribution_list_ids ?? []).length;
          if (employeeCount > 0) parts.push(`${employeeCount} employee(s)`);
          if (listCount > 0) parts.push(`${listCount} distribution list(s)`);
          return `Forward to ${parts.join(" + ") || "0 recipients"}`;
        }
        if (a.type === "create_folder") return `Create Folder "${a.folder_name}"`;
        return `Move to Folder "${a.folder_name}"`;
      })
      .join(", ") || "—"
  );
}

// Renders Mail Rules / OTP Rules as a stacked list of individual rule
// cards (rule name + Active/reorder/Edit/Delete in a header row, then
// Condition/Action as labeled, stacked fields below) rather than a
// dense generic table — easier to scan per-rule condition/action
// summaries, which are free-text and often longer than a table column
// comfortably fits. Same data/handlers as before this redesign, only
// the surrounding markup changed.
function RuleList({
  category,
  rules,
  busyRuleIds,
  onCreate,
  onEdit,
  onToggleEnabled,
  onReorder,
  onDelete,
}: {
  category: RuleCategory;
  rules: RuleResponse[];
  // Rule ids with an in-flight reorder/toggle request — their
  // controls are disabled meanwhile so a rapid double-click can't fire
  // a second, concurrent request for the same rule.
  busyRuleIds: Set<string>;
  // Backs the empty state's own contextual "+ New Rule" button —
  // distinct from the tab section header's identical button, so the
  // empty state is a complete, actionable screen on its own.
  onCreate: () => void;
  onEdit: (rule: RuleResponse) => void;
  onToggleEnabled: (rule: RuleResponse, enabled: boolean) => void;
  onReorder: (rule: RuleResponse, direction: "up" | "down") => void;
  onDelete: (rule: RuleResponse) => void;
}) {
  const ordered = useMemo(() => [...rules].sort((a, b) => a.priority - b.priority), [rules]);

  if (ordered.length === 0) {
    return (
      <EmptyState
        title={`No ${CATEGORY_LABELS[category]}s Yet`}
        description={
          category === "mail_rule"
            ? "Create a Mail Rule to automatically organize incoming email into folders."
            : "Create an OTP Rule to automatically forward one-time-passcode emails to the right people."
        }
        action={
          <Button onClick={onCreate}>
            <Plus className="mr-2 h-4 w-4" />
            New Rule
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      {ordered.map((rule, index) => {
        // can_manage is false only for a rule this viewer can see (via
        // rule:view_all) but didn't create and isn't shared on — every
        // mutation below would 403 server-side regardless, so these
        // controls are disabled rather than left clickable-but-doomed.
        const isLocked = !rule.can_manage;
        const isBusy = busyRuleIds.has(rule.rule_id);
        const lockedTitle = isLocked ? "You don't have permission to manage this rule" : undefined;

        return (
          <div key={rule.rule_id} className="rounded-lg border border-border bg-card p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-foreground">{rule.name}</p>
                {rule.stop_processing && (
                  <p className="mt-0.5 text-xs text-muted-foreground">Stops processing more rules</p>
                )}
              </div>

              <div className="flex flex-none items-center gap-3">
                <div className="flex flex-col gap-0.5">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5"
                    disabled={index === 0 || isLocked || isBusy}
                    title={lockedTitle}
                    aria-label="Move up"
                    onClick={() => onReorder(rule, "up")}
                  >
                    <ArrowUp className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5"
                    disabled={index === ordered.length - 1 || isLocked || isBusy}
                    title={lockedTitle}
                    aria-label="Move down"
                    onClick={() => onReorder(rule, "down")}
                  >
                    <ArrowDown className="h-3.5 w-3.5" />
                  </Button>
                </div>

                <Switch
                  checked={rule.is_enabled}
                  disabled={isLocked || isBusy}
                  title={lockedTitle}
                  onCheckedChange={(checked) => onToggleEnabled(rule, checked)}
                />

                <div className="flex gap-1.5">
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Edit rule"
                    disabled={isLocked}
                    title={lockedTitle}
                    onClick={() => onEdit(rule)}
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Delete rule"
                    disabled={isLocked}
                    title={lockedTitle}
                    onClick={() => onDelete(rule)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>

            <div className="mt-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Condition</p>
              <p className="mt-1 text-sm text-foreground/90">{summarizeConditions(rule)}</p>
            </div>

            <div className="mt-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Action</p>
              <p className="mt-1 text-sm text-foreground/90">{summarizeActions(rule)}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Rules lives inside Mail now (Mail → Rules is the one canonical entry
// point — see InboxPage.tsx's rulesOpen state and MailSidebar.tsx's
// Rules button) rather than a standalone /settings/rules route.
// Everything below is unchanged from that former page — only the
// breadcrumb was updated to reflect the new nesting.
export function RulesPanel({
  onFoldersMayHaveChanged,
}: {
  // Called right after a mutation that could add/rename/remove a
  // rule-managed mail folder (create/update/delete) — lets the Mail
  // page's own, separately-owned folder list (useMailInbox.folders)
  // refresh immediately instead of only on the next full remount.
  // Optional so this component still works standalone/in tests with
  // no caller wired up.
  onFoldersMayHaveChanged?: () => void;
} = {}) {
  const currentUser = useAuthStore((s) => s.user);
  const hasPermission = useAuthStore((s) => s.hasPermission);
  const { toast } = useToast();

  // null strictly means "never successfully loaded yet" — the one
  // and only signal the render below uses to decide between the
  // loading skeleton and "No Rules yet.", so a background refresh
  // (after a toggle/reorder/delete/save) never re-blanks an
  // already-populated list, and "0 rules" can never render before
  // the first real response has actually arrived.
  const [rules, setRules] = useState<RuleResponse[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [builderOpen, setBuilderOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<RuleResponse | null>(null);
  const [pendingDelete, setPendingDelete] = useState<RuleResponse | null>(null);
  // Which of the three sections is visible — Mail Rules by default.
  // Distribution Lists' own data/CRUD lives entirely inside
  // DistributionListsPanel already; this state only controls which
  // section is rendered, not any data fetching.
  const [activeTab, setActiveTab] = useState<"mail_rule" | "otp_rule" | "distribution_lists">("mail_rule");
  // Which category a brand-new "+ New Rule" click should open the
  // builder pre-selected to — set right before opening, from whichever
  // tab's own button was clicked.
  const [createCategory, setCreateCategory] = useState<RuleCategory>("mail_rule");
  // Rule ids with an in-flight reorder/toggle request — guards against
  // a rapid double-click firing a second, concurrent request for the
  // same rule (see RuleList's own use of this for disabling controls).
  const [busyRuleIds, setBusyRuleIds] = useState<Set<string>>(new Set());

  function markBusy(ruleId: string) {
    setBusyRuleIds((prev) => new Set(prev).add(ruleId));
  }

  function clearBusy(ruleId: string) {
    setBusyRuleIds((prev) => {
      const next = new Set(prev);
      next.delete(ruleId);
      return next;
    });
  }

  // The backend's real 403 detail (e.g. "You do not have access to
  // this rule.") is far more useful than a flat generic string —
  // surfacing it is what "don't hide real errors" actually means here.
  // NOTE: by the time this runs, `error` is never a raw AxiosError —
  // `@tw/api/client`'s response interceptor already unwraps every
  // rejected request into a plain `Error` whose `.message` is the
  // backend's own `detail` (falling back to `error.message` or a
  // generic string only if there was no `detail` at all). Checking
  // `axios.isAxiosError(error)` here would always be false and silently
  // swallow the real message — the same interceptor-shape mistake
  // documented in this app's own CLAUDE.md ("canceled" toast bug) and
  // already worked around correctly by useApiAction.ts's identical
  // `error instanceof Error ? error.message : ...` pattern, reused here.
  function errorDetail(error: unknown): string | undefined {
    return error instanceof Error ? error.message : undefined;
  }

  function refresh(signal?: AbortSignal) {
    listRules(signal)
      .then((data) => {
        setRules(data);
        setLoadError(null);
      })
      .catch((error) => {
        if (axios.isCancel(error)) return;
        setLoadError("Failed to load rules. Please try again.");
      });
  }

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    return () => controller.abort();
  }, []);

  if (currentUser && !hasPermission("rule:manage")) {
    return <AccessDenied message="You do not have access to Mail/OTP Rules." />;
  }

  async function handleToggleEnabled(rule: RuleResponse, enabled: boolean) {
    if (busyRuleIds.has(rule.rule_id)) return;
    markBusy(rule.rule_id);
    try {
      await setRuleEnabled(rule.rule_id, enabled);
      refresh();
    } catch (error) {
      toast({ title: "Couldn't update this rule", description: errorDetail(error), variant: "destructive" });
    } finally {
      clearBusy(rule.rule_id);
    }
  }

  async function handleReorder(rule: RuleResponse, direction: "up" | "down") {
    if (busyRuleIds.has(rule.rule_id)) return;
    markBusy(rule.rule_id);
    try {
      await reorderRule(rule.rule_id, direction);
      refresh();
    } catch (error) {
      toast({ title: "Couldn't reorder this rule", description: errorDetail(error), variant: "destructive" });
    } finally {
      clearBusy(rule.rule_id);
    }
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    try {
      await deleteRule(pendingDelete.rule_id);
      toast({ title: "Rule deleted" });
      // If the just-deleted rule happened to be open for editing,
      // close that dialog too rather than leaving it pointed at a
      // rule that no longer exists.
      if (editingRule?.rule_id === pendingDelete.rule_id) {
        setBuilderOpen(false);
        setEditingRule(null);
      }
      setPendingDelete(null);
      refresh();
      // The backend deletes the rule's own folder too, as part of the
      // same request, once no remaining rule still references it —
      // the Mail page's folder list needs to know right away, not
      // just the next time Rules happens to be closed.
      onFoldersMayHaveChanged?.();
    } catch (error) {
      toast({ title: "Couldn't delete this rule", description: errorDetail(error), variant: "destructive" });
    }
  }

  const mailRules = (rules ?? []).filter((r) => r.category === "mail_rule");
  const otpRules = (rules ?? []).filter((r) => r.category === "otp_rule");

  return (
    <div className="space-y-8 px-6 py-6 md:px-8">
      <Breadcrumbs
        items={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Mail", href: "/dashboard/inbox" },
          { label: "Rules" },
        ]}
      />

      <PageHeader
        title="Rules"
        description="Automatically organize incoming mail and forward OTP emails whenever a new email arrives — Mail Rules and OTP Rules both trigger on Email Received."
      />

      {loadError && <ErrorState message={loadError} />}

      {!loadError && (
        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
          {/* Only this strip scrolls horizontally on a narrow viewport
              — never the whole page — if the three labels don't fit. */}
          <div className="overflow-x-auto">
            <TabsList>
              <TabsTrigger value="mail_rule">Mail Rules</TabsTrigger>
              <TabsTrigger value="otp_rule">OTP Rules</TabsTrigger>
              <TabsTrigger value="distribution_lists">Distribution Lists</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="mail_rule">
            <Card>
              <CardHeader className="flex flex-col gap-3 space-y-0 sm:flex-row sm:items-center sm:justify-between">
                <CardTitle className="text-lg font-semibold">Mail Rules</CardTitle>
                <Button
                  onClick={() => {
                    setEditingRule(null);
                    setCreateCategory("mail_rule");
                    setBuilderOpen(true);
                  }}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  New Rule
                </Button>
              </CardHeader>
              <CardContent>
                {/* Only the true first load (rules === null, nothing to
                    show yet at all) renders the skeleton — a later
                    background refresh (toggle/reorder/delete/save)
                    keeps showing the last-known list instead of
                    blanking it out, and "No Mail Rules yet." only ever
                    renders once real data has actually arrived, never
                    while a request is still in flight. */}
                {rules === null ? (
                  <div className="space-y-3">
                    <Skeleton className="h-20 w-full rounded-lg" />
                    <Skeleton className="h-20 w-full rounded-lg" />
                  </div>
                ) : (
                  <RuleList
                    category="mail_rule"
                    rules={mailRules}
                    onCreate={() => {
                      setEditingRule(null);
                      setCreateCategory("mail_rule");
                      setBuilderOpen(true);
                    }}
                    onEdit={(rule) => {
                      setEditingRule(rule);
                      setBuilderOpen(true);
                    }}
                    busyRuleIds={busyRuleIds}
                    onToggleEnabled={handleToggleEnabled}
                    onReorder={handleReorder}
                    onDelete={setPendingDelete}
                  />
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="otp_rule">
            <Card>
              <CardHeader className="flex flex-col gap-3 space-y-0 sm:flex-row sm:items-center sm:justify-between">
                <CardTitle className="text-lg font-semibold">OTP Rules</CardTitle>
                <Button
                  onClick={() => {
                    setEditingRule(null);
                    setCreateCategory("otp_rule");
                    setBuilderOpen(true);
                  }}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  New Rule
                </Button>
              </CardHeader>
              <CardContent>
                {rules === null ? (
                  <div className="space-y-3">
                    <Skeleton className="h-20 w-full rounded-lg" />
                    <Skeleton className="h-20 w-full rounded-lg" />
                  </div>
                ) : (
                  <RuleList
                    category="otp_rule"
                    rules={otpRules}
                    onCreate={() => {
                      setEditingRule(null);
                      setCreateCategory("otp_rule");
                      setBuilderOpen(true);
                    }}
                    onEdit={(rule) => {
                      setEditingRule(rule);
                      setBuilderOpen(true);
                    }}
                    busyRuleIds={busyRuleIds}
                    onToggleEnabled={handleToggleEnabled}
                    onReorder={handleReorder}
                    onDelete={setPendingDelete}
                  />
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="distribution_lists">
            <DistributionListsPanel />
          </TabsContent>
        </Tabs>
      )}

      <RuleBuilderDialog
        open={builderOpen}
        onOpenChange={setBuilderOpen}
        rule={editingRule}
        defaultCategory={createCategory}
        onSaved={() => {
          refresh();
          // A create/update can add a brand-new folder-action target
          // (eagerly created server-side the moment the rule is
          // saved) or change which folder an existing action names —
          // the Mail page's folder list should reflect that right
          // away too.
          onFoldersMayHaveChanged?.();
        }}
      />

      <AlertDialog open={pendingDelete != null} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete "{pendingDelete?.name}"?</AlertDialogTitle>
            <AlertDialogDescription>
              This rule will stop running immediately. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
