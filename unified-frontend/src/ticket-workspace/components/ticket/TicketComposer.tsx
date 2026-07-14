import { useEffect, useMemo, useState } from "react";
import { Lock, Paperclip, X } from "lucide-react";
import { Card } from "@tw/components/common/Card";
import { Button } from "@tw/components/common/Button";
import { EnvelopePreview } from "@tw/components/common/EnvelopePreview";
import { FileDropzone } from "@tw/components/common/FileDropzone";
import { SelectInput, TextArea, TextInput } from "@tw/components/common/FormField";
import { validateFiles } from "@tw/lib/attachmentMeta";
import { useApiAction } from "@tw/hooks/useApiAction";
import { listClientContacts } from "@tw/api/clients";
import { addInternalNote, replyToClient, uploadAttachment } from "@tw/api/interaction";
import { listRbacRoles, listRbacUsers, type RbacUserSummary } from "@tw/api/rbacUsers";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import type { ClientContact } from "@tw/types";

export type ComposerMode = "reply" | "note";

function parseEmails(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

// Fixed display order for the Internal Note "To" dropdown's role
// groups — independent of whatever order the roles table returns.
const TO_ROLE_ORDER = ["Super Admin", "Site Lead", "Account Manager", "Team Lead", "Staff"];

interface TicketComposerProps {
  mode: ComposerMode;
  onClose: () => void;
  onSent: () => void;
  // When true, this composer is being driven by an external tab
  // (Reply / Internal Note) rather than opened via a floating toggle
  // — hides the redundant internal Reply/Internal-note pill so the
  // outer tab is the only place mode is chosen.
  lockMode?: boolean;
  // Rendered inside TicketActivityPanel's tabbed box, which already
  // provides the outer border/shadow — see Card's `flat` prop (same
  // convention TicketTimeline/TicketAuditLog already use there).
  flat?: boolean;
}

export function TicketComposer({
  mode,
  onClose,
  onSent,
  lockMode = false,
  flat = false,
}: TicketComposerProps) {
  const { activeTicket, timeline } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const [activeMode, setActiveMode] = useState<ComposerMode>(mode);
  const [message, setMessage] = useState("");
  const [noteSubject, setNoteSubject] = useState("");
  const [contacts, setContacts] = useState<ClientContact[]>([]);
  const [selectedTo, setSelectedTo] = useState("");

  // Reply Cc/Bcc — both optional, mirroring the backend's own
  // ReplyCreate schema (cc/bcc default to empty lists already; this
  // just exposes fields the UI never surfaced before).
  const [replyCc, setReplyCc] = useState("");
  const [replyBcc, setReplyBcc] = useState("");
  // Reply attachments — local File[] only, uploaded via the existing
  // ticket attachment endpoint right after the reply itself succeeds
  // (same "upload only at Send" pattern Mail's own ticketed
  // ReplyComposer already uses for POST /tickets/{id}/attachments).
  const [replyFiles, setReplyFiles] = useState<File[]>([]);

  // Internal Note "To" — UI-only enhancement (see TicketComposer's
  // task notes): addInternalNote has no recipient concept on the
  // backend, so this never gets sent with the request. It just lets
  // the author indicate who the note is really meant for.
  const [toRoleGroups, setToRoleGroups] = useState<Record<string, RbacUserSummary[]>>({});
  const [toUserId, setToUserId] = useState("");

  // Internal Note "Attach Files" — reuses the exact same ticket
  // attachment upload the "Upload Attachment" action already uses,
  // just made available right next to the note composer too.
  const [showAttach, setShowAttach] = useState(false);
  const [attachFiles, setAttachFiles] = useState<File[]>([]);

  const { run: runReply, isLoading: isReplyLoading } = useApiAction(replyToClient, {
    successMessage: "Reply sent to client.",
  });
  const { run: runNote, isLoading: isNoteLoading } = useApiAction(addInternalNote, {
    successMessage: "Internal note added.",
  });
  const { run: runUpload, isLoading: isUploadLoading } = useApiAction(uploadAttachment, {
    successMessage: (res) =>
      `${res.attachments.length} file${res.attachments.length === 1 ? "" : "s"} uploaded.`,
  });

  useEffect(() => {
    if (lockMode) setActiveMode(mode);
  }, [mode, lockMode]);

  useEffect(() => {
    if (activeMode !== "note") return;
    Promise.all([listRbacUsers(), listRbacRoles()])
      .then(([users, roles]) => {
        const roleNameById = new Map(roles.map((r) => [r.role_id, r.name]));
        const grouped: Record<string, RbacUserSummary[]> = {};
        users
          .filter((u) => u.is_active)
          .forEach((user) => {
            const roleName = roleNameById.get(user.role_id);
            if (!roleName) return;
            (grouped[roleName] ??= []).push(user);
          });
        setToRoleGroups(grouped);
      })
      .catch(() => setToRoleGroups({}));
  }, [activeMode]);

  // Envelope preview — derived from the latest inbound email on this
  // ticket's timeline, so the agent sees exactly where a reply will
  // go before sending it. Trust-building UI, not the source of truth
  // (the backend builds the real envelope independently).
  const latestEmail = useMemo(() => {
    return [...timeline]
      .filter((i) => i.interaction_type === "EMAIL")
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
  }, [timeline]);

  const toEmail = latestEmail?.payload.to_email as string | undefined;
  const fromEmail = latestEmail?.payload.from_email as string | undefined;
  const subject = latestEmail?.payload.subject as string | undefined;

  // Every personal address this client has ever emailed the shared
  // inbox from — lets the agent redirect a reply to a different
  // contact at the same client company instead of always the sender
  // of whichever email happens to be most recent.
  useEffect(() => {
    if (!activeTicket?.client_company_id) {
      setContacts([]);
      return;
    }
    listClientContacts(activeTicket.client_company_id)
      .then(setContacts)
      .catch(() => setContacts([]));
  }, [activeTicket?.client_company_id]);

  // Defaults to the latest inbound email's sender whenever the open
  // ticket changes — the agent can still override it below.
  useEffect(() => {
    setSelectedTo(fromEmail ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTicket?.ticket_id]);

  const toOptions = useMemo(() => {
    const seen = new Set<string>();
    const options: ClientContact[] = [];
    for (const contact of [
      ...(fromEmail ? [{ email: fromEmail, name: null }] : []),
      ...contacts,
    ]) {
      if (seen.has(contact.email)) continue;
      seen.add(contact.email);
      options.push(contact);
    }
    return options;
  }, [contacts, fromEmail]);

  if (!activeTicket) return null;

  const isReply = activeMode === "reply";
  const isLoading = isReply ? isReplyLoading : isNoteLoading;
  const isTicketClosed = activeTicket.current_status === "CLOSED";

  async function handleSend() {
    if (!activeTicket || !message.trim()) return;
    if (!isReply && !noteSubject.trim()) return;

    const result = isReply
      ? await runReply(activeTicket.ticket_id, {
          message,
          to_email: selectedTo || undefined,
          cc: parseEmails(replyCc),
          bcc: parseEmails(replyBcc),
        })
      : await runNote(activeTicket.ticket_id, { note: message, subject: noteSubject });

    if (result) {
      if (isReply && replyFiles.length > 0) {
        await runUpload(activeTicket.ticket_id, replyFiles);
      }
      setMessage("");
      setNoteSubject("");
      setReplyCc("");
      setReplyBcc("");
      setReplyFiles([]);
      onSent();
    }
  }

  async function handleUploadAttachments() {
    if (!activeTicket || attachFiles.length === 0) return;
    const result = await runUpload(activeTicket.ticket_id, attachFiles);
    if (result) {
      setAttachFiles([]);
      setShowAttach(false);
    }
  }

  return (
    <Card
      flat={flat}
      title={isReply ? "Reply" : "Internal Note"}
      eyebrow="Composer"
      actions={
        <button
          onClick={onClose}
          aria-label="Close composer"
          className="flex h-7 w-7 items-center justify-center rounded-md2 text-muted transition-colors hover:bg-surfaceHover hover:text-slate-900"
        >
          <X size={15} />
        </button>
      }
    >
      {isTicketClosed ? (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Lock size={14} className="flex-none" />
          This ticket is closed — reopen it to reply or add a note.
        </p>
      ) : (
      <div className="flex flex-col gap-3">
        {!lockMode && (
          <div className="flex rounded-md2 border border-border p-0.5 text-xs font-semibold">
            <button
              onClick={() => setActiveMode("reply")}
              aria-pressed={isReply}
              className={`flex-1 rounded-[7px] py-1.5 transition-colors ${
                isReply ? "bg-accent/10 text-accent" : "text-muted hover:text-slate-700"
              }`}
            >
              Reply to client
            </button>
            <button
              onClick={() => setActiveMode("note")}
              aria-pressed={!isReply}
              className={`flex-1 rounded-[7px] py-1.5 transition-colors ${
                !isReply ? "bg-warning/10 text-warning" : "text-muted hover:text-slate-700"
              }`}
            >
              Internal note
            </button>
          </div>
        )}

        {isReply ? (
          <>
            {toOptions.length > 1 && (
              <SelectInput
                label="To"
                value={selectedTo}
                onChange={(e) => setSelectedTo(e.target.value)}
              >
                {toOptions.map((contact) => (
                  <option key={contact.email} value={contact.email}>
                    {contact.name ? `${contact.name} <${contact.email}>` : contact.email}
                  </option>
                ))}
              </SelectInput>
            )}
            <EnvelopePreview
              senderName={currentUser?.name ?? "you"}
              viaEmail={toEmail}
              toEmail={selectedTo || fromEmail}
              subject={subject}
            />
            <TextInput
              label="CC (Optional)"
              value={replyCc}
              onChange={(e) => setReplyCc(e.target.value)}
              placeholder="cc@example.com, ..."
            />
            <TextInput
              label="BCC (Optional)"
              value={replyBcc}
              onChange={(e) => setReplyBcc(e.target.value)}
              placeholder="bcc@example.com, ..."
            />
          </>
        ) : (
          <>
            <TextInput
              label="Subject"
              value={noteSubject}
              onChange={(e) => setNoteSubject(e.target.value)}
              placeholder="Short summary shown on the timeline…"
              autoFocus
            />
            <SelectInput
              label="To"
              hint="Who this note is meant for — informational only, doesn't change who can see it."
              value={toUserId}
              onChange={(e) => setToUserId(e.target.value)}
            >
              <option value="">Select a recipient…</option>
              {TO_ROLE_ORDER.filter((role) => (toRoleGroups[role]?.length ?? 0) > 0).map((role) => (
                <optgroup key={role} label={role}>
                  {toRoleGroups[role].map((user) => (
                    <option key={user.user_id} value={user.user_id}>
                      {user.name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </SelectInput>
          </>
        )}

        <TextArea
          label={isReply ? "Message to client" : "Note (visible to agents only)"}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={
            isReply ? "Type a reply the client will see…" : "Type a note only agents can see…"
          }
          autoFocus={isReply}
        />

        {isReply && (
          <FileDropzone label="Attachments" files={replyFiles} onFilesChange={setReplyFiles} />
        )}

        {!isReply && (
          <div className="flex flex-col gap-2">
            <Button
              variant="secondary"
              size="sm"
              type="button"
              className="w-fit"
              onClick={() => setShowAttach((prev) => !prev)}
            >
              <Paperclip size={13} />
              Attach Files{attachFiles.length > 0 ? ` (${attachFiles.length})` : ""}
            </Button>

            {showAttach && (
              <div className="flex flex-col gap-2 rounded-md2 border border-border bg-canvas/40 p-3">
                <FileDropzone label="Files" files={attachFiles} onFilesChange={setAttachFiles} />
                <Button
                  variant="secondary"
                  size="sm"
                  className="w-fit"
                  isLoading={isUploadLoading}
                  disabled={
                    attachFiles.length === 0 || validateFiles(attachFiles).errors.length > 0
                  }
                  onClick={handleUploadAttachments}
                >
                  Upload to ticket
                </Button>
              </div>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            isLoading={isLoading}
            disabled={!message.trim() || (!isReply && !noteSubject.trim())}
            onClick={handleSend}
          >
            {isReply ? "Send Reply" : "Add Note"}
          </Button>
        </div>
      </div>
      )}
    </Card>
  );
}
