"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { UserMultiSelect } from "@/components/users/UserMultiSelect";
import { useToast } from "@/hooks/use-toast";
import { getApiErrorMessage } from "@/lib/utils";
import { categoryService, reportingManagerService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { Category } from "@/types";
import { listInternalNoteRecipients } from "@tw/api/interaction";

const TEAM_LEAD_ROLE_NAME = "Team Lead";
const STAFF_ROLE_NAME = "Staff";
const ACCOUNT_MANAGER_ROLE_NAME = "Account Manager";

interface CategoryFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Omit (or null) for create mode; pass the category being edited to
  // switch to edit mode — rename + add/remove Team Leads/Staff.
  category?: Category | null;
}

// Candidates are sourced from the same genuinely unscoped endpoint the
// Internal Note "To" picker and the Rules "Search Employees" picker
// already use (GET /tickets/internal-notes/recipients) — every active
// user, any role, company-wide. RBAC's own GET /users/GET /roles is
// hierarchy-scoped (an Account Manager only sees their own reporting
// subtree) and was the root cause of an earlier version of this form
// showing an incomplete/empty Team Lead-Staff picker — see root
// CLAUDE.md's "Internal Note recipients" and "Rules 'Search
// Employees' picker" sections for the two prior times this exact bug
// was hit and fixed the same way.
export function CategoryFormDialog({ open, onOpenChange, category }: CategoryFormDialogProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const mode: "create" | "edit" = category ? "edit" : "create";

  const [categoryName, setCategoryName] = useState("");
  const [inboxEmail, setInboxEmail] = useState("");
  const [teamLeadIds, setTeamLeadIds] = useState<string[]>([]);
  const [staffIds, setStaffIds] = useState<string[]>([]);
  const [accountManagerIds, setAccountManagerIds] = useState<string[]>([]);
  const [originalAccountManagerId, setOriginalAccountManagerId] = useState<string | null>(null);
  const [originalMappingId, setOriginalMappingId] = useState<string | null>(null);

  const hasPermission = useAuthStore((s) => s.hasPermission);
  const canManageAccountManager = hasPermission("org:manage_reporting_managers");

  const recipientsQuery = useQuery({
    queryKey: ["category-picker-recipients"],
    queryFn: () => listInternalNoteRecipients(),
    enabled: open,
  });

  const membersQuery = useQuery({
    queryKey: ["category-members", category?.category_id],
    queryFn: () => categoryService.getMembers(category!.category_id),
    enabled: open && mode === "edit" && !!category,
  });

  // Reads the existing Reporting Manager mapping for this category —
  // gated on the permission this dialog otherwise never needs, so a
  // user who can't manage Reporting Managers never fires a doomed 403.
  const reportingManagerQuery = useQuery({
    queryKey: ["category-reporting-manager", category?.category_id],
    queryFn: () => reportingManagerService.list({ categoryId: category!.category_id }),
    enabled: open && mode === "edit" && !!category && canManageAccountManager,
  });

  useEffect(() => {
    if (!open) return;
    setCategoryName(category?.category_name ?? "");
    setInboxEmail(category?.inbox_email ?? "");
    if (mode === "create") {
      setTeamLeadIds([]);
      setStaffIds([]);
      setAccountManagerIds([]);
      setOriginalAccountManagerId(null);
      setOriginalMappingId(null);
    }
  }, [open, category, mode]);

  useEffect(() => {
    if (mode !== "edit" || !membersQuery.data) return;
    const members = membersQuery.data.members;
    setTeamLeadIds(members.filter((m) => m.role_name === TEAM_LEAD_ROLE_NAME).map((m) => m.user_id));
    setStaffIds(members.filter((m) => m.role_name === STAFF_ROLE_NAME).map((m) => m.user_id));
  }, [mode, membersQuery.data]);

  useEffect(() => {
    if (mode !== "edit" || !reportingManagerQuery.data) return;
    // A category can genuinely have more than one Reporting Manager
    // (the underlying mapping is many-to-many) but this dialog only
    // ever shows/manages the first one — never touch the rest.
    const first = reportingManagerQuery.data[0] ?? null;
    setAccountManagerIds(first ? [first.account_manager_id] : []);
    setOriginalAccountManagerId(first ? first.account_manager_id : null);
    setOriginalMappingId(first ? first.id : null);
  }, [mode, reportingManagerQuery.data]);

  const allCandidates = recipientsQuery.data ?? [];
  const teamLeadOptions = useMemo(
    () =>
      allCandidates
        .filter((u) => u.role_name === TEAM_LEAD_ROLE_NAME)
        .map((u) => ({ user_id: u.user_id, name: u.name, email: u.email })),
    [allCandidates]
  );
  const staffOptions = useMemo(
    () =>
      allCandidates
        .filter((u) => u.role_name === STAFF_ROLE_NAME)
        .map((u) => ({ user_id: u.user_id, name: u.name, email: u.email })),
    [allCandidates]
  );
  const accountManagerOptions = useMemo(
    () =>
      allCandidates
        .filter((u) => u.role_name === ACCOUNT_MANAGER_ROLE_NAME)
        .map((u) => ({ user_id: u.user_id, name: u.name, email: u.email })),
    [allCandidates]
  );

  function handleAccountManagerChange(ids: string[]) {
    // Cap to a single selection — picking a second person replaces the
    // first rather than adding to it; UserMultiSelect itself has no
    // single-select mode, so this is enforced here instead.
    setAccountManagerIds(ids.slice(-1));
  }

  const pickersUnavailable = recipientsQuery.isError || (mode === "edit" && membersQuery.isError);

  const mutation = useMutation({
    mutationFn: async () => {
      const name = categoryName.trim();
      const email = inboxEmail.trim() || null;
      const memberIds = [...teamLeadIds, ...staffIds];
      let categoryId: string;

      if (mode === "create") {
        const created = await categoryService.create({ category_name: name, user_ids: memberIds, inbox_email: email });
        categoryId = created.category_id;
      } else {
        if (name !== category!.category_name || email !== (category!.inbox_email ?? null)) {
          await categoryService.update(category!.category_id, { category_name: name, inbox_email: email });
        }
        await categoryService.setMembers(category!.category_id, memberIds);
        categoryId = category!.category_id;
      }

      // Account Manager reconciliation is a separate concern from the
      // category/members save above, and must never fail or roll it
      // back — a permission-denied AM change still leaves the rest of
      // the save intact, surfaced as its own toast instead.
      const nextAccountManagerId = accountManagerIds[0] ?? null;
      if (nextAccountManagerId !== originalAccountManagerId) {
        try {
          if (originalMappingId) {
            await reportingManagerService.revoke(originalMappingId);
          }
          if (nextAccountManagerId) {
            await reportingManagerService.assign({
              account_manager_id: nextAccountManagerId,
              category_id: categoryId,
            });
          }
        } catch (amError) {
          toast({
            variant: "destructive",
            title: "Account Manager not updated",
            description: getApiErrorMessage(
              amError,
              "Category saved, but you don't have permission to change the Account Manager."
            ),
          });
        }
      }

      return categoryId;
    },
    onSuccess: (categoryId) => {
      queryClient.invalidateQueries({ queryKey: ["categories-options"] });
      if (category) {
        queryClient.invalidateQueries({ queryKey: ["category-members", category.category_id] });
      }
      queryClient.invalidateQueries({ queryKey: ["category-reporting-manager", categoryId] });
      toast({
        title: mode === "create" ? "Category created" : "Category updated",
        description:
          mode === "create"
            ? `"${categoryName.trim()}" is now available everywhere categories are used.`
            : "Changes have been saved.",
      });
      onOpenChange(false);
    },
    onError: (error) => {
      toast({
        variant: "destructive",
        title: mode === "create" ? "Failed to create category" : "Failed to update category",
        description: getApiErrorMessage(error, "Please check the form and try again."),
      });
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{mode === "create" ? "Create Category" : "Edit Category"}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="category-name">Category Name</Label>
            <Input
              id="category-name"
              placeholder="PATIENTOUTREACH"
              value={categoryName}
              onChange={(e) => setCategoryName(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="category-inbox-email">Category Shared Inbox (optional)</Label>
            <Input
              id="category-inbox-email"
              type="email"
              placeholder="apm@company.com"
              value={inboxEmail}
              onChange={(e) => setInboxEmail(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Mail sent to this address is routed by category, not by client — it maps to the
              Account Manager(s) assigned as Reporting Manager for this category.
            </p>
          </div>

          {pickersUnavailable ? (
            <p className="text-sm text-destructive">
              {getApiErrorMessage(
                recipientsQuery.error ?? membersQuery.error,
                "Could not load the Team Lead/Staff picker. Please try again."
              )}
            </p>
          ) : (
            <>
              <div className="space-y-2">
                <Label>Account Manager</Label>
                <UserMultiSelect
                  users={accountManagerOptions}
                  selectedIds={accountManagerIds}
                  onChange={handleAccountManagerChange}
                  placeholder={recipientsQuery.isLoading ? "Loading account managers..." : "Search account managers…"}
                />
                <p className="text-xs text-muted-foreground">
                  Optional — the Account Manager assigned as Reporting Manager for this category.
                  {!canManageAccountManager && " You don't have permission to change this."}
                </p>
              </div>

              <div className="space-y-2">
                <Label>Team Leads</Label>
                <UserMultiSelect
                  users={teamLeadOptions}
                  selectedIds={teamLeadIds}
                  onChange={setTeamLeadIds}
                  placeholder={recipientsQuery.isLoading ? "Loading team leads..." : "Search team leads…"}
                />
                <p className="text-xs text-muted-foreground">
                  Optional — leave empty if none should be assigned.
                </p>
              </div>

              <div className="space-y-2">
                <Label>Staff</Label>
                <UserMultiSelect
                  users={staffOptions}
                  selectedIds={staffIds}
                  onChange={setStaffIds}
                  placeholder={recipientsQuery.isLoading ? "Loading staff..." : "Search staff…"}
                />
                <p className="text-xs text-muted-foreground">
                  Optional — leave empty if none should be assigned.
                </p>
              </div>
            </>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!categoryName.trim() || mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {mode === "create" ? "Create Category" : "Save Changes"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
