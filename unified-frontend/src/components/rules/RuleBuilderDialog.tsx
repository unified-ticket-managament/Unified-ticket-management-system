"use client";

import { useEffect, useState } from "react";
import axios from "axios";
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";
import {
  createRule,
  updateRule,
  type RuleActionItem,
  type RuleCategory,
  type RuleConditionGroup,
  type RuleConditionItem,
  type RuleResponse,
} from "@tw/api/rules";

import { ActionRow } from "./ActionRow";
import { ConditionRow } from "./ConditionRow";
import { ACTION_TYPES_BY_CATEGORY, CATEGORY_LABELS, CONDITION_FIELDS_BY_CATEGORY } from "./ruleCatalog";

interface RuleBuilderDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Present when editing an existing rule — category becomes fixed
  // (changing category would invalidate every condition/action
  // already configured for the old one).
  rule: RuleResponse | null;
  onSaved: () => void;
}

function defaultCondition(category: RuleCategory): RuleConditionItem {
  const field = CONDITION_FIELDS_BY_CATEGORY[category][0];
  const value = field.kind === "text" ? "" : field.kind === "boolean" ? true : [];
  return { field: field.value, operator: field.fixedOperator ?? "equals", value };
}

function defaultAction(category: RuleCategory): RuleActionItem {
  const actionType = ACTION_TYPES_BY_CATEGORY[category][0];
  return actionType.value === "forward_to"
    ? { type: "forward_to", employee_user_ids: [] }
    : { type: actionType.value, folder_name: "" };
}

function emptyGroup(): RuleConditionGroup {
  return { combinator: "AND", rules: [] };
}

export function RuleBuilderDialog({ open, onOpenChange, rule, onSaved }: RuleBuilderDialogProps) {
  const { toast } = useToast();
  const isEditing = rule != null;

  const [category, setCategory] = useState<RuleCategory>("mail_rule");
  const [name, setName] = useState("");
  const [isEnabled, setIsEnabled] = useState(true);
  const [conditions, setConditions] = useState<RuleConditionGroup>(emptyGroup());
  const [exceptions, setExceptions] = useState<RuleConditionGroup>(emptyGroup());
  const [actions, setActions] = useState<RuleActionItem[]>([]);
  const [stopProcessing, setStopProcessing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  // Re-seed local state every time the dialog opens, for either a
  // fresh "New Rule" (rule === null) or editing a specific one.
  useEffect(() => {
    if (!open) return;
    if (rule) {
      setCategory(rule.category);
      setName(rule.name);
      setIsEnabled(rule.is_enabled);
      setConditions(rule.conditions);
      setExceptions(rule.exceptions);
      setActions(rule.actions);
      setStopProcessing(rule.stop_processing);
    } else {
      setCategory("mail_rule");
      setName("");
      setIsEnabled(true);
      setConditions({ combinator: "AND", rules: [defaultCondition("mail_rule")] });
      setExceptions(emptyGroup());
      setActions([]);
      setStopProcessing(false);
    }
  }, [open, rule]);

  function handleCategoryChange(next: RuleCategory) {
    setCategory(next);
    setConditions({ combinator: "AND", rules: [defaultCondition(next)] });
    setExceptions(emptyGroup());
    setActions([]);
  }

  function updateConditionAt(list: RuleConditionGroup, index: number, next: RuleConditionItem) {
    return { ...list, rules: list.rules.map((c, i) => (i === index ? next : c)) };
  }

  function removeConditionAt(list: RuleConditionGroup, index: number) {
    return { ...list, rules: list.rules.filter((_, i) => i !== index) };
  }

  const isValid =
    name.trim().length > 0 &&
    conditions.rules.length > 0 &&
    conditions.rules.every((c) =>
      Array.isArray(c.value)
        ? c.value.length > 0
        : typeof c.value === "boolean"
          ? true
          : c.value.trim().length > 0
    ) &&
    actions.length > 0 &&
    actions.every((a) =>
      a.type === "forward_to" ? (a.employee_user_ids ?? []).length > 0 : !!a.folder_name?.trim()
    );

  async function handleSave() {
    if (!isValid) return;
    setIsSaving(true);
    try {
      if (isEditing && rule) {
        await updateRule(rule.rule_id, {
          name: name.trim(),
          is_enabled: isEnabled,
          conditions,
          exceptions,
          actions,
          stop_processing: stopProcessing,
        });
        toast({ title: "Rule updated" });
      } else {
        await createRule({
          name: name.trim(),
          category,
          is_enabled: isEnabled,
          conditions,
          exceptions,
          actions,
          stop_processing: stopProcessing,
        });
        toast({ title: "Rule created" });
      }
      onSaved();
      onOpenChange(false);
    } catch (error) {
      const detail = axios.isAxiosError(error) && error.response?.data?.detail;
      toast({
        title: "Couldn't save this rule",
        description: typeof detail === "string" ? detail : "Please check the fields and try again.",
        variant: "destructive",
      });
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit Rule" : "New Rule"}</DialogTitle>
        </DialogHeader>

        <div className="space-y-6">
          {/* Rule Category — fixed once a rule exists, per the category-
              determined condition/action catalog above. */}
          <div className="space-y-2">
            <Label>Rule Category</Label>
            <div className="flex gap-2">
              {(["mail_rule", "otp_rule"] as RuleCategory[]).map((c) => (
                <Button
                  key={c}
                  type="button"
                  variant={category === c ? "default" : "outline"}
                  disabled={isEditing}
                  onClick={() => handleCategoryChange(c)}
                >
                  {CATEGORY_LABELS[c]}
                </Button>
              ))}
            </div>
          </div>

          {/* Rule Name */}
          <div className="space-y-2">
            <Label htmlFor="rule-name">Rule Name</Label>
            <Input
              id="rule-name"
              placeholder="e.g. Move Crescent Health Emails"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {/* Trigger — fixed, not user-selectable. */}
          <div className="space-y-2">
            <Label>Trigger</Label>
            <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
              Email Received
            </p>
          </div>

          {/* IF — Conditions */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>IF</Label>
              {conditions.rules.length > 1 && (
                <div className="flex gap-1">
                  {(["AND", "OR"] as const).map((combinator) => (
                    <Button
                      key={combinator}
                      type="button"
                      size="sm"
                      variant={conditions.combinator === combinator ? "default" : "outline"}
                      onClick={() => setConditions({ ...conditions, combinator })}
                    >
                      {combinator}
                    </Button>
                  ))}
                </div>
              )}
            </div>
            <div className="space-y-2">
              {conditions.rules.map((condition, index) => (
                <ConditionRow
                  key={index}
                  category={category}
                  condition={condition}
                  onChange={(next) => setConditions(updateConditionAt(conditions, index, next))}
                  onRemove={() => setConditions(removeConditionAt(conditions, index))}
                />
              ))}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setConditions({ ...conditions, rules: [...conditions.rules, defaultCondition(category)] })
              }
            >
              <Plus className="mr-1 h-4 w-4" />
              Add another condition
            </Button>
          </div>

          {/* THEN — Actions */}
          <div className="space-y-2">
            <Label>THEN</Label>
            <div className="space-y-2">
              {actions.map((action, index) => (
                <ActionRow
                  key={index}
                  category={category}
                  action={action}
                  onChange={(next) => setActions(actions.map((a, i) => (i === index ? next : a)))}
                  onRemove={() => setActions(actions.filter((_, i) => i !== index))}
                />
              ))}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setActions([...actions, defaultAction(category)])}
            >
              <Plus className="mr-1 h-4 w-4" />
              Add an action
            </Button>
          </div>

          {/* Exceptions */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Except if</Label>
              {exceptions.rules.length > 1 && (
                <div className="flex gap-1">
                  {(["AND", "OR"] as const).map((combinator) => (
                    <Button
                      key={combinator}
                      type="button"
                      size="sm"
                      variant={exceptions.combinator === combinator ? "default" : "outline"}
                      onClick={() => setExceptions({ ...exceptions, combinator })}
                    >
                      {combinator}
                    </Button>
                  ))}
                </div>
              )}
            </div>
            <div className="space-y-2">
              {exceptions.rules.map((condition, index) => (
                <ConditionRow
                  key={index}
                  category={category}
                  condition={condition}
                  onChange={(next) => setExceptions(updateConditionAt(exceptions, index, next))}
                  onRemove={() => setExceptions(removeConditionAt(exceptions, index))}
                />
              ))}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setExceptions({ ...exceptions, rules: [...exceptions.rules, defaultCondition(category)] })
              }
            >
              <Plus className="mr-1 h-4 w-4" />
              Add an exception
            </Button>
          </div>

          {/* Stop processing */}
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={stopProcessing} onCheckedChange={(v) => setStopProcessing(!!v)} />
            Stop processing more rules
          </label>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Discard
          </Button>
          <Button type="button" onClick={handleSave} disabled={!isValid || isSaving}>
            {isSaving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
