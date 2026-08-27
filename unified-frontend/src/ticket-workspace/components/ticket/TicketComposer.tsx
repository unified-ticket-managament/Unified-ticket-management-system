import { useEffect, useMemo, useRef, useState } from "react";
import { Lock, Paperclip, X } from "lucide-react";
import { Card } from "@tw/components/common/Card";
import { Button } from "@tw/components/common/Button";
import { EnvelopePreview } from "@tw/components/common/EnvelopePreview";
import { FileDropzone } from "@tw/components/common/FileDropzone";
import { TextInput } from "@tw/components/common/FormField";
import { MultiRecipientCombobox, type RecipientChip } from "@tw/components/common/MultiRecipientCombobox";
import type { RecipientOption } from "@tw/components/common/RecipientCombobox";
import { RichTextEditor, isRichTextEmpty } from "@tw/components/mail/RichTextEditor";
import { UserMultiSelect } from "@tw/components/common/UserMultiSelect";
import { DistributionListMultiSelect } from "@tw/components/common/DistributionListMultiSelect";
import { validateFiles } from "@tw/lib/attachmentMeta";
import { generateIdempotencyKey } from "@tw/lib/idempotency";
import { useApiAction } from "@tw/hooks/useApiAction";
import { listClientContacts } from "@tw/api/clients";
import {
  addInternalNote,
  discardTicketNoteDraft,
  discardTicketReplyDraft,
  getTicketNoteDraft,
  getTicketReplyDraft,
  listInternalNoteRecipients,
  replyToClient,
  saveTicketNoteDraft,
  saveTicketReplyDraft,
  uploadAttachment,
  uploadTicketInlineImage,
} from "@tw/api/interaction";
import type { SelectableUser } from "@tw/components/common/UserMultiSelect";
import { useAuthContext } from "@tw/context/AuthContext";
import { useToast } from "@tw/context/ToastContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { isValidEmailAddress } from "@tw/lib/validation";
import { showUndoSendToast } from "@tw/lib/undoSend";
import {
  escapeHtml,
  filterLiveInlineImageIds,
  htmlToPlainText,
  isRichContent,
  resolveInlineImageSources,
  type TrackedInlineImage,
} from "@tw/lib/richText";
import type { ClientContact } from "@tw/types";
// Cross-alias imports, same deliberate exception MessageDetailsView.tsx
// already documents: useAuthContext() only re-exposes the store's
// last-set snapshot read-only, and there is no @tw/-side equivalent
// for a live /auth/me refetch + store sync.
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";

export type ComposerMode = "reply" | "note";

function parseEmails(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

// Fixed display order for the Internal Note "To" dropdown's role
// groups — independent of whatever order the API returns. Every
// eligible platform role: none is excluded on hierarchy grounds.
const TO_ROLE_ORDER = [
  "Super Admin",
  "Site Lead",
  "Account Manager",
  "Team Lead",
  "Staff",
  "Client",
];

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
  const { pushToast } = useToast();
  const setUser = useAuthStore((s) => s.setUser);
  const [activeMode, setActiveMode] = useState<ComposerMode>(mode);
  // HTML string (Tiptap), not plain text — see RichTextEditor.tsx.
  // Flattened to plain text (htmlToPlainText) at send time for the
  // always-required `message`/`note` field, with a sanitized-on-the-
  // backend HTML counterpart sent alongside it as `body_html` when
  // the content actually contains real formatting/a table/an inline
  // image (isRichContent) — see handleSend below.
  const [messageHtml, setMessageHtml] = useState("");
  const [hasPendingImageUploads, setHasPendingImageUploads] = useState(false);
  // Every interaction_id a pasted-screenshot upload returned during
  // this compose session — unlike a regular file attachment, a
  // pasted image is uploaded to its own standalone interaction (see
  // AttachmentService.upload_inline_image) that must be explicitly
  // submitted back at Send time so the backend can reassign it onto
  // the real reply/note and actually embed it (see
  // InteractionService._merge_inline_images_into_envelope) — without
  // this the image would silently never reach the outbound email.
  // Tracked as {interactionId, contentId} pairs (not just the id)
  // so a deleted/replaced image can be filtered back out at Send
  // time via filterLiveInlineImageIds — see handleSend below.
  const pastedImageInteractionIdsRef = useRef<TrackedInlineImage[]>([]);
  // One Send idempotency key per in-progress reply, not one per
  // click — a double-click (or a manual retry after a failure) must
  // reuse the same key so the backend's own dedup (a unique index on
  // the key) can actually collapse them. Unlike a Compose/Reply
  // modal, this composer stays mounted across sends (fields just
  // reset in place), so the key is explicitly regenerated after a
  // successful send and on ticket change, below — never on every
  // handleSend call.
  const idempotencyKeyRef = useRef<string>(generateIdempotencyKey());
  const [noteSubject, setNoteSubject] = useState("");
  const [contacts, setContacts] = useState<ClientContact[]>([]);
  // Reply's "To" — multiple recipients supported via to_emails (the
  // backend's ReplyCreate already has both to_email and its plural
  // to_emails counterpart; only this frontend picker was capped at
  // one). Each chip is either a known contact or a manually-typed
  // external address — MultiRecipientCombobox validates/adds both the
  // same way, so there's no separate per-chip "matched" tracking
  // needed here (unlike Forward's internal-user-vs-external split in
  // ComposeView.tsx).
  const [toChips, setToChips] = useState<RecipientChip[]>([]);

  // Reply Cc/Bcc — both optional, mirroring the backend's own
  // ReplyCreate schema (cc/bcc default to empty lists already; this
  // just exposes fields the UI never surfaced before).
  const [replyCc, setReplyCc] = useState("");
  const [replyBcc, setReplyBcc] = useState("");
  const [replyDistributionListIds, setReplyDistributionListIds] = useState<string[]>([]);
  // A non-empty Cc/Bcc entry must still be a real address — this used
  // to have no frontend validation at all (an invalid entry only ever
  // got caught by the backend's own EmailStr rejection, with no
  // visible error and no Send-button gating), matching the same gap
  // Compose's own Cc/Bcc fields had before ComposeView.tsx's canSend
  // was fixed.
  const replyCcEntries = useMemo(() => parseEmails(replyCc), [replyCc]);
  const replyBccEntries = useMemo(() => parseEmails(replyBcc), [replyBcc]);
  const invalidReplyCcEntries = useMemo(
    () => replyCcEntries.filter((entry) => !isValidEmailAddress(entry)),
    [replyCcEntries]
  );
  const invalidReplyBccEntries = useMemo(
    () => replyBccEntries.filter((entry) => !isValidEmailAddress(entry)),
    [replyBccEntries]
  );
  // Reply attachments — local File[] only, uploaded via the existing
  // ticket attachment endpoint right after the reply itself succeeds
  // (same "upload only at Send" pattern Mail's own ticketed
  // ReplyComposer already uses for POST /tickets/{id}/attachments).
  const [replyFiles, setReplyFiles] = useState<File[]>([]);

  // Internal Note To/CC/BCC — "To" is a real recipient list now: it's
  // sent as recipient_user_ids and the backend delivers the note
  // specifically to those users' Mail > System, on top of its
  // existing Timeline/Interaction storage (see add_internal_note).
  // CC/BCC remain the pre-existing UI-only affordance — the backend
  // has no CC/BCC delivery concept for internal notes, and this pass
  // deliberately didn't add one (only "To" was in scope).
  const [toRoleGroups, setToRoleGroups] = useState<Record<string, SelectableUser[]>>({});
  const [noteToIds, setNoteToIds] = useState<string[]>([]);
  const [noteCcIds, setNoteCcIds] = useState<string[]>([]);
  const [noteBccIds, setNoteBccIds] = useState<string[]>([]);
  const [noteDistributionListIds, setNoteDistributionListIds] = useState<string[]>([]);

  // Internal Note "Attach Files" — reuses the exact same ticket
  // attachment upload the "Upload Attachment" action already uses,
  // just made available right next to the note composer too.
  const [showAttach, setShowAttach] = useState(false);
  const [attachFiles, setAttachFiles] = useState<File[]>([]);

  // No successMessage here — handleSend below shows an Undo-capable
  // toast instead of a plain one (Issue 8).
  const { run: runReply, isLoading: isReplyLoading } = useApiAction(replyToClient);
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
    // Every eligible active platform user, unscoped by hierarchy —
    // see GET /tickets/internal-notes/recipients' own docstring for
    // why this is a dedicated endpoint rather than RBAC's own
    // (hierarchy-scoped) GET /api/v1/users + (role:view-gated)
    // GET /api/v1/roles.
    listInternalNoteRecipients()
      .then((candidates) => {
        const grouped: Record<string, SelectableUser[]> = {};
        candidates.forEach((candidate) => {
          (grouped[candidate.role_name] ??= []).push(candidate);
        });
        setToRoleGroups(grouped);
      })
      .catch(() => setToRoleGroups({}));
  }, [activeMode]);

  // currentUser.permissions above is a render-time snapshot of
  // whatever useAuthStore held at login/last full page load — a
  // permission granted to the user's role afterward (e.g. via the
  // Roles page) never reaches it, since neither the axios 401/refresh
  // interceptor nor any polling re-syncs the store mid-session (see
  // MessageDetailsView.tsx's identical belt-and-suspenders comment for
  // the Reply path). Re-fetching here means switching to the Internal
  // Note tab always reflects the user's actual, current
  // communication:reply_internal grant rather than a stale one.
  useEffect(() => {
    if (activeMode !== "note") return;
    authService.me().then(setUser).catch(() => {});
  }, [activeMode, setUser]);

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
  // ticket changes — the agent can still override it below. Also
  // resets every other field a saved draft might otherwise leave
  // stale from a previously-open ticket — the draft-load effect just
  // below re-populates them from a real saved draft, if one exists,
  // right after this runs.
  useEffect(() => {
    setToChips(fromEmail ? [{ email: fromEmail }] : []);
    setReplyCc("");
    setReplyBcc("");
    setNoteSubject("");
    setNoteToIds([]);
    setMessageHtml("");
    idempotencyKeyRef.current = generateIdempotencyKey();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTicket?.ticket_id]);

  const replyDraftIdRef = useRef<string | null>(null);
  const noteDraftIdRef = useRef<string | null>(null);
  const [draftStatus, setDraftStatus] = useState<"idle" | "saving" | "saved">("idle");
  const savedIndicatorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const skipNextAutoSaveRef = useRef(true);

  // Loads any existing draft for the current (ticket, mode) pair and
  // pre-fills the composer — mirrors Mail's own "opening a thread
  // that already has a saved draft auto-populates the composer"
  // behavior for pre-ticket Reply drafts (see ReplyComposer.tsx/
  // MessageDetailsView.tsx). A 404 (no draft) is expected, not an
  // error — the fields above were already reset to blank by the
  // ticket-change effect right above, or are simply left as-is on a
  // mode toggle within the same ticket (matching this component's
  // own pre-existing "messageHtml is shared across Reply/Note" design
  // — a mode switch was never a hard reset even before drafts).
  useEffect(() => {
    if (!activeTicket) return;
    skipNextAutoSaveRef.current = true;
    let cancelled = false;

    if (activeMode === "reply") {
      replyDraftIdRef.current = null;
      getTicketReplyDraft(activeTicket.ticket_id)
        .then((draft) => {
          if (cancelled) return;
          replyDraftIdRef.current = draft.interaction_id;
          const chips: RecipientChip[] = [
            ...(draft.to_email ? [{ email: draft.to_email }] : []),
            ...draft.to_emails.map((email) => ({ email })),
          ];
          if (chips.length > 0) setToChips(chips);
          if (draft.cc.length > 0) setReplyCc(draft.cc.join(", "));
          if (draft.bcc.length > 0) setReplyBcc(draft.bcc.join(", "));
          if (draft.body_html) {
            setMessageHtml(draft.body_html);
          } else if (draft.message) {
            setMessageHtml(`<p>${escapeHtml(draft.message).replace(/\n/g, "<br/>")}</p>`);
          }
        })
        .catch(() => {
          if (!cancelled) replyDraftIdRef.current = null;
        });
    } else {
      noteDraftIdRef.current = null;
      getTicketNoteDraft(activeTicket.ticket_id)
        .then((draft) => {
          if (cancelled) return;
          noteDraftIdRef.current = draft.interaction_id;
          setNoteSubject(draft.subject);
          if (draft.recipient_user_ids.length > 0) setNoteToIds(draft.recipient_user_ids);
          if (draft.body_html) {
            setMessageHtml(draft.body_html);
          } else if (draft.note) {
            setMessageHtml(`<p>${escapeHtml(draft.note).replace(/\n/g, "<br/>")}</p>`);
          }
        })
        .catch(() => {
          if (!cancelled) noteDraftIdRef.current = null;
        });
    }

    return () => {
      cancelled = true;
    };
  }, [activeTicket?.ticket_id, activeMode]);

  // Upserts the current mode's draft on this ticket — creates it on
  // the first call, updates it in place on every subsequent one.
  // Attachments are deliberately never part of this (see this
  // composer's own replyFiles/attachFiles — both stay local, uploaded
  // fresh at Send time, unchanged from before drafts existed).
  async function persistDraft() {
    if (!activeTicket) return null;
    setDraftStatus("saving");
    try {
      if (activeMode === "reply") {
        const toEntries = toChips.map((chip) => chip.email);
        const result = await saveTicketReplyDraft(activeTicket.ticket_id, {
          to_email: toEntries[0],
          to_emails: toEntries.slice(1),
          cc: parseEmails(replyCc),
          bcc: parseEmails(replyBcc),
          message: htmlToPlainText(messageHtml),
          body_html: isRichContent(messageHtml) ? resolveInlineImageSources(messageHtml) : undefined,
        });
        replyDraftIdRef.current = result.interaction_id;
      } else {
        const result = await saveTicketNoteDraft(activeTicket.ticket_id, {
          subject: noteSubject,
          note: htmlToPlainText(messageHtml),
          body_html: isRichContent(messageHtml) ? resolveInlineImageSources(messageHtml) : undefined,
          recipient_user_ids: noteToIds,
        });
        noteDraftIdRef.current = result.interaction_id;
      }
      setDraftStatus("saved");
      if (savedIndicatorTimerRef.current) clearTimeout(savedIndicatorTimerRef.current);
      savedIndicatorTimerRef.current = setTimeout(() => setDraftStatus("idle"), 2500);
      return true;
    } catch {
      setDraftStatus("idle");
      return null;
    }
  }

  // Continuous auto-save — debounced, skips the very first render
  // after a ticket/mode switch (the effect above may still be loading
  // a saved draft, or the fields were just reset to blank) so opening
  // the composer never immediately re-saves whatever it was just
  // given. An entirely untouched draft (nothing typed/selected yet)
  // is never saved either.
  useEffect(() => {
    if (!activeTicket) return;
    if (skipNextAutoSaveRef.current) {
      skipNextAutoSaveRef.current = false;
      return;
    }
    const isUntouched =
      activeMode === "reply"
        ? toChips.length === 0 &&
          !replyCc.trim() &&
          !replyBcc.trim() &&
          isRichTextEmpty(messageHtml)
        : !noteSubject.trim() && noteToIds.length === 0 && isRichTextEmpty(messageHtml);
    if (isUntouched) return;

    const timer = setTimeout(() => {
      persistDraft();
    }, 1200);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTicket?.ticket_id, activeMode, toChips, replyCc, replyBcc, noteSubject, noteToIds, messageHtml]);

  useEffect(() => {
    return () => {
      if (savedIndicatorTimerRef.current) clearTimeout(savedIndicatorTimerRef.current);
    };
  }, []);

  async function handleSaveDraft() {
    const result = await persistDraft();
    pushToast(result ? "Draft saved." : "Couldn't save draft. Try again.", result ? "success" : "error");
  }

  const toRecipientOptions = useMemo(() => {
    const seen = new Set<string>();
    const options: RecipientOption[] = [];
    for (const contact of [
      ...(fromEmail ? [{ email: fromEmail, name: null as string | null }] : []),
      ...contacts,
    ]) {
      if (seen.has(contact.email)) continue;
      seen.add(contact.email);
      options.push({
        id: contact.email,
        label: contact.name ?? contact.email,
        email: contact.email,
        sublabel: contact.name ? contact.email : undefined,
      });
    }
    return options;
  }, [contacts, fromEmail]);

  if (!activeTicket) return null;

  const isReply = activeMode === "reply";
  // For Reply, this must also cover the attachment pre-upload step
  // handleSend runs before runReply itself starts (see below) — the
  // Send button's disabled state is bound to isLoading, and without
  // isUploadLoading here it stayed clickable for the whole upload,
  // letting a second click fire a second, differently-keyed send.
  const isLoading = isReply ? isReplyLoading || isUploadLoading : isNoteLoading;
  const isTicketClosed = activeTicket.current_status === "CLOSED";

  // ticket:reply and communication:reply_internal are independent UI gates —
  // one governs only the Reply interface, the other only the Internal Note
  // interface. The backend's own add_reply/add_internal_note enforcement
  // (interaction_service.py) is stricter (it requires both together) and
  // remains the real security boundary; this check only controls whether
  // the tab's compose UI is enabled here.
  const permissions = currentUser?.permissions ?? [];
  const canReply = permissions.includes("ticket:reply");
  const canAddNote = permissions.includes("communication:reply_internal");
  const hasComposePermission = isReply ? canReply : canAddNote;

  async function handleSend() {
    if (!activeTicket || isRichTextEmpty(messageHtml) || !hasComposePermission) return;
    if (!isReply && !noteSubject.trim()) return;
    // Every "To" chip is already validated (or matched against a
    // known contact) at add-time by MultiRecipientCombobox, so there's
    // no separate invalid-entry check needed here the way Cc/Bcc's
    // plain comma-separated text fields still need.
    if (isReply && (invalidReplyCcEntries.length > 0 || invalidReplyBccEntries.length > 0)) return;
    // A pasted screenshot's upload is still in flight — block Send
    // rather than silently sending the message without it.
    if (hasPendingImageUploads) return;

    // Reply attachments are uploaded *before* the reply itself (not
    // after) so the reply can reference them via
    // attachment_source_interaction_id — the backend embeds them in
    // the actual outbound Graph email that way. Uploading afterward
    // (the old order) only ever recorded them on the ticket's own
    // timeline, never on the sent mail. See Mail's own ReplyComposer/
    // MessageDetailsView.tsx for the identical fix applied there.
    let attachmentSourceInteractionId: string | undefined;
    if (isReply && replyFiles.length > 0) {
      const uploadResult = await runUpload(activeTicket.ticket_id, replyFiles);
      if (!uploadResult) return;
      attachmentSourceInteractionId = uploadResult.interaction_id;
    }

    const plainMessage = htmlToPlainText(messageHtml);
    const bodyHtml = isRichContent(messageHtml)
      ? resolveInlineImageSources(messageHtml)
      : undefined;
    // Only submit ids for images still actually present (as a real
    // cid: reference) in the body being sent — a paste-then-delete/
    // replace/undo before Send must not resurrect a stale attachment.
    // See lib/richText.ts's filterLiveInlineImageIds for why this is
    // needed on top of resolveInlineImageSources alone.
    const liveInlineImageInteractionIds = filterLiveInlineImageIds(
      bodyHtml ?? "",
      pastedImageInteractionIdsRef.current
    );

    const result = isReply
      ? await runReply(activeTicket.ticket_id, {
          message: plainMessage,
          body_html: bodyHtml,
          to_emails: toChips.length > 0 ? toChips.map((chip) => chip.email) : undefined,
          cc: parseEmails(replyCc),
          bcc: parseEmails(replyBcc),
          distribution_list_ids: replyDistributionListIds,
          attachment_source_interaction_id: attachmentSourceInteractionId,
          inline_image_interaction_ids: liveInlineImageInteractionIds,
          idempotency_key: idempotencyKeyRef.current,
        })
      : await runNote(activeTicket.ticket_id, {
          note: plainMessage,
          body_html: bodyHtml,
          subject: noteSubject,
          recipient_user_ids: noteToIds,
          distribution_list_ids: noteDistributionListIds,
          inline_image_interaction_ids: liveInlineImageInteractionIds,
        });

    if (result) {
      if (isReply) {
        // Only the Reply path is a real outbound send — Internal
        // Note is never dispatched, so it gets a plain success toast,
        // never a misleading Undo button (see undo_send's own
        // PENDING_SEND gate — a note's interaction never reaches it).
        showUndoSendToast(pushToast, (result as { interaction_id: string | null }).interaction_id, "Reply sent to client.");
      } else {
        pushToast("Internal note added.", "success");
      }
      if (isReply) idempotencyKeyRef.current = generateIdempotencyKey();
      pastedImageInteractionIdsRef.current = [];
      setMessageHtml("");
      setNoteSubject("");
      setReplyCc("");
      setReplyBcc("");
      setReplyDistributionListIds([]);
      setReplyFiles([]);
      setNoteToIds([]);
      setNoteCcIds([]);
      setNoteBccIds([]);
      setNoteDistributionListIds([]);
      // The message just sent through the normal reply/note path
      // above (unchanged, already-tested) — any draft this session
      // had been autosaving is now obsolete.
      if (isReply && replyDraftIdRef.current) {
        discardTicketReplyDraft(activeTicket.ticket_id).catch(() => {});
        replyDraftIdRef.current = null;
      } else if (!isReply && noteDraftIdRef.current) {
        discardTicketNoteDraft(activeTicket.ticket_id).catch(() => {});
        noteDraftIdRef.current = null;
      }
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

        {!hasComposePermission ? (
          <p className="flex items-center gap-2 text-sm text-muted" role="alert">
            <Lock size={14} className="flex-none" />
            {isReply
              ? "You don't have permission to reply to this ticket."
              : "You don't have permission to add an internal note to this ticket."}
          </p>
        ) : (
        <>
        {isReply ? (
          <>
            <MultiRecipientCombobox
              label="To"
              options={toRecipientOptions}
              value={toChips}
              onChange={setToChips}
              resetKey={activeTicket.ticket_id}
              placeholder="Select a contact or type an email…"
            />
            <EnvelopePreview
              senderName={currentUser?.name ?? "you"}
              viaEmail={toEmail}
              toEmail={toChips.length > 0 ? toChips.map((chip) => chip.email).join(", ") : fromEmail}
              subject={subject}
            />
            <TextInput
              label="CC (Optional)"
              value={replyCc}
              onChange={(e) => setReplyCc(e.target.value)}
              placeholder="cc@example.com, ..."
            />
            {invalidReplyCcEntries.length > 0 && (
              <p className="-mt-1 text-[11px] text-red-600">
                {invalidReplyCcEntries.length === 1
                  ? `Enter a valid email address. "${invalidReplyCcEntries[0]}" isn't valid.`
                  : "Enter a valid email address for every entry, separated by commas."}
              </p>
            )}
            <TextInput
              label="BCC (Optional)"
              value={replyBcc}
              onChange={(e) => setReplyBcc(e.target.value)}
              placeholder="bcc@example.com, ..."
            />
            {invalidReplyBccEntries.length > 0 && (
              <p className="-mt-1 text-[11px] text-red-600">
                {invalidReplyBccEntries.length === 1
                  ? `Enter a valid email address. "${invalidReplyBccEntries[0]}" isn't valid.`
                  : "Enter a valid email address for every entry, separated by commas."}
              </p>
            )}
            <DistributionListMultiSelect
              label="Distribution Groups (Cc)"
              selectedIds={replyDistributionListIds}
              onChange={setReplyDistributionListIds}
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
            <UserMultiSelect
              label="To"
              hint="Delivered to each selected user's Mail > System. Doesn't grant them ticket access."
              groups={toRoleGroups}
              roleOrder={TO_ROLE_ORDER}
              selectedIds={noteToIds}
              onChange={setNoteToIds}
            />
            <DistributionListMultiSelect
              label="Distribution Groups (To)"
              hint="Each active member is added as a note recipient, same as an individually-picked user."
              selectedIds={noteDistributionListIds}
              onChange={setNoteDistributionListIds}
            />
            <UserMultiSelect
              label="CC (Optional)"
              groups={toRoleGroups}
              roleOrder={TO_ROLE_ORDER}
              selectedIds={noteCcIds}
              onChange={setNoteCcIds}
            />
            <UserMultiSelect
              label="BCC (Optional)"
              groups={toRoleGroups}
              roleOrder={TO_ROLE_ORDER}
              selectedIds={noteBccIds}
              onChange={setNoteBccIds}
            />
          </>
        )}

        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-muted">
            {isReply ? "Message to client" : "Note (visible to agents only)"}
          </label>
          <RichTextEditor
            value={messageHtml}
            onChange={setMessageHtml}
            placeholder={
              isReply
                ? "Type a reply the client will see…"
                : "Type a note only agents can see…"
            }
            onImageUpload={
              activeTicket
                ? (file) =>
                    uploadTicketInlineImage(activeTicket.ticket_id, file).then((res) => {
                      pastedImageInteractionIdsRef.current.push({
                        interactionId: res.interaction_id,
                        contentId: res.content_id,
                      });
                      return { attachmentId: res.id, contentId: res.content_id };
                    })
                : undefined
            }
            onPendingImageUploadsChange={setHasPendingImageUploads}
          />
        </div>

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
              Attachments{attachFiles.length > 0 ? ` (${attachFiles.length})` : ""}
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

        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] text-muted">
            {draftStatus === "saving" && "Saving draft…"}
            {draftStatus === "saved" && "Draft saved"}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={!hasComposePermission || draftStatus === "saving"}
              onClick={handleSaveDraft}
            >
              Save Draft
            </Button>
            <Button
              variant="primary"
              size="sm"
              isLoading={isLoading}
              disabled={
                !hasComposePermission ||
                isRichTextEmpty(messageHtml) ||
                (!isReply && !noteSubject.trim()) ||
                (isReply && (invalidReplyCcEntries.length > 0 || invalidReplyBccEntries.length > 0)) ||
                hasPendingImageUploads
              }
              onClick={handleSend}
            >
              {isReply ? "Send Reply" : "Add Note"}
            </Button>
          </div>
        </div>
        </>
        )}
      </div>
      )}
    </Card>
  );
}
