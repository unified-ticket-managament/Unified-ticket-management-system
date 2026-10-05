"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { listTickets } from "@tw/api/ticket";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { formatTicketNumber } from "@tw/lib/format";
import type { TicketPriority, TicketResponse } from "@tw/types";

// Bulk counterparts of MessageDetailsView's Create Ticket / Attach To
// Existing Ticket dialogs. They only COLLECT the shared choices; the
// ticket itself is created/attached per message by the existing
// workflow behind POST /inbox/bulk-action, so these hold no ticket
// business rules. Each is also the confirmation step for its action.

const PRIORITIES: TicketPriority[] = ["LOW", "MEDIUM", "HIGH"];

export interface BulkCreateTicketChoice {
  ticketType: string;
  priority: TicketPriority;
  assignToMe: boolean;
}

interface BulkCreateTicketDialogProps {
  open: boolean;
  count: number;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (choice: BulkCreateTicketChoice) => void;
}

export function BulkCreateTicketDialog({
  open,
  count,
  busy,
  onCancel,
  onConfirm,
}: BulkCreateTicketDialogProps) {
  const { allCategories, allCategoriesLoading, allCategoriesError } = useWorkflowContext();
  const [ticketType, setTicketType] = useState("");
  const [priority, setPriority] = useState<TicketPriority>("MEDIUM");
  const [assignToMe, setAssignToMe] = useState(false);

  useEffect(() => {
    if (open) {
      setTicketType("");
      setPriority("MEDIUM");
      setAssignToMe(false);
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && !busy && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            Create {count} {count === 1 ? "ticket" : "tickets"}
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <p className="text-xs text-muted-foreground">
            One separate ticket is created for each selected email, titled with its subject.
            Emails are never merged, and each one is checked on its own — any that can&apos;t be
            ticketed are reported afterwards.
          </p>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Category</label>
            <Select value={ticketType} onValueChange={setTicketType} disabled={allCategoriesLoading}>
              <SelectTrigger>
                <SelectValue
                  placeholder={
                    allCategoriesLoading
                      ? "Loading categories…"
                      : allCategoriesError
                        ? "Failed to load categories"
                        : "Select"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {allCategories.map((c) => (
                  <SelectItem key={c.category_id} value={c.category_name}>
                    {c.category_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Priority</label>
            <Select value={priority} onValueChange={(v) => setPriority(v as TicketPriority)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRIORITIES.map((p) => (
                  <SelectItem key={p} value={p}>
                    {p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Assigned To</label>
            <Select
              value={assignToMe ? "self" : "unassigned"}
              onValueChange={(v) => setAssignToMe(v === "self")}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="unassigned">Unassigned</SelectItem>
                <SelectItem value="self">Myself</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button
            onClick={() => onConfirm({ ticketType, priority, assignToMe })}
            disabled={busy || !ticketType}
          >
            {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            Create {count} {count === 1 ? "ticket" : "tickets"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface BulkLinkTicketDialogProps {
  open: boolean;
  count: number;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (ticketId: string) => void;
}

export function BulkLinkTicketDialog({
  open,
  count,
  busy,
  onCancel,
  onConfirm,
}: BulkLinkTicketDialogProps) {
  const [tickets, setTickets] = useState<TicketResponse[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);
  const [ticketId, setTicketId] = useState("");

  useEffect(() => {
    if (!open) return;
    setTicketId("");
    setLoadFailed(false);
    let cancelled = false;
    listTickets()
      .then((rows) => {
        if (!cancelled) setTickets(rows);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const selected = useMemo(
    () => tickets.find((t) => t.ticket_id === ticketId) ?? null,
    [tickets, ticketId]
  );
  const reopens = selected?.current_status === "CLOSED";

  return (
    <Dialog open={open} onOpenChange={(next) => !next && !busy && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            Link {count} {count === 1 ? "email" : "emails"} to an existing ticket
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <p className="text-xs text-muted-foreground">
            Each email is checked on its own — it is linked only if you may act on it and it
            belongs to the same client as the ticket. Any that can&apos;t be linked are reported
            afterwards.
          </p>
          {tickets.length > 0 ? (
            <Select value={ticketId} onValueChange={setTicketId}>
              <SelectTrigger>
                <SelectValue placeholder="Choose a ticket..." />
              </SelectTrigger>
              <SelectContent>
                {tickets.map((t) => (
                  <SelectItem key={t.ticket_id} value={t.ticket_id}>
                    {formatTicketNumber(t.ticket_number)} · {t.title} · {t.client_company_name ?? "—"} ·{" "}
                    {t.current_status}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <p className="text-xs text-muted-foreground">
              {loadFailed ? "Couldn't load tickets — paste a ticket ID instead." : "Loading tickets…"}
            </p>
          )}
          <Input
            value={ticketId}
            onChange={(e) => setTicketId(e.target.value.trim())}
            placeholder="Or paste a ticket ID"
          />
          {reopens && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3.5 py-2.5 text-xs text-muted-foreground">
              This ticket is closed. Linking reopens it exactly as a single link does (Closed → In
              Progress, same ticket and history), for callers permitted to reopen.
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => onConfirm(ticketId)} disabled={busy || !ticketId}>
            {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            Link {count} {count === 1 ? "email" : "emails"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
