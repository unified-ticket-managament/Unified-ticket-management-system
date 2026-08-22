"use client";

import { useEffect, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import {
  addDistributionListMember,
  createDistributionList,
  removeDistributionListMember,
  updateDistributionList,
  type DistributionListResponse,
} from "@tw/api/distributionLists";

import { EmployeeMultiSelect } from "./EmployeeMultiSelect";

interface DistributionListDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  distributionList: DistributionListResponse | null;
  onSaved: () => void;
}

// Create/Edit form for a Distribution List. Reuses EmployeeMultiSelect
// as-is for member selection (it already fetches every active
// internal user and manages a string[] of user_ids — exactly what
// membership needs; a DL's own members are always users, never other
// DLs, so no DistributionListMultiSelect involvement here). Edit
// diffs the member selection against the list's original membership
// and calls the granular add/remove-member endpoints per changed
// member (never a bulk replace) — this is what gives each membership
// change its own precise MEMBER_ADDED/MEMBER_REMOVED audit event,
// matching the spec's exact CRUD operation list.
export function DistributionListDialog({
  open,
  onOpenChange,
  distributionList,
  onSaved,
}: DistributionListDialogProps) {
  const { toast } = useToast();
  const isEditing = distributionList != null;

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [memberIds, setMemberIds] = useState<string[]>([]);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setName(distributionList?.name ?? "");
      setDescription(distributionList?.description ?? "");
      setMemberIds(distributionList?.members.map((m) => m.user_id) ?? []);
    }
  }, [open, distributionList]);

  const canSave = name.trim().length > 0 && memberIds.length > 0;

  async function handleSave() {
    if (!canSave || isSaving) return;
    setIsSaving(true);
    try {
      if (isEditing && distributionList) {
        await updateDistributionList(distributionList.distribution_list_id, {
          name: name.trim(),
          description: description.trim() || null,
          is_active: distributionList.is_active,
        });

        const originalIds = new Set(distributionList.members.map((m) => m.user_id));
        const nextIds = new Set(memberIds);
        const toAdd = memberIds.filter((id) => !originalIds.has(id));
        const toRemove = [...originalIds].filter((id) => !nextIds.has(id));

        for (const userId of toAdd) {
          await addDistributionListMember(distributionList.distribution_list_id, userId);
        }
        for (const userId of toRemove) {
          await removeDistributionListMember(distributionList.distribution_list_id, userId);
        }

        toast({ title: "Distribution list updated" });
      } else {
        await createDistributionList({
          name: name.trim(),
          description: description.trim() || null,
          member_user_ids: memberIds,
        });
        toast({ title: "Distribution list created" });
      }
      onOpenChange(false);
      onSaved();
    } catch (error: any) {
      toast({
        title: error?.response?.data?.detail ?? "Couldn't save this distribution list",
        variant: "destructive",
      });
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit Distribution List" : "New Distribution List"}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-semibold text-muted-foreground">
              Group Name
            </label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. APM Support Team"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-semibold text-muted-foreground">
              Description
            </label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional"
              rows={2}
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-semibold text-muted-foreground">
              Members
            </label>
            <EmployeeMultiSelect selectedIds={memberIds} onChange={setMemberIds} />
            {memberIds.length === 0 && (
              <p className="mt-1 text-[11px] text-destructive">
                At least one active member is required.
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={!canSave || isSaving}>
            {isSaving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
