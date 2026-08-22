"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { listMailFolders } from "@tw/api/mailFolder";
import type { MailFolder } from "@tw/types";
import type { RuleActionItem, RuleActionType, RuleCategory } from "@tw/api/rules";

import { ACTION_TYPES_BY_CATEGORY } from "./ruleCatalog";
import { EmployeeMultiSelect } from "./EmployeeMultiSelect";
import { DistributionListMultiSelect } from "@tw/components/common/DistributionListMultiSelect";

interface ActionRowProps {
  category: RuleCategory;
  action: RuleActionItem;
  onChange: (action: RuleActionItem) => void;
  onRemove: () => void;
}

export function ActionRow({ category, action, onChange, onRemove }: ActionRowProps) {
  const actionTypes = ACTION_TYPES_BY_CATEGORY[category];
  const [existingFolders, setExistingFolders] = useState<MailFolder[]>([]);

  useEffect(() => {
    if (action.type === "create_folder" || action.type === "move_to_folder") {
      listMailFolders().then(setExistingFolders).catch(() => setExistingFolders([]));
    }
  }, [action.type]);

  function setType(type: RuleActionType) {
    if (type === "forward_to") {
      onChange({ type, employee_user_ids: [], distribution_list_ids: [] });
    } else {
      onChange({ type, folder_name: "" });
    }
  }

  return (
    <div className="flex flex-wrap items-start gap-2 rounded-lg border border-border p-3">
      <div className="w-full sm:w-44">
        <Select value={action.type} onValueChange={(v) => setType(v as RuleActionType)}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {actionTypes.map((a) => (
              <SelectItem key={a.value} value={a.value}>
                {a.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="min-w-[220px] flex-1 space-y-2">
        {action.type === "forward_to" ? (
          <>
            <EmployeeMultiSelect
              selectedIds={action.employee_user_ids ?? []}
              onChange={(ids) => onChange({ ...action, employee_user_ids: ids })}
            />
            <DistributionListMultiSelect
              label="Or Forward To Distribution Lists"
              selectedIds={action.distribution_list_ids ?? []}
              onChange={(ids) => onChange({ ...action, distribution_list_ids: ids })}
            />
          </>
        ) : (
          <>
            <Input
              placeholder="Folder name…"
              list="existing-mail-folders"
              value={action.folder_name ?? ""}
              onChange={(e) => onChange({ ...action, folder_name: e.target.value })}
            />
            <datalist id="existing-mail-folders">
              {existingFolders.map((f) => (
                <option key={f.folder_id} value={f.name} />
              ))}
            </datalist>
          </>
        )}
      </div>

      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="shrink-0"
        aria-label="Remove action"
        onClick={onRemove}
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  );
}
