import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { AppLayout } from "@tw/components/layout/AppLayout";
import { Badge } from "@tw/components/common/Badge";
import { EmptyState } from "@tw/components/common/EmptyState";
import { AttachmentList } from "@tw/components/common/AttachmentList";
import { getInteractionThread } from "@tw/api/interaction";
import { openInboxThread } from "@tw/api/inbox";
import {
  messageBody,
  messageDirectionLabel,
  messageSender,
  metaFor,
  summarize,
} from "@tw/lib/interactionMeta";
import { shortId, formatDateTime } from "@tw/lib/format";
import type { InteractionResponse, InteractionStatus, OpenEmailResponse, ThreadResponse } from "@tw/types";

// Minimal header info the page needs — a subset of InteractionsPage's
// own `InteractionRow` shape, passed through via router state when
// reached from the Expand button (see InteractionsPage's handleExpand)
// so no extra request is needed in the common case.
interface HeaderRow {
  id: string;
  createdAt: string;
  type: string;
  status: InteractionStatus;
  ticketId: string | null;
  clientName: string | null;
  summaryText: string;
}

interface LocationState {
  row?: HeaderRow;
  email?: OpenEmailResponse | null;
  thread?: ThreadResponse | null;
}

// Reshapes the single-email response (pending, not-yet-ticketed rows)
// into the same InteractionResponse shape every other message already
// has, so one conversation renderer covers both cases without a
// second code path.
function emailToMessage(email: OpenEmailResponse): InteractionResponse {
  return {
    interaction_id: email.interaction_id,
    ticket_id: email.ticket_id,
    interaction_type: "EMAIL",
    status: email.status,
    direction: "INBOUND",
    performed_by: null,
    performed_by_name: null,
    payload: {
      client_name: email.client_name,
      from_email: email.from_email,
      to_email: email.to_email,
      subject: email.subject,
      body: email.body,
    },
    is_visible: true,
    removed_by: null,
    removed_at: null,
    message_id: email.message_id,
    created_at: email.received_at,
    attachments: email.attachments,
  };
}

function initials(name: string | null): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// Client emails render left, agent replies render right, internal
// notes get their own distinct centered card, and everything else
// (status/priority changes, transfers, standalone attachment
// uploads, etc.) renders as a slim centered system line — not a chat
// bubble, since there's no "sender" side to take in a messaging UI.
type ConversationAlign = "left" | "right" | "note" | "system";

function alignFor(type: string): ConversationAlign {
  switch (type) {
    case "EMAIL":
      return "left";
    case "REPLY":
      return "right";
    case "INTERNAL_NOTE":
      return "note";
    default:
      return "system";
  }
}

function ConversationItem({ message }: { message: InteractionResponse }) {
  const align = alignFor(message.interaction_type);
  const meta = metaFor(message.interaction_type);
  const sender = messageSender(message);
  const body = messageBody(message);
  const timestamp = formatDateTime(message.created_at);
  const attachments = message.attachments ?? [];

  if (align === "system") {
    return (
      <div className="flex flex-col items-center gap-2 py-1">
        <div className="flex flex-wrap items-center justify-center gap-2 text-[11px] text-muted">
          <span>{meta.icon}</span>
          <span>{summarize(message)}</span>
          <span>·</span>
          <span>{timestamp}</span>
          <Badge tone={meta.tone}>{message.status}</Badge>
        </div>
        {attachments.length > 0 && (
          <div className="w-full max-w-sm">
            <AttachmentList attachments={attachments} />
          </div>
        )}
      </div>
    );
  }

  if (align === "note") {
    return (
      <div className="mx-auto flex w-full max-w-xl flex-col gap-1.5 rounded-md2 border border-warning/20 bg-warning/5 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-warning">
            {meta.icon} Internal Note
          </span>
          <span className="text-[11px] text-muted">{timestamp}</span>
        </div>
        {sender && <p className="text-[11px] font-medium text-slate-600">{sender}</p>}
        {body && (
          <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">{body}</p>
        )}
        {attachments.length > 0 && <AttachmentList attachments={attachments} className="mt-1" />}
        <div>
          <Badge tone="default">{message.status}</Badge>
        </div>
      </div>
    );
  }

  const isRight = align === "right";
  return (
    <div className={`flex items-end gap-2.5 ${isRight ? "flex-row-reverse" : ""}`}>
      <span className="flex h-8 w-8 flex-none items-center justify-center rounded-full border border-border bg-canvas text-[11px] font-semibold text-slate-600">
        {initials(sender)}
      </span>
      <div className={`flex max-w-[75%] flex-col gap-1 ${isRight ? "items-end" : "items-start"}`}>
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
          <span className="font-semibold text-slate-700">{sender ?? "Unknown"}</span>
          <span>·</span>
          <span>{messageDirectionLabel(message)}</span>
          <span>·</span>
          <span>{timestamp}</span>
        </div>
        <div
          className={`rounded-md2 border px-3.5 py-2.5 text-[13px] leading-relaxed shadow-xs ${
            isRight ? "border-accent/20 bg-accent/10 text-slate-800" : "border-border bg-surface text-slate-800"
          }`}
        >
          {body && <p className="whitespace-pre-wrap">{body}</p>}
          {attachments.length > 0 && <AttachmentList attachments={attachments} className="mt-2" />}
        </div>
        <Badge tone={meta.tone}>{message.status}</Badge>
      </div>
    </div>
  );
}

// Full-page counterpart to InteractionDetailsDrawer's sidebar view —
// reached only via its Expand button (see InteractionsPage). Reuses
// the exact same GET /interactions/{id}/thread and GET /inbox/{id}
// calls the drawer already uses; when the drawer's Expand click
// passes that already-fetched data through router state, this page
// renders instantly with no request of its own. The fetch below only
// runs as a fallback for a direct load/refresh on this URL.
export function FullInteractionPage() {
  const { interactionId } = useParams<{ interactionId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const passedState = (location.state as LocationState | null) ?? null;

  const [thread, setThread] = useState<ThreadResponse | null>(passedState?.thread ?? null);
  const [email, setEmail] = useState<OpenEmailResponse | null>(passedState?.email ?? null);
  const [row, setRow] = useState<HeaderRow | null>(passedState?.row ?? null);
  const [isLoading, setIsLoading] = useState(!passedState?.row);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (passedState?.row || !interactionId) return;

    let cancelled = false;
    setIsLoading(true);
    (async () => {
      try {
        const fetchedThread = await getInteractionThread(interactionId);
        if (cancelled) return;
        setThread(fetchedThread);
        const parent = fetchedThread.parent_interaction;
        setRow({
          id: parent.interaction_id,
          createdAt: parent.created_at,
          type: parent.interaction_type,
          status: parent.status,
          ticketId: parent.ticket_id,
          clientName: (parent.payload?.client_name as string) ?? null,
          summaryText: summarize(parent),
        });
      } catch {
        try {
          const fetchedEmail = await openInboxThread(interactionId);
          if (cancelled) return;
          setEmail(fetchedEmail);
          setRow({
            id: fetchedEmail.interaction_id,
            createdAt: fetchedEmail.received_at,
            type: "EMAIL",
            status: fetchedEmail.status,
            ticketId: fetchedEmail.ticket_id,
            clientName: fetchedEmail.client_name,
            summaryText: fetchedEmail.subject,
          });
        } catch (error) {
          if (!cancelled) {
            setLoadError(error instanceof Error ? error.message : "Failed to load this interaction.");
          }
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactionId]);

  const messages = useMemo<InteractionResponse[]>(() => {
    const items = thread
      ? thread.ordered_thread
      : email
        ? [emailToMessage(email), ...email.replies]
        : [];
    return [...items].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  }, [thread, email]);

  const subject = useMemo(() => {
    if (thread) return (thread.parent_interaction.payload?.subject as string) ?? null;
    if (email) return email.subject;
    return row?.summaryText ?? null;
  }, [thread, email, row]);

  const meta = row ? metaFor(row.type) : null;

  return (
    <AppLayout>
      <div className="flex flex-col gap-5">
        <button
          type="button"
          onClick={() => navigate("/interactions")}
          className="flex w-fit items-center gap-1.5 text-xs font-semibold text-muted transition-colors hover:text-slate-900"
        >
          <ArrowLeft size={14} />
          Back
        </button>

        {!row ? (
          <div className="rounded-md2 border border-border bg-surface shadow-xs">
            <EmptyState
              icon={isLoading ? "💬" : "⚠️"}
              title={isLoading ? "Loading interaction…" : "Interaction not found"}
              description={
                isLoading ? undefined : loadError ?? "It may have been removed, or the link is incorrect."
              }
            />
          </div>
        ) : (
          <>
            <div className="rounded-md2 border border-border bg-surface p-5 shadow-xs">
              <div className="flex flex-wrap items-center gap-2">
                {meta && (
                  <Badge tone={meta.tone}>
                    {meta.icon} {meta.label}
                  </Badge>
                )}
                <Badge tone="default">{row.status}</Badge>
              </div>

              {subject && <h2 className="mt-3 text-xl font-bold leading-tight text-slate-900">{subject}</h2>}

              <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-xs sm:grid-cols-4">
                <div>
                  <dt className="text-muted">Interaction ID</dt>
                  <dd className="mt-0.5 font-mono text-[11px] text-slate-800">{shortId(row.id, 12)}</dd>
                </div>
                <div>
                  <dt className="text-muted">Ticket ID</dt>
                  <dd className="mt-0.5 font-mono text-[11px] text-slate-800">
                    {row.ticketId ? shortId(row.ticketId, 12) : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted">Client Name</dt>
                  <dd className="mt-0.5 font-medium text-slate-800">{row.clientName ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-muted">Timestamp</dt>
                  <dd className="mt-0.5 font-medium text-slate-800">{formatDateTime(row.createdAt)}</dd>
                </div>
              </dl>
            </div>

            <div className="flex flex-col gap-4 rounded-md2 border border-border bg-surface p-5 shadow-xs">
              {messages.length === 0 ? (
                <EmptyState icon="💬" title="No conversation yet" />
              ) : (
                messages.map((message) => <ConversationItem key={message.interaction_id} message={message} />)
              )}
            </div>
          </>
        )}
      </div>
    </AppLayout>
  );
}
