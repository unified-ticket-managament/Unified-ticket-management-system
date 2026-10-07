import { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { listAssignableAgents } from "@tw/api/agent";
import { formatAssigneeLabel } from "@tw/lib/format";
import type { AssignableUserSummary, CategoryResponse } from "@tw/types";

// One extra (secondary) assignee picked FOR a specific category — the
// person list of each row is scoped to that row's own category, exactly
// like the dialog's primary "Assigned To" picker is scoped to the main
// Category. The ticket ends up in every category used here.
export interface AdditionalAssignmentRow {
  key: string;
  category_name: string;
  user_id: string;
}

interface Candidate {
  user: AssignableUserSummary;
  role: string;
}

interface AdditionalAssignmentRowsProps {
  categories: CategoryResponse[];
  rows: AdditionalAssignmentRow[];
  onChange: (rows: AdditionalAssignmentRow[]) => void;
  // The primary assignee — never offered again as an additional one.
  primaryUserId?: string;
  // Category the new row starts on (the ticket's main category).
  defaultCategory?: string;
}

let rowCounter = 0;
function newKey() {
  rowCounter += 1;
  return `row-${rowCounter}`;
}

export function AdditionalAssignmentRows({
  categories,
  rows,
  onChange,
  primaryUserId,
  defaultCategory,
}: AdditionalAssignmentRowsProps) {
  // category name -> candidates (same /agents/assignable lookup, and the
  // same role/hierarchy scoping, as the primary picker).
  const [candidatesByCategory, setCandidatesByCategory] = useState<Record<string, Candidate[]>>({});
  const [failed, setFailed] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const needed = Array.from(new Set(rows.map((r) => r.category_name).filter(Boolean))).filter(
      (name) => !(name in candidatesByCategory)
    );
    for (const name of needed) {
      listAssignableAgents(name)
        .then((response) => {
          const list: Candidate[] = [];
          if (response.me) list.push({ user: response.me, role: "Me" });
          for (const group of response.groups) {
            for (const user of group.users) {
              if (!list.some((c) => c.user.user_id === user.user_id)) list.push({ user, role: group.role });
            }
          }
          setCandidatesByCategory((prev) => ({ ...prev, [name]: list }));
        })
        .catch(() => setFailed((prev) => ({ ...prev, [name]: true })));
    }
  }, [rows, candidatesByCategory]);

  const takenIds = new Set([primaryUserId, ...rows.map((r) => r.user_id)].filter(Boolean));

  const update = (key: string, patch: Partial<AdditionalAssignmentRow>) =>
    onChange(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  return (
    <div className="flex flex-col gap-2" data-testid="additional-assignment-rows">
      <label className="block text-xs font-medium text-muted-foreground">
        Additional assignees (optional) — pick a category, then a person from it
      </label>

      {rows.map((row, index) => {
        const candidates = candidatesByCategory[row.category_name];
        const options = (candidates ?? []).filter(
          (c) => c.user.user_id === row.user_id || !takenIds.has(c.user.user_id)
        );
        return (
          <div
            key={row.key}
            className="grid grid-cols-[1fr_1fr_auto] items-center gap-2 rounded-md border border-border p-2"
            data-testid={`assignment-row-${index}`}
          >
            <Select
              value={row.category_name}
              onValueChange={(value) => update(row.key, { category_name: value, user_id: "" })}
            >
              <SelectTrigger aria-label={`Category for additional assignee ${index + 1}`}>
                <SelectValue placeholder="Category" />
              </SelectTrigger>
              <SelectContent>
                {categories.map((c) => (
                  <SelectItem key={c.category_id} value={c.category_name}>
                    {c.category_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={row.user_id}
              onValueChange={(value) => update(row.key, { user_id: value })}
              disabled={!row.category_name || !candidates}
            >
              <SelectTrigger aria-label={`Person for additional assignee ${index + 1}`}>
                <SelectValue
                  placeholder={
                    !row.category_name
                      ? "Pick a category first"
                      : failed[row.category_name]
                        ? "Couldn't load people"
                        : !candidates
                          ? "Loading…"
                          : options.length === 0
                            ? "No one available"
                            : "Select person"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {options.map(({ user, role }) => (
                  <SelectItem key={user.user_id} value={user.user_id}>
                    {formatAssigneeLabel(user)} · {role}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <button
              type="button"
              aria-label={`Remove additional assignee ${index + 1}`}
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              onClick={() => onChange(rows.filter((r) => r.key !== row.key))}
            >
              <X size={14} />
            </button>
          </div>
        );
      })}

      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={() =>
            onChange([...rows, { key: newKey(), category_name: defaultCategory ?? "", user_id: "" }])
          }
        >
          <Plus size={12} className="mr-1" />
          Add another person
        </Button>
      </div>
    </div>
  );
}
