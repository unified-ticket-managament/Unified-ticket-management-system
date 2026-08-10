import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowLeft, Check, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { TicketActions } from "@tw/components/ticket/TicketActions";
import { RefreshButton } from "@tw/components/common/RefreshButton";
import { useApiAction } from "@tw/hooks/useApiAction";
import { useAuthContext } from "@tw/context/AuthContext";
import { useToast } from "@tw/context/ToastContext";
import { updateTicket } from "@tw/api/ticket";
import { formatTicketNumber } from "@tw/lib/format";
import type { TicketResponse } from "@tw/types";

interface TicketHeaderProps {
  ticket: TicketResponse;
  onActionComplete: () => void;
  onRefresh: () => void;
  isRefreshing?: boolean;
}

export function TicketHeader({ ticket, onActionComplete, onRefresh, isRefreshing }: TicketHeaderProps) {
  const navigate = useNavigate();
  const { currentUser } = useAuthContext();
  const { pushToast } = useToast();
  const { run: runUpdateTitle, isLoading: isSavingTitle } = useApiAction(updateTicket);

  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(ticket.title);
  const inputRef = useRef<HTMLInputElement>(null);

  // Mirrors the actual gate PATCH /tickets/{id} enforces server-side
  // (TicketService.update requires ticket:change_category regardless
  // of which field in the payload changes — there's no separate
  // "rename ticket" permission) rather than the ownership-based
  // canActOnTicket gate TicketActions.tsx uses for reply/status/etc,
  // since this reuses that same shared endpoint.
  const canEditTitle =
    ticket.current_status !== "CLOSED" &&
    !!currentUser?.permissions?.includes("ticket:change_category");

  useEffect(() => {
    if (!isEditingTitle) setTitleDraft(ticket.title);
  }, [ticket.title, isEditingTitle]);

  useEffect(() => {
    if (isEditingTitle && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditingTitle]);

  function startEditing() {
    if (!canEditTitle) return;
    setTitleDraft(ticket.title);
    setIsEditingTitle(true);
  }

  function cancelEditing() {
    setTitleDraft(ticket.title);
    setIsEditingTitle(false);
  }

  async function saveTitle() {
    const trimmed = titleDraft.trim();
    if (!trimmed) {
      pushToast("Ticket name cannot be empty.", "error");
      return;
    }
    if (trimmed === ticket.title) {
      setIsEditingTitle(false);
      return;
    }
    const result = await runUpdateTitle(ticket.ticket_id, { title: trimmed });
    if (result) {
      setIsEditingTitle(false);
      onActionComplete();
    }
  }

  function handleTitleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      saveTitle();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancelEditing();
    }
  }

  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 flex-1">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-muted transition-colors hover:text-slate-900"
        >
          <ArrowLeft size={14} />
          Back
        </button>
        <p className="font-mono text-[11px] font-semibold tracking-wide text-accent">
          {formatTicketNumber(ticket.ticket_number)}
        </p>
        {isEditingTitle ? (
          <div className="mt-1 flex items-center gap-1.5">
            <input
              ref={inputRef}
              type="text"
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              onKeyDown={handleTitleKeyDown}
              onBlur={cancelEditing}
              className="w-full max-w-xl rounded-md2 border border-accent bg-surface px-2 py-1 text-2xl font-bold leading-tight text-slate-900 shadow-xs focus:outline-none focus:ring-4 focus:ring-accent/10"
            />
            <button
              type="button"
              aria-label="Save ticket name"
              onMouseDown={(e) => e.preventDefault()}
              onClick={saveTitle}
              disabled={isSavingTitle}
              className="flex h-7 w-7 flex-none items-center justify-center rounded-md2 text-success transition-colors hover:bg-success/10 disabled:opacity-50"
            >
              <Check size={16} />
            </button>
            <button
              type="button"
              aria-label="Cancel editing ticket name"
              onMouseDown={(e) => e.preventDefault()}
              onClick={cancelEditing}
              disabled={isSavingTitle}
              className="flex h-7 w-7 flex-none items-center justify-center rounded-md2 text-muted transition-colors hover:bg-canvas disabled:opacity-50"
            >
              <X size={16} />
            </button>
          </div>
        ) : (
          <h2
            onDoubleClick={startEditing}
            title={canEditTitle ? "Double-click to rename" : undefined}
            className={`mt-1 text-2xl font-bold leading-tight text-slate-900 ${canEditTitle ? "cursor-text" : ""}`}
          >
            {ticket.title}
          </h2>
        )}
      </div>

      <div className="flex flex-none items-center gap-2">
        <RefreshButton onRefresh={onRefresh} isRefreshing={isRefreshing} />
        <TicketActions onActionComplete={onActionComplete} />
      </div>
    </div>
  );
}
