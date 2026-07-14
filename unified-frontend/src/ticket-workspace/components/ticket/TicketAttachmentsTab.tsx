import { useEffect, useState } from "react";
import { Download, Loader2, Trash2 } from "lucide-react";
import { Card } from "@tw/components/common/Card";
import { EmptyState } from "@tw/components/common/EmptyState";
import { deleteAttachment } from "@tw/api/interaction";
import { listEditAccessRequests } from "@tw/api/ticket";
import { useApiAction } from "@tw/hooks/useApiAction";
import { formatBytes, iconForFilename } from "@tw/lib/attachmentMeta";
import { formatDateTime, shortId } from "@tw/lib/format";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";

interface FlatAttachment {
  id: string;
  filename: string;
  size: number | null;
  download_url: string;
  uploadedBy: string;
  uploadedAt: string;
}

interface TicketAttachmentsTabProps {
  // Refetches the ticket timeline after a delete so the removed file
  // (and the interaction row it belonged to, if now attachment-less)
  // disappears immediately — same refresh TicketTimeline already
  // triggers after hiding an interaction.
  onChanged: () => void;
  // Rendered inside TicketActivityPanel's tabbed box, which already
  // provides the outer border/shadow — see Card's `flat` prop (same
  // convention every other tab here already uses).
  flat?: boolean;
}

// Every file ever uploaded to this ticket, across every interaction
// (replies, notes, and the dedicated "Upload Attachment" action all
// create one) — derived entirely from the ticket's own timeline
// (already loaded by TicketDetailPage), so this reuses the exact same
// data and upload/delete endpoints instead of standing up a second
// attachment system.
export function TicketAttachmentsTab({ onChanged, flat = false }: TicketAttachmentsTabProps) {
  const { activeTicket, timeline } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const [hasActiveEditAccessGrant, setHasActiveEditAccessGrant] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const { run: runDelete, isLoading: isDeleting } = useApiAction(deleteAttachment, {
    successMessage: "Attachment deleted.",
  });

  useEffect(() => {
    if (!activeTicket) return;
    listEditAccessRequests(activeTicket.ticket_id)
      .then((requests) => {
        const active = requests.some(
          (r) =>
            r.requested_by === currentUser?.user_id &&
            r.status === "APPROVED" &&
            (!r.expires_at || new Date(r.expires_at) > new Date())
        );
        setHasActiveEditAccessGrant(active);
      })
      .catch(() => setHasActiveEditAccessGrant(false));
  }, [activeTicket?.ticket_id, currentUser?.user_id]);

  if (!activeTicket) return null;

  // Mirrors TicketActions' own canActOnTicket check — the same actor
  // set allowed to upload is allowed to delete. A closed ticket is
  // read-only regardless of ownership/grants — deleting an attachment
  // is an edit operation like any other.
  const isOwnTicket = activeTicket.agent_id === currentUser?.user_id;
  const hasEditOther =
    (currentUser?.permissions ?? []).includes("ticket:editother_ticket") ||
    (currentUser?.scoped_permissions?.["ticket:editother_ticket"] ?? []).includes(
      activeTicket.ticket_id
    );
  const isTicketClosed = activeTicket.current_status === "CLOSED";
  const canDelete = !isTicketClosed && (isOwnTicket || hasEditOther || hasActiveEditAccessGrant);

  const attachments: FlatAttachment[] = timeline
    .flatMap((interaction) =>
      (interaction.attachments ?? []).map((attachment) => ({
        id: attachment.id,
        filename: attachment.filename,
        size: attachment.size,
        download_url: attachment.download_url,
        uploadedBy:
          interaction.performed_by_name ??
          (interaction.performed_by ? shortId(interaction.performed_by) : "System"),
        uploadedAt: interaction.created_at,
      }))
    )
    .sort((a, b) => new Date(b.uploadedAt).getTime() - new Date(a.uploadedAt).getTime());

  async function handleDelete(attachmentId: string) {
    setDeletingId(attachmentId);
    const result = await runDelete(attachmentId);
    setDeletingId(null);
    if (result !== null) onChanged();
  }

  return (
    <Card flat={flat} title="Attachments" eyebrow={`${attachments.length} file${attachments.length === 1 ? "" : "s"}`}>
      {attachments.length === 0 ? (
        <EmptyState
          icon="📎"
          title="No attachments yet"
          description="Files uploaded via Reply, Internal Note, or Upload Attachment will appear here."
        />
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {attachments.map((attachment) => {
            const Icon = iconForFilename(attachment.filename);
            const isRowDeleting = isDeleting && deletingId === attachment.id;

            return (
              <li key={attachment.id} className="flex flex-wrap items-center gap-3 py-3">
                <span className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-canvas text-muted">
                  <Icon size={16} />
                </span>

                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-semibold text-slate-900">
                    {attachment.filename}
                  </p>
                  <p className="mt-0.5 text-[11px] text-muted">
                    Uploaded by {attachment.uploadedBy} · {formatDateTime(attachment.uploadedAt)}
                  </p>
                </div>

                <span className="flex-none text-[11px] font-medium text-muted">
                  {formatBytes(attachment.size)}
                </span>

                <div className="flex flex-none items-center gap-1">
                  <a
                    href={attachment.download_url}
                    target="_blank"
                    rel="noreferrer"
                    download
                    aria-label={`Download ${attachment.filename}`}
                    title="Download"
                    className="flex h-8 w-8 items-center justify-center rounded-md2 text-muted transition-colors hover:bg-surfaceHover hover:text-accent"
                  >
                    <Download size={15} />
                  </a>
                  {canDelete && (
                    <button
                      type="button"
                      onClick={() => handleDelete(attachment.id)}
                      disabled={isDeleting}
                      aria-label={`Delete ${attachment.filename}`}
                      title="Delete"
                      className="flex h-8 w-8 items-center justify-center rounded-md2 text-muted transition-colors hover:bg-danger/10 hover:text-danger disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {isRowDeleting ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
