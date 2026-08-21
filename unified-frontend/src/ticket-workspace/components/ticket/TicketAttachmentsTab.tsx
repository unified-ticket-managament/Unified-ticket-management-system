import { useEffect, useRef, useState } from "react";
import { Download, ExternalLink, Loader2, Trash2 } from "lucide-react";
import { Card } from "@tw/components/common/Card";
import { EmptyState } from "@tw/components/common/EmptyState";
import { SkeletonRows } from "@tw/components/common/Skeleton";
import { deleteAttachment, getTicketAttachments } from "@tw/api/interaction";
import { useApiAction } from "@tw/hooks/useApiAction";
import { formatBytes, iconForFilename } from "@tw/lib/attachmentMeta";
import { formatDateTime, shortId } from "@tw/lib/format";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import type { TicketAttachmentItem } from "@tw/types";

interface FlatAttachment {
  id: string;
  filename: string;
  size: number | null;
  download_url: string;
  isExternalLink: boolean;
  uploadedBy: string;
  uploadedAt: string;
}

function toFlatAttachment(item: TicketAttachmentItem): FlatAttachment {
  return {
    id: item.id,
    filename: item.filename,
    size: item.size,
    download_url: item.download_url,
    isExternalLink: Boolean(item.is_external_link),
    uploadedBy: item.performed_by_name ?? (item.performed_by ? shortId(item.performed_by) : "System"),
    uploadedAt: item.created_at,
  };
}

interface TicketAttachmentsTabProps {
  // Refetches the ticket timeline after a delete so the removed
  // interaction row (if now attachment-less) disappears immediately —
  // same refresh TicketTimeline already triggers after hiding an
  // interaction. This tab also refetches its own attachment list
  // independently (see refreshToken below), since the timeline itself
  // never carries real attachment data (see getTicketAttachments).
  onChanged: () => void;
  // Rendered inside TicketActivityPanel's tabbed box, which already
  // provides the outer border/shadow — see Card's `flat` prop (same
  // convention every other tab here already uses).
  flat?: boolean;
}

// Every file ever uploaded to this ticket, across every interaction
// type — inbound/outbound email, internal note, reply, and direct
// ticket upload all create one. Fetched from a dedicated endpoint
// (GET /tickets/{id}/attachments) rather than derived from the
// already-loaded ticket timeline: that endpoint's own InteractionResponse
// rows are deliberately built with `attachments: []` always (a
// performance optimization for the Timeline tab, see
// InteractionService.get_ticket_interactions), so deriving from it here
// silently produced an empty Attachments tab regardless of how many
// files actually existed. This still reuses the existing upload/delete
// endpoints and the existing repository/service architecture — only
// the *read* path for this tab changed.
export function TicketAttachmentsTab({ onChanged, flat = false }: TicketAttachmentsTabProps) {
  const { activeTicket } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [items, setItems] = useState<TicketAttachmentItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [refreshToken, setRefreshToken] = useState(0);
  const requestIdRef = useRef(0);

  const { run: runDelete, isLoading: isDeleting } = useApiAction(deleteAttachment, {
    successMessage: "Attachment deleted.",
  });

  const ticketId = activeTicket?.ticket_id;

  useEffect(() => {
    if (!ticketId) return;

    let cancelled = false;
    const thisRequestId = ++requestIdRef.current;
    setIsLoading(true);

    getTicketAttachments(ticketId)
      .then((data) => {
        if (!cancelled && thisRequestId === requestIdRef.current) {
          setItems(data);
        }
      })
      .catch(() => {
        if (!cancelled && thisRequestId === requestIdRef.current) {
          setItems([]);
        }
      })
      .finally(() => {
        if (!cancelled && thisRequestId === requestIdRef.current) {
          setIsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [ticketId, refreshToken]);

  if (!activeTicket) return null;

  // Mirrors the backend's AttachmentService.delete_attachment gate
  // exactly: ticket:archive_attachment (Full for Super Admin/Site
  // Lead/Account Manager — own clients, checked server-side via
  // ensure_account_manager_owns_ticket_client — Override-only for Team
  // Lead/Staff). Previously reused ticket:editother_ticket/ownership,
  // which is a different permission for a different action (editing
  // someone else's ticket, not archiving an attachment) and let anyone
  // who could edit the ticket delete files regardless of this
  // permission. A closed ticket is read-only regardless of permission
  // — deleting an attachment is an edit operation like any other.
  const canArchiveAttachment = (currentUser?.permissions ?? []).includes(
    "ticket:archive_attachment"
  );
  const isTicketClosed = activeTicket.current_status === "CLOSED";
  // Deliberately no edit-access-grant fallback here — unlike
  // ensure_agent_can_act_on_ticket (upload/reply/etc.), the backend's
  // delete_attachment authorizes purely via ticket:archive_attachment,
  // with no edit-access-grant bypass.
  const canDelete = !isTicketClosed && canArchiveAttachment;

  const attachments: FlatAttachment[] = items
    .map(toFlatAttachment)
    .sort((a, b) => new Date(b.uploadedAt).getTime() - new Date(a.uploadedAt).getTime());

  async function handleDelete(attachmentId: string) {
    setDeletingId(attachmentId);
    const result = await runDelete(attachmentId);
    setDeletingId(null);
    if (result !== null) {
      setRefreshToken((prev) => prev + 1);
      onChanged();
    }
  }

  return (
    <Card flat={flat} title="Attachments" eyebrow={`${attachments.length} file${attachments.length === 1 ? "" : "s"}`}>
      {isLoading ? (
        <SkeletonRows rows={3} />
      ) : attachments.length === 0 ? (
        <EmptyState
          icon="📎"
          title="No attachments yet"
          description="Files uploaded via Reply, Internal Note, or Upload Attachment will appear here."
        />
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {attachments.map((attachment) => {
            const Icon = attachment.isExternalLink ? ExternalLink : iconForFilename(attachment.filename);
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
                  {attachment.isExternalLink ? "Linked" : formatBytes(attachment.size)}
                </span>

                <div className="flex flex-none items-center gap-1">
                  <a
                    href={attachment.download_url}
                    target="_blank"
                    rel="noreferrer"
                    download={!attachment.isExternalLink}
                    aria-label={attachment.isExternalLink ? `Open ${attachment.filename}` : `Download ${attachment.filename}`}
                    title={attachment.isExternalLink ? "Opens the original OneDrive/SharePoint link" : "Download"}
                    className="flex h-8 w-8 items-center justify-center rounded-md2 text-muted transition-colors hover:bg-surfaceHover hover:text-accent"
                  >
                    {attachment.isExternalLink ? <ExternalLink size={15} /> : <Download size={15} />}
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
