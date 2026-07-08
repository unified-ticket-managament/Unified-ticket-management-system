import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, Clock, X } from "lucide-react";
import { AttachmentList } from "@/components/common/AttachmentList";
import { Badge } from "@/components/common/Badge";
import { Card } from "@/components/common/Card";
import { formatDateTime } from "@/lib/format";
import { priorityTone } from "@/lib/ticketTone";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type { MailFolder, TicketPriority } from "@/types";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-xs font-medium text-slate-800">{children}</dd>
    </div>
  );
}

const MAIL_STATUS_LABEL: Record<string, string> = {
  PENDING: "Pending",
  ASSIGNED: "Replied",
  IGNORED: "Archived",
};

const SNOOZE_PRESETS: Array<{ label: string; getDate: () => Date }> = [
  { label: "1 hour", getDate: () => new Date(Date.now() + 60 * 60 * 1000) },
  {
    label: "Tomorrow, 9am",
    getDate: () => {
      const d = new Date();
      d.setDate(d.getDate() + 1);
      d.setHours(9, 0, 0, 0);
      return d;
    },
  },
  { label: "1 week", getDate: () => new Date(Date.now() + 7 * 24 * 60 * 60 * 1000) },
];

interface MailDetailsPanelProps {
  folders: MailFolder[];
  onUpdateTags: (interactionId: string, tags: string[]) => Promise<boolean>;
  onAssignFolder: (interactionId: string, folderId: string | null) => Promise<boolean>;
  onSnooze: (interactionId: string, snoozeUntil: string) => Promise<boolean>;
  onUnsnooze: (interactionId: string) => Promise<boolean>;
}

/**
 * The Mail page's info panel — same Card/<dl>/Row pattern as
 * TicketDetails.tsx, but for a pre-ticket Interaction. Priority and
 * Category/Team only exist once this item has become a ticket
 * (neither applies to a bare pre-ticket email), so those rows are
 * conditional on ticket_id being set. Tags/folder are always
 * editable; snooze only applies while the item is still pending and
 * unticketed (mirrors the backend's own guard).
 */
export function MailDetailsPanel({
  folders,
  onUpdateTags,
  onAssignFolder,
  onSnooze,
  onUnsnooze,
}: MailDetailsPanelProps) {
  const { selectedEmail } = useWorkflowContext();
  const [newTag, setNewTag] = useState("");
  const [isSnoozeMenuOpen, setIsSnoozeMenuOpen] = useState(false);

  if (!selectedEmail) return null;

  const isTicketed = Boolean(selectedEmail.ticket_id);
  const statusLabel = isTicketed
    ? "Ticketed"
    : MAIL_STATUS_LABEL[selectedEmail.status] ?? selectedEmail.status;

  const isSnoozed = Boolean(
    selectedEmail.snoozed_until && new Date(selectedEmail.snoozed_until) > new Date()
  );

  async function handleAddTag() {
    const tag = newTag.trim();
    if (!tag || !selectedEmail) return;
    if (selectedEmail.tags.includes(tag)) {
      setNewTag("");
      return;
    }
    await onUpdateTags(selectedEmail.interaction_id, [...selectedEmail.tags, tag]);
    setNewTag("");
  }

  async function handleRemoveTag(tag: string) {
    if (!selectedEmail) return;
    await onUpdateTags(
      selectedEmail.interaction_id,
      selectedEmail.tags.filter((t) => t !== tag)
    );
  }

  async function handleFolderChange(value: string) {
    if (!selectedEmail) return;
    await onAssignFolder(selectedEmail.interaction_id, value || null);
  }

  async function handleSnooze(getDate: () => Date) {
    if (!selectedEmail) return;
    await onSnooze(selectedEmail.interaction_id, getDate().toISOString());
    setIsSnoozeMenuOpen(false);
  }

  return (
    <Card title="Mail Details" eyebrow="Overview">
      <dl className="flex flex-col divide-y divide-border">
        <Row label="Status">
          <Badge tone={isTicketed ? "accent" : selectedEmail.status === "PENDING" ? "warning" : "success"} dot>
            {statusLabel}
          </Badge>
        </Row>
        {selectedEmail.ticket_priority && (
          <Row label="Priority">
            <Badge tone={priorityTone[selectedEmail.ticket_priority as TicketPriority] ?? "default"}>
              {selectedEmail.ticket_priority}
            </Badge>
          </Row>
        )}
        {selectedEmail.ticket_category && <Row label="Team">{selectedEmail.ticket_category}</Row>}
        <Row label="Client">{selectedEmail.client_name}</Row>
        <Row label="Account Manager">{selectedEmail.account_manager_name ?? "—"}</Row>
        <Row label="Assigned To">{selectedEmail.claimed_by_name ?? "Unclaimed"}</Row>
        <Row label="Created On">{formatDateTime(selectedEmail.received_at)}</Row>
        <Row label="Channel">
          <Badge tone="default">Email</Badge>
        </Row>
      </dl>

      <div className="mt-2 border-t border-border pt-4">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Folder</p>
        <select
          value={selectedEmail.folder_id ?? ""}
          onChange={(e) => handleFolderChange(e.target.value)}
          className="w-full cursor-pointer rounded-md2 border border-border bg-white px-2.5 py-1.5 text-[12px] text-slate-700 outline-none focus:ring-2 focus:ring-accent/40"
        >
          <option value="">No folder</option>
          {folders.map((folder) => (
            <option key={folder.folder_id} value={folder.folder_id}>
              {folder.name}
            </option>
          ))}
        </select>
      </div>

      <div className="mt-2 border-t border-border pt-4">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Tags</p>
        <div className="flex flex-wrap gap-1.5">
          {selectedEmail.tags.map((tag) => (
            <span
              key={tag}
              className="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600"
            >
              {tag}
              <button onClick={() => handleRemoveTag(tag)} className="text-slate-400 hover:text-slate-700">
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
        <input
          value={newTag}
          onChange={(e) => setNewTag(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleAddTag();
            }
          }}
          placeholder="Add a tag, press Enter"
          className="mt-2 w-full rounded-md2 border border-border bg-white px-2.5 py-1.5 text-[12px] outline-none focus:ring-2 focus:ring-accent/40"
        />
      </div>

      {!isTicketed && (
        <div className="mt-2 border-t border-border pt-4">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Snooze</p>
          {isSnoozed ? (
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-[12px] text-slate-600">
                <Clock size={13} />
                Until {formatDateTime(selectedEmail.snoozed_until!)}
              </span>
              <button
                onClick={() => onUnsnooze(selectedEmail.interaction_id)}
                className="rounded-md2 border border-border px-2 py-1 text-[11px] font-semibold text-slate-600 hover:bg-surfaceHover"
              >
                Unsnooze
              </button>
            </div>
          ) : (
            <div className="relative">
              <button
                onClick={() => setIsSnoozeMenuOpen((prev) => !prev)}
                className="flex w-full items-center justify-center gap-1.5 rounded-md2 border border-border px-3 py-2 text-[12px] font-semibold text-slate-600 hover:bg-surfaceHover"
              >
                <Clock size={14} />
                Snooze
              </button>
              {isSnoozeMenuOpen && (
                <div className="absolute right-0 z-10 mt-1 w-full rounded-md2 border border-border bg-white py-1 shadow-sm">
                  {SNOOZE_PRESETS.map((preset) => (
                    <button
                      key={preset.label}
                      onClick={() => handleSnooze(preset.getDate)}
                      className="block w-full px-3 py-1.5 text-left text-[12px] text-slate-600 hover:bg-surfaceHover"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {selectedEmail.attachments && selectedEmail.attachments.length > 0 && (
        <div className="mt-2 border-t border-border pt-4">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
            Attachments
          </p>
          <AttachmentList attachments={selectedEmail.attachments} />
        </div>
      )}

      {isTicketed && selectedEmail.ticket_id && (
        <Link
          to={`/tickets/${selectedEmail.ticket_id}`}
          className="mt-4 flex items-center justify-center gap-1.5 rounded-md2 border border-accent/20 bg-accent/5 px-3 py-2 text-[11.5px] font-semibold text-accent transition-colors hover:bg-accent/10"
        >
          View full ticket <ArrowUpRight size={13} />
        </Link>
      )}
    </Card>
  );
}
