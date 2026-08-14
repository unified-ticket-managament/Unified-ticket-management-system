"use client";

import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { listInternalNoteRecipients } from "@tw/api/interaction";
import type { InternalNoteRecipientCandidate } from "@tw/types";

type EmployeeSummary = InternalNoteRecipientCandidate;

interface EmployeeMultiSelectProps {
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}

// The "Forward To" picker — searchable, checkbox-selectable, selected
// employees shown as chips. Fetches every active employee once via
// GET /tickets/internal-notes/recipients (listInternalNoteRecipients)
// — the same deliberately unscoped, any-role endpoint the Internal
// Note "To" picker uses, and for the same reason: RBAC's own
// GET /api/v1/users is hierarchy-scoped (Account Manager/Team Lead
// only get their own reporting subtree back), which silently starved
// this picker's search of most of the company regardless of query.
//
// Renders the list as an always-visible, bounded-height box (same
// structure as ClientPicker) rather than an absolutely-positioned
// floating dropdown — a floating overlay gated by input focus used to
// be here, but RuleBuilderDialog's own scrollable DialogContent
// clips/mispositions that kind of overlay, so it rendered nothing
// visible however far down the form this row happened to sit.
export function EmployeeMultiSelect({ selectedIds, onChange }: EmployeeMultiSelectProps) {
  const [employees, setEmployees] = useState<EmployeeSummary[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    listInternalNoteRecipients()
      .then((recipients) => {
        setEmployees(recipients);
        setLoadError(false);
      })
      .catch(() => setLoadError(true))
      .finally(() => setIsLoading(false));
  }, []);

  const selected = useMemo(
    () => selectedIds.map((id) => employees.find((e) => e.user_id === id)).filter(Boolean) as EmployeeSummary[],
    [employees, selectedIds]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return employees.filter((e) => {
      if (!q) return true;
      return e.name.toLowerCase().includes(q) || e.email.toLowerCase().includes(q);
    });
  }, [employees, query]);

  function toggle(userId: string) {
    if (selectedIds.includes(userId)) {
      onChange(selectedIds.filter((id) => id !== userId));
    } else {
      onChange([...selectedIds, userId]);
    }
  }

  return (
    <div>
      {selected.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {selected.map((employee) => (
            <Badge key={employee.user_id} variant="secondary" className="gap-1 pr-1">
              {employee.name}
              <button
                type="button"
                aria-label={`Remove ${employee.name}`}
                onClick={() => toggle(employee.user_id)}
                className="rounded-full p-0.5 hover:bg-muted"
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      <div className="rounded-lg border border-border">
        <div className="border-b border-border p-2">
          <Input
            placeholder="Search employees by name or email…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="h-8"
          />
        </div>
        <div className="max-h-48 overflow-y-auto p-2">
          {isLoading ? (
            <p className="px-1 py-2 text-xs text-muted-foreground">Loading employees…</p>
          ) : loadError ? (
            <p className="px-1 py-2 text-xs text-destructive">Couldn't load employees. Please try again.</p>
          ) : filtered.length === 0 ? (
            <p className="px-1 py-2 text-xs text-muted-foreground">No matching employees.</p>
          ) : (
            filtered.map((employee) => (
              <label
                key={employee.user_id}
                className="flex items-center gap-2 rounded-md px-1 py-1.5 text-sm hover:bg-muted/50"
              >
                <Checkbox
                  checked={selectedIds.includes(employee.user_id)}
                  onCheckedChange={() => toggle(employee.user_id)}
                />
                <span className="flex flex-col">
                  <span className="font-medium">{employee.name}</span>
                  <span className="text-xs text-muted-foreground">{employee.email}</span>
                </span>
              </label>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
