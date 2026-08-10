"use client";

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
import type { RuleCategory, RuleConditionItem } from "@tw/api/rules";

import { CONDITION_FIELDS_BY_CATEGORY } from "./ruleCatalog";
import { ClientPicker } from "./ClientPicker";

interface ConditionRowProps {
  category: RuleCategory;
  condition: RuleConditionItem;
  onChange: (condition: RuleConditionItem) => void;
  onRemove: () => void;
}

export function ConditionRow({ category, condition, onChange, onRemove }: ConditionRowProps) {
  const fields = CONDITION_FIELDS_BY_CATEGORY[category];
  // "client" is the field value shared by both the single- and multi-
  // select catalog entries — resolve to whichever entry actually
  // appears in this category's own list.
  const fieldDef = fields.find((f) => f.value === condition.field) ?? fields[0];

  function setField(fieldValue: string) {
    const next = fields.find((f) => f.value === fieldValue) ?? fields[0];
    onChange({
      field: next.value,
      operator: next.fixedOperator ?? "equals",
      value: next.kind === "text" ? "" : [],
    });
  }

  return (
    <div className="flex flex-wrap items-start gap-2 rounded-lg border border-border p-3">
      <div className="w-full sm:w-44">
        <Select value={fieldDef.value} onValueChange={setField}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {fields.map((f) => (
              <SelectItem key={f.label} value={f.value}>
                {f.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {!fieldDef.fixedOperator && (
        <div className="w-full sm:w-36">
          <Select
            value={condition.operator}
            onValueChange={(operator) =>
              onChange({ ...condition, operator: operator as RuleConditionItem["operator"] })
            }
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="equals">equals</SelectItem>
              <SelectItem value="contains">contains</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      <div className="min-w-[200px] flex-1">
        {fieldDef.kind === "text" ? (
          <Input
            placeholder="Value…"
            value={typeof condition.value === "string" ? condition.value : ""}
            onChange={(e) => onChange({ ...condition, value: e.target.value })}
          />
        ) : (
          <ClientPicker
            multiple={fieldDef.kind === "client-multi"}
            selectedIds={Array.isArray(condition.value) ? condition.value : []}
            onChange={(ids) => onChange({ ...condition, value: ids })}
          />
        )}
      </div>

      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="shrink-0"
        aria-label="Remove condition"
        onClick={onRemove}
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  );
}
