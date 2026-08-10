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
import { AccessDenied, ErrorState } from "@/components/shared/stats";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
        if (a.type === "forward_to") return `Forward to ${(a.employee_user_ids ?? []).length} employee(s)`;
        if (a.type === "create_folder") return `Create Folder "${a.folder_name}"`;
        return `Move to Folder "${a.folder_name}"`;
      })
      .join(", ") || "—"
  );
}

function RuleTable({
  category,
  rules,
  onEdit,
  onToggleEnabled,
  onReorder,
  onDelete,
}: {
  category: RuleCategory;
  rules: RuleResponse[];
  onEdit: (rule: RuleResponse) => void;
  onToggleEnabled: (rule: RuleResponse, enabled: boolean) => void;
  onReorder: (rule: RuleResponse, direction: "up" | "down") => void;
  onDelete: (rule: RuleResponse) => void;
}) {
  const ordered = useMemo(() => [...rules].sort((a, b) => a.priority - b.priority), [rules]);

  if (ordered.length === 0) {
    return <p className="px-6 py-8 text-sm text-muted-foreground">No {CATEGORY_LABELS[category]}s yet.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-10" />
          <TableHead>Name</TableHead>
          <TableHead>Conditions</TableHead>
          <TableHead>Actions</TableHead>
          <TableHead className="w-20">Enabled</TableHead>
          <TableHead className="w-28" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {ordered.map((rule, index) => (
          <TableRow key={rule.rule_id}>
            <TableCell>
              <div className="flex flex-col">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-5 w-5"
                  disabled={index === 0}
                  aria-label="Move up"
                  onClick={() => onReorder(rule, "up")}
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-5 w-5"
                  disabled={index === ordered.length - 1}
                  aria-label="Move down"
                  onClick={() => onReorder(rule, "down")}
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                </Button>
              </div>
            </TableCell>
            <TableCell className="font-medium">
              {rule.name}
              {rule.stop_processing && (
                <p className="text-xs text-muted-foreground">Stops processing more rules</p>
              )}
            </TableCell>
            <TableCell className="max-w-xs text-sm text-muted-foreground">
              {summarizeConditions(rule)}
            </TableCell>
            <TableCell className="max-w-xs text-sm text-muted-foreground">
              {summarizeActions(rule)}
            </TableCell>
            <TableCell>
              <Switch
                checked={rule.is_enabled}
                onCheckedChange={(checked) => onToggleEnabled(rule, checked)}
              />
            </TableCell>
            <TableCell>
              <div className="flex justify-end gap-1">
                <Button variant="ghost" size="icon" aria-label="Edit rule" onClick={() => onEdit(rule)}>
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" aria-label="Delete rule" onClick={() => onDelete(rule)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export default function RulesPage() {
  const currentUser = useAuthStore((s) => s.user);
  const hasPermission = useAuthStore((s) => s.hasPermission);
  const { toast } = useToast();

  const [rules, setRules] = useState<RuleResponse[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [builderOpen, setBuilderOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<RuleResponse | null>(null);
  const [pendingDelete, setPendingDelete] = useState<RuleResponse | null>(null);

  function refresh(signal?: AbortSignal) {
    setIsLoading(true);
    listRules(signal)
      .then((data) => {
        setRules(data);
        setLoadError(null);
      })
      .catch((error) => {
        if (axios.isCancel(error)) return;
        setLoadError("Failed to load rules. Please try again.");
      })
      .finally(() => setIsLoading(false));
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
    try {
      await setRuleEnabled(rule.rule_id, enabled);
      refresh();
    } catch {
      toast({ title: "Couldn't update this rule", variant: "destructive" });
    }
  }

  async function handleReorder(rule: RuleResponse, direction: "up" | "down") {
    try {
      await reorderRule(rule.rule_id, direction);
      refresh();
    } catch {
      toast({ title: "Couldn't reorder this rule", variant: "destructive" });
    }
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    try {
      await deleteRule(pendingDelete.rule_id);
      toast({ title: "Rule deleted" });
      setPendingDelete(null);
      refresh();
    } catch {
      toast({ title: "Couldn't delete this rule", variant: "destructive" });
    }
  }

  const mailRules = (rules ?? []).filter((r) => r.category === "mail_rule");
  const otpRules = (rules ?? []).filter((r) => r.category === "otp_rule");

  return (
    <div className="space-y-6">
      <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "Rules" }]} />

      <PageHeader
        title="Rules"
        description="Automatically organize incoming mail and forward OTP emails whenever a new email arrives — Mail Rules and OTP Rules both trigger on Email Received."
        action={
          <Button
            onClick={() => {
              setEditingRule(null);
              setBuilderOpen(true);
            }}
          >
            <Plus className="mr-2 h-4 w-4" />
            New Rule
          </Button>
        }
      />

      {loadError && <ErrorState message={loadError} />}

      {!loadError && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Mail Rules</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {isLoading ? (
                <div className="space-y-3 p-6">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              ) : (
                <RuleTable
                  category="mail_rule"
                  rules={mailRules}
                  onEdit={(rule) => {
                    setEditingRule(rule);
                    setBuilderOpen(true);
                  }}
                  onToggleEnabled={handleToggleEnabled}
                  onReorder={handleReorder}
                  onDelete={setPendingDelete}
                />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>OTP Rules</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {isLoading ? (
                <div className="space-y-3 p-6">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              ) : (
                <RuleTable
                  category="otp_rule"
                  rules={otpRules}
                  onEdit={(rule) => {
                    setEditingRule(rule);
                    setBuilderOpen(true);
                  }}
                  onToggleEnabled={handleToggleEnabled}
                  onReorder={handleReorder}
                  onDelete={setPendingDelete}
                />
              )}
            </CardContent>
          </Card>
        </>
      )}

      <RuleBuilderDialog
        open={builderOpen}
        onOpenChange={setBuilderOpen}
        rule={editingRule}
        onSaved={refresh}
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
