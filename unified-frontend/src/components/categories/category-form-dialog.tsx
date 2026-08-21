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
import { categoryService } from "@/services";
import { Category } from "@/types";
import { listInternalNoteRecipients } from "@tw/api/interaction";

const TEAM_LEAD_ROLE_NAME = "Team Lead";
const STAFF_ROLE_NAME = "Staff";

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
  const [teamLeadIds, setTeamLeadIds] = useState<string[]>([]);
  const [staffIds, setStaffIds] = useState<string[]>([]);

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

  useEffect(() => {
    if (!open) return;
    setCategoryName(category?.category_name ?? "");
    if (mode === "create") {
      setTeamLeadIds([]);
      setStaffIds([]);
    }
  }, [open, category, mode]);

  useEffect(() => {
    if (mode !== "edit" || !membersQuery.data) return;
    const members = membersQuery.data.members;
    setTeamLeadIds(members.filter((m) => m.role_name === TEAM_LEAD_ROLE_NAME).map((m) => m.user_id));
    setStaffIds(members.filter((m) => m.role_name === STAFF_ROLE_NAME).map((m) => m.user_id));
  }, [mode, membersQuery.data]);

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

  const pickersUnavailable = recipientsQuery.isError || (mode === "edit" && membersQuery.isError);

  const mutation = useMutation({
    mutationFn: async () => {
      const name = categoryName.trim();
      const memberIds = [...teamLeadIds, ...staffIds];

      if (mode === "create") {
        return categoryService.create({ category_name: name, user_ids: memberIds });
      }

      if (name !== category!.category_name) {
        await categoryService.update(category!.category_id, { category_name: name });
      }
      return categoryService.setMembers(category!.category_id, memberIds);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories-options"] });
      if (category) {
        queryClient.invalidateQueries({ queryKey: ["category-members", category.category_id] });
      }
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
