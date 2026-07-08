import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Archive,
  CheckCheck,
  FilePlus,
  Link2,
  PencilLine,
  UserPlus,
} from "lucide-react";
import { Button } from "@/components/common/Button";
import { EmptyState } from "@/components/common/EmptyState";
import { Modal } from "@/components/common/Modal";
import { SelectInput, TextInput } from "@/components/common/FormField";
import { useApiAction } from "@/hooks/useApiAction";
import { listCategories } from "@/api/categories";
import { archiveInteraction, claimInteraction } from "@/api/inbox";
import {
  attachInteractionToTicket,
  createTicketFromInteraction,
  listTickets,
} from "@/api/ticket";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type { CategoryResponse, TicketPriority, TicketResponse } from "@/types";

const PRIORITIES: TicketPriority[] = ["LOW", "MEDIUM", "HIGH"];

export function InboxActionsPanel() {
  const navigate = useNavigate();
  const { selectedEmail, setSelectedEmail } = useWorkflowContext();

  const [createOpen, setCreateOpen] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);

  const [categories, setCategories] = useState<CategoryResponse[]>([]);
  const [title, setTitle] = useState("");
  const [ticketType, setTicketType] = useState("");
  const [priority, setPriority] = useState<TicketPriority>("MEDIUM");
  const [existingTicketId, setExistingTicketId] = useState("");
  const [clientTickets, setClientTickets] = useState<TicketResponse[]>([]);
  const [isLoadingClientTickets, setIsLoadingClientTickets] = useState(false);

  useEffect(() => {
    listCategories()
      .then((result) => {
        setCategories(result);
        setTicketType((current) => current || result[0]?.category_name || "");
      })
      .catch(() => {
        // Category fetch failing shouldn't block the rest of the
        // panel — the Select just renders empty and the agent sees
        // no options rather than a broken page.
      });
  }, []);

  const { run: runCreate, isLoading: isCreating } = useApiAction(
    createTicketFromInteraction,
    { successMessage: "Ticket created from this email." }
  );
  const { run: runAttach, isLoading: isAttaching } = useApiAction(
    attachInteractionToTicket,
    { successMessage: "Email attached to existing ticket." }
  );
  const { run: runClaim, isLoading: isClaiming } = useApiAction(claimInteraction, {
    successMessage: (res) => res.message,
  });
  const { run: runArchive, isLoading: isArchiving } = useApiAction(archiveInteraction, {
    successMessage: "Archived — no ticket needed.",
  });

  if (!selectedEmail) {
    return (
      <div className="flex h-full items-center justify-center rounded-md2 border border-border bg-surface shadow-xs">
        <EmptyState
          icon="⚡"
          title="No email selected"
          description="Actions become available once you open an email."
        />
      </div>
    );
  }

  async function handleCreateTicket() {
    if (!selectedEmail) return;

    const result = await runCreate({
      interaction_id: selectedEmail.interaction_id,
      title: title || selectedEmail.subject,
      ticket_type: ticketType,
      current_priority: priority,
    });

    if (result) {
      setCreateOpen(false);
      navigate(`/tickets/${result.ticket_id}`);
    }
  }

  async function openAttachModal() {
    // Prefill from the backend's best-effort recommendation, if any
    // — the agent can still clear/override it before confirming.
    setExistingTicketId(selectedEmail?.recommended_ticket_id ?? "");
    setAttachOpen(true);

    if (!selectedEmail?.client_id) {
      setClientTickets([]);
      return;
    }

    // GET /tickets is already scoped to whatever this user is allowed
    // to see (an Account Manager's own clients, or everything for
    // Site Lead/Super Admin) — that scope always includes this
    // client's tickets, since the caller could only open this email
    // in the first place if they're allowed to see this client. No
    // dedicated "tickets for one client" endpoint needed, just filter
    // client-side.
    setIsLoadingClientTickets(true);
    try {
      const all = await listTickets();
      setClientTickets(all.filter((t) => t.client_company_id === selectedEmail.client_id));
    } catch {
      setClientTickets([]);
    } finally {
      setIsLoadingClientTickets(false);
    }
  }

  async function handleAttachExisting() {
    if (!selectedEmail || !existingTicketId) return;

    const result = await runAttach(existingTicketId, {
      interaction_id: selectedEmail.interaction_id,
    });

    if (result) {
      setAttachOpen(false);
      navigate(`/tickets/${result.ticket_id}`);
    }
  }

  async function handleClaim() {
    if (!selectedEmail) return;

    const result = await runClaim(selectedEmail.interaction_id);

    if (result) {
      // Same convention as EmailDetails.tsx's reply handler — update
      // in place, the shared inbox list picks it up on its next
      // refresh rather than triggering a cross-component refetch.
      setSelectedEmail({
        ...selectedEmail,
        claimed_by: result.claimed_by,
        claimed_by_name: result.claimed_by_name,
      });
    }
  }

  async function handleArchive() {
    if (!selectedEmail) return;

    const result = await runArchive(selectedEmail.interaction_id);

    if (result) {
      setSelectedEmail({
        ...selectedEmail,
        status: result.status,
      });
    }
  }

  return (
    <>
      <div className="flex h-full flex-col gap-3 rounded-md2 border border-border bg-surface p-4 shadow-xs">
        <div>
          <h3 className="text-[13px] font-semibold text-slate-900">Actions</h3>
          <p className="text-[11px] text-muted">What would you like to do?</p>
        </div>

        <button
          onClick={() => setCreateOpen(true)}
          className="group flex items-center gap-3 rounded-md2 border border-success/20 bg-success/5 px-4 py-3.5 text-left transition-all duration-150 hover:-translate-y-0.5 hover:border-success/30 hover:bg-success/10 hover:shadow-xs"
        >
          <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-success/15 text-success">
            <FilePlus size={16} />
          </div>
          <div>
            <p className="text-[13px] font-semibold text-slate-900">Create New Ticket</p>
            <p className="text-[11px] text-muted">Create a new ticket from this email</p>
          </div>
        </button>

        <button
          onClick={openAttachModal}
          className="group flex items-center gap-3 rounded-md2 border border-accent/20 bg-accent/5 px-4 py-3.5 text-left transition-all duration-150 hover:-translate-y-0.5 hover:border-accent/30 hover:bg-accent/10 hover:shadow-xs"
        >
          <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-accent/15 text-accent">
            <Link2 size={16} />
          </div>
          <div>
            <p className="text-[13px] font-semibold text-slate-900">
              Attach to Existing Ticket
            </p>
            <p className="text-[11px] text-muted">
              {selectedEmail.recommended_ticket_id
                ? "We found a likely match from this thread"
                : "Link this email to an existing ticket"}
            </p>
          </div>
        </button>

        {(() => {
          const alreadyTicketed = Boolean(selectedEmail.ticket_id);
          const alreadyClaimed = Boolean(selectedEmail.claimed_by);
          const notPending = selectedEmail.status !== "PENDING";
          const claimDisabled = alreadyTicketed || alreadyClaimed || notPending || isClaiming;

          return (
            <button
              onClick={handleClaim}
              disabled={claimDisabled}
              title={
                alreadyTicketed
                  ? "Already converted to a ticket."
                  : alreadyClaimed
                  ? `Already assigned to ${selectedEmail.claimed_by_name ?? "someone"}.`
                  : notPending
                  ? "This item is no longer pending."
                  : undefined
              }
              className={`group flex items-center gap-3 rounded-md2 border px-4 py-3.5 text-left transition-all duration-150 ${
                claimDisabled
                  ? "cursor-not-allowed border-border opacity-50"
                  : "border-warning/20 bg-warning/5 hover:-translate-y-0.5 hover:border-warning/30 hover:bg-warning/10 hover:shadow-xs"
              }`}
            >
              <div
                className={`flex h-9 w-9 flex-none items-center justify-center rounded-md2 ${
                  claimDisabled ? "bg-canvas text-muted" : "bg-warning/15 text-warning"
                }`}
              >
                <UserPlus size={16} />
              </div>
              <div>
                <p className="text-[13px] font-medium text-slate-700">
                  {alreadyClaimed ? `Assigned to ${selectedEmail.claimed_by_name ?? "someone"}` : "Assign to Me"}
                </p>
                <p className="text-[11px] text-muted">
                  {alreadyClaimed ? "" : "Pick this up from the shared pool"}
                </p>
              </div>
            </button>
          );
        })()}

        {(() => {
          const alreadyTicketed = Boolean(selectedEmail.ticket_id);
          const notPending = selectedEmail.status !== "PENDING";
          const archiveDisabled = alreadyTicketed || notPending || isArchiving;

          return (
            <button
              onClick={handleArchive}
              disabled={archiveDisabled}
              title={
                alreadyTicketed
                  ? "Already converted to a ticket."
                  : notPending
                  ? "This item is no longer pending."
                  : undefined
              }
              className={`group flex items-center gap-3 rounded-md2 border px-4 py-3.5 text-left transition-all duration-150 ${
                archiveDisabled
                  ? "cursor-not-allowed border-border opacity-50"
                  : "border-border hover:-translate-y-0.5 hover:border-slate-300 hover:bg-surfaceHover hover:shadow-xs"
              }`}
            >
              <div
                className={`flex h-9 w-9 flex-none items-center justify-center rounded-md2 ${
                  archiveDisabled ? "bg-canvas text-muted" : "bg-slate-100 text-slate-600"
                }`}
              >
                <Archive size={16} />
              </div>
              <div>
                <p className="text-[13px] font-medium text-slate-700">Informational / Archive</p>
                <p className="text-[11px] text-muted">Store it — no ticket, no assignment</p>
              </div>
            </button>
          );
        })()}

        <div
          title="Not available yet — no update endpoint exists for a pending (pre-ticket) interaction."
          className="flex cursor-not-allowed items-center gap-3 rounded-md2 border border-border px-4 py-3.5 text-left opacity-50"
        >
          <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-canvas text-muted">
            <PencilLine size={16} />
          </div>
          <div>
            <p className="text-[13px] font-medium text-slate-700">Update Email</p>
            <p className="text-[11px] text-muted">Not available yet</p>
          </div>
        </div>

        <div
          title="Not available yet — no read-status endpoint exists for a pending (pre-ticket) interaction."
          className="flex cursor-not-allowed items-center gap-3 rounded-md2 border border-border px-4 py-3.5 text-left opacity-50"
        >
          <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-canvas text-muted">
            <CheckCheck size={16} />
          </div>
          <div>
            <p className="text-[13px] font-medium text-slate-700">Mark as Read</p>
            <p className="text-[11px] text-muted">Not available yet</p>
          </div>
        </div>
      </div>

      <Modal
        open={createOpen}
        title="Create Ticket From This Email"
        onClose={() => setCreateOpen(false)}
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              isLoading={isCreating}
              onClick={handleCreateTicket}
            >
              Create Ticket
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <TextInput
            label="Title"
            placeholder={selectedEmail.subject}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <SelectInput
            label="Category"
            value={ticketType}
            onChange={(e) => setTicketType(e.target.value)}
          >
            {categories.map((c) => (
              <option key={c.category_id} value={c.category_name}>
                {c.category_name}
              </option>
            ))}
          </SelectInput>
          <SelectInput
            label="Priority"
            value={priority}
            onChange={(e) => setPriority(e.target.value as TicketPriority)}
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </SelectInput>
        </div>
      </Modal>

      <Modal
        open={attachOpen}
        title="Attach To Existing Ticket"
        onClose={() => setAttachOpen(false)}
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => setAttachOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              isLoading={isAttaching}
              onClick={handleAttachExisting}
            >
              Attach
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          {selectedEmail.recommended_ticket_id && (
            <div className="rounded-md2 border border-accent/20 bg-accent/5 px-3.5 py-2.5 text-xs">
              <p className="font-semibold text-accent">
                Recommended: {selectedEmail.recommended_ticket_id.slice(0, 8)}…
              </p>
              <p className="mt-0.5 text-muted">{selectedEmail.recommended_ticket_reason}</p>
              {existingTicketId !== selectedEmail.recommended_ticket_id && (
                <button
                  onClick={() => setExistingTicketId(selectedEmail.recommended_ticket_id!)}
                  className="mt-1.5 font-medium text-accent hover:underline"
                >
                  Use this ticket
                </button>
              )}
            </div>
          )}

          {isLoadingClientTickets ? (
            <p className="text-xs text-muted">Loading {selectedEmail.client_name}'s tickets…</p>
          ) : clientTickets.length > 0 ? (
            <SelectInput
              label={`${selectedEmail.client_name}'s tickets`}
              value={clientTickets.some((t) => t.ticket_id === existingTicketId) ? existingTicketId : ""}
              onChange={(e) => setExistingTicketId(e.target.value)}
              hint="Every existing ticket for this client — pick one instead of pasting an ID."
            >
              <option value="">Choose a ticket…</option>
              {clientTickets.map((t) => (
                <option key={t.ticket_id} value={t.ticket_id}>
                  {t.title} · {t.current_status} ({t.ticket_id.slice(0, 8)})
                </option>
              ))}
            </SelectInput>
          ) : (
            <p className="text-xs text-muted">
              No existing tickets found for {selectedEmail.client_name} yet — paste a ticket ID
              manually below if you have one from elsewhere.
            </p>
          )}

          <TextInput
            label={clientTickets.length > 0 ? "Or paste a ticket ID manually" : "Existing ticket ID"}
            placeholder="Paste a ticket_id"
            value={existingTicketId}
            onChange={(e) => setExistingTicketId(e.target.value)}
          />
        </div>
      </Modal>
    </>
  );
}
