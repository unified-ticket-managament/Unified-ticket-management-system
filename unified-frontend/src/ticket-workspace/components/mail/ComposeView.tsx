"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Save, Send, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { WorkflowLoader } from "@/components/common/WorkflowLoader";
import { AttachmentUploader } from "@tw/components/mail/AttachmentUploader";
import { RichTextEditor, isRichTextEmpty } from "@tw/components/mail/RichTextEditor";
import { listInternalNoteRecipients } from "@tw/api/interaction";
import { uploadComposeInlineImage } from "@tw/api/inbox";
import { listClientContacts } from "@tw/api/clients";
import { RecipientCombobox } from "@tw/components/common/RecipientCombobox";
import type { RecipientOption } from "@tw/components/common/RecipientCombobox";
import { useAuthContext } from "@tw/context/AuthContext";
import { useToast } from "@tw/context/ToastContext";
import { htmlToPlainText, isRichContent, resolveInlineImageSources } from "@tw/lib/richText";
import { isValidEmailAddress } from "@tw/lib/validation";
import { MAX_ATTACHMENT_FILES } from "@tw/lib/attachmentMeta";
import type { ClientContact, ClientResponse, InternalNoteRecipientCandidate } from "@tw/types";

const LOCAL_DRAFT_KEY = "utms-mail-compose-draft";

// Who Forward's "To" picker may target — every internal org role
// except the client-facing Client role (renamed from "Viewer"), in
// display order. Filtering
// further by department/category/reporting hierarchy was considered
// but no existing internal-recipient selector in this codebase (the
// Internal Note To/CC/BCC picker included) actually does that — this
// mirrors that same established, company-wide-by-role convention
// rather than inventing new scoping rules.
const INTERNAL_RECIPIENT_ROLE_ORDER = [
  "Super Admin",
  "Site Lead",
  "Account Manager",
  "Team Lead",
  "Staff",
];

export interface ComposeInitialValues {
  clientId?: string | null;
  toEmail?: string;
  subject?: string;
  bodyHtml?: string;
  // Set only when this view was opened via Forward (see
  // InboxPage.tsx's handleForward) — swaps the "To" field from the
  // client picker (Compose's own recipient concept) to an internal-
  // org-user picker, since forwarding a message is an internal hand-
  // off, never a new outbound message to a client.
  mode?: "forward";
  // The original interaction being forwarded (forward mode only) —
  // needed so the backend can preserve the original-message/ticket
  // relationship on the resulting communication.
  interactionId?: string;
  // How many attachments the original message already has (forward
  // mode only) — used to cap newly-added attachments so original +
  // new never exceeds the 10-attachment total the backend enforces.
  originalAttachmentCount?: number;
}

interface LocalDraft {
  clientId: string;
  toEmail: string;
  cc: string;
  bcc: string;
  subject: string;
  bodyHtml: string;
}

function readLocalDraft(): LocalDraft | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LOCAL_DRAFT_KEY);
    return raw ? (JSON.parse(raw) as LocalDraft) : null;
  } catch {
    return null;
  }
}

function clearLocalDraft() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(LOCAL_DRAFT_KEY);
}

interface ComposeViewProps {
  clients: ClientResponse[];
  // Distinguishes "still fetching the client list" and "the fetch
  // failed" from "fetched fine, and there are genuinely zero clients"
  // — all three used to look identical (`clients` is an empty array
  // in every case), which is what let the empty-state message render
  // while the request was still in flight.
  clientsLoading: boolean;
  clientsError: boolean;
  initialValues?: ComposeInitialValues;
  isSending: boolean;
  onSend: (payload: {
    clientId: string;
    toEmail: string;
    subject: string;
    message: string;
    bodyHtml?: string;
    cc: string[];
    bcc: string[];
    files: File[];
    inlineImageInteractionIds?: string[];
  }) => Promise<unknown>;
  // Forward mode's own Send path — distinct from onSend since
  // forwarding can address either an internal organization user (by
  // user_id, resolved server-side to their real email) or an
  // arbitrary external address (recipientEmail, e.g. another
  // client's mailbox), and creates a different kind of communication
  // (see InteractionService.forward_to_internal_user). Exactly one of
  // recipientUserId/recipientEmail is set. Only required when
  // initialValues.mode === "forward".
  onForwardSend?: (payload: {
    interactionId: string;
    clientId: string;
    recipientUserId?: string;
    recipientEmail?: string;
    cc?: string[];
    bcc?: string[];
    subject: string;
    message: string;
    files: File[];
    bodyHtml?: string;
    inlineImageInteractionIds?: string[];
  }) => Promise<unknown>;
  onDiscard: () => void;
  // Only rendered (as a "← Back" control) when this view is in
  // Forward mode — Discard already covers "abandon and return to the
  // inbox" for a brand-new Compose; Back specifically returns to the
  // exact message that was being forwarded, preserving the mailbox/
  // selection/scroll state the task's Back-button requirement asks
  // for, with no new routing (see InboxPage.tsx's handleComposeBack).
  onBack?: () => void;
  // See MessageDetailsView's identical prop for the full rationale —
  // "panel" drops this component's own card chrome when it renders
  // inside the Mail workspace's own already-chromed panel.
  variant?: "standalone" | "panel";
}

function parseEmails(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

// View 3 — replaces the right pane in-place when Compose is clicked
// (never navigation). "Save Draft" here is genuinely functional but
// local-only (browser storage): unlike Reply, a brand-new Compose
// message has no existing thread row for a server-side draft to
// attach to yet — the send itself is what creates that row. Local
// persistence is real (survives navigating away and back), just not
// synced across devices, and is disclosed as such rather than
// silently pretending it's server-backed.
export function ComposeView({
  clients,
  clientsLoading,
  clientsError,
  initialValues,
  isSending,
  onSend,
  onForwardSend,
  onDiscard,
  onBack,
  variant = "standalone",
}: ComposeViewProps) {
  const { currentUser } = useAuthContext();
  const { pushToast } = useToast();
  const isForward = initialValues?.mode === "forward";

  // `communication:reply_external` (the same permission that gates
  // Reply/Reply All on an already-ticketed message, see
  // MessageDetailsView.tsx's canReplyExternal) is the source of truth
  // for whether the current user may compose external mail at all —
  // this used to be a hardcoded role check that ignored it entirely
  // (any role other than Account Manager/Site Lead/Super Admin was
  // unconditionally blocked, even one granted the permission via the
  // Roles UI, e.g. Team Lead). The backend's ensure_can_compose_for_
  // client (interaction_service.compose_email's authorization) is the
  // matching, final source of truth — this is only the UI-side gate,
  // kept in sync with it rather than duplicating a separate rule.
  const canComposeExternally = !!currentUser?.permissions.includes(
    "communication:reply_external"
  );

  const composableClients = useMemo(() => {
    if (!currentUser || !canComposeExternally) return [];
    if (currentUser.role === "Account Manager") {
      return clients.filter((c) => c.account_manager_id === currentUser.user_id);
    }
    // Every other role holding the permission (Site Lead/Super Admin,
    // and now any role explicitly granted it, e.g. Team Lead) is
    // unrestricted — Compose has no per-role client-ownership concept
    // outside Account Manager's own-clients business rule, and
    // Client itself carries no category/team-lead field to scope by.
    return clients;
  }, [clients, currentUser, canComposeExternally]);

  const localDraft = useMemo(() => (initialValues ? null : readLocalDraft()), [initialValues]);

  // "From" — which client this message is filed under (still a
  // required field on POST /inbox/compose regardless of who the
  // actual recipient turns out to be). Picking one here is what
  // drives the "To" field's contact suggestions below; it no longer
  // doubles as the recipient itself, which is also what fixes the
  // "external address left Send disabled" bug — canSend (below) no
  // longer requires the "To" text to match a client at all.
  const [clientId, setClientId] = useState(initialValues?.clientId ?? localDraft?.clientId ?? "");
  // "To" — the actual recipient(s). A plain comma-separated address
  // list, same convention as Cc/Bcc (parseEmails below) rather than a
  // chip UI, so entering more than one is just typing/selecting more
  // than once. Independent of clientId: a manually-typed external
  // address is exactly as valid a recipient as a dropdown-picked
  // contact, which is what makes canSend correct for both cases.
  const [toEmail, setToEmail] = useState(initialValues?.toEmail ?? localDraft?.toEmail ?? "");
  // Combobox UI state for the (non-forward) "To" field below — the
  // input's value IS toEmail itself (no separate query string).
  const [showToSuggestions, setShowToSuggestions] = useState(false);
  // Known contact addresses for the selected "From" client — backs
  // the "To" suggestion dropdown, same listClientContacts endpoint
  // TicketComposer.tsx/MessageDetailsView.tsx already use for their
  // own reply "To" pickers.
  const [clientContacts, setClientContacts] = useState<ClientContact[]>([]);
  const [cc, setCc] = useState(localDraft?.cc ?? "");
  const [bcc, setBcc] = useState(localDraft?.bcc ?? "");
  const [subject, setSubject] = useState(initialValues?.subject ?? localDraft?.subject ?? "");
  const [bodyHtml, setBodyHtml] = useState(initialValues?.bodyHtml ?? localDraft?.bodyHtml ?? "");
  const [files, setFiles] = useState<File[]>([]);
  const [hasPendingImageUploads, setHasPendingImageUploads] = useState(false);
  // Interaction ids of any screenshot pasted/dropped into the editor,
  // staged via uploadComposeInlineImage (see RichTextEditor's
  // onImageUpload below) and reassigned onto the real outbound
  // message at Send time — same pattern TicketComposer.tsx already
  // uses via pastedImageInteractionIdsRef for Reply/Note.
  const pastedImageInteractionIdsRef = useRef<string[]>([]);

  async function handleComposeImageUpload(file: File) {
    const res = await uploadComposeInlineImage(file);
    pastedImageInteractionIdsRef.current.push(res.interaction_id);
    return { attachmentId: res.id, contentId: res.content_id };
  }

  // Forward's "To" data source — every active internal user. Fetched
  // only in Forward mode (Compose's own client picker needs none of
  // this).
  //
  // Sourced from listInternalNoteRecipients() (GET /tickets/internal-
  // notes/recipients) — the same unscoped, company-wide "every active
  // user + role_name" endpoint the Internal Note "To" picker and the
  // Rules "Forward To" picker were both already fixed to use, for the
  // identical reason: listRbacUsers()/listRbacRoles() (RBAC's own
  // hierarchy-scoped GET /api/v1/users + role:view-gated GET
  // /api/v1/roles) silently under-populates or empties out entirely
  // for Account Manager/Team Lead/Staff senders.
  const [allInternalUsers, setAllInternalUsers] = useState<InternalNoteRecipientCandidate[]>([]);
  // The resolved recipient — userId set only when the current value
  // matches a known internal user (selected from the dropdown, or an
  // exact-matching typed email); otherwise this is a genuinely custom
  // external address and only email is set. Exactly one of the two
  // is sent to the backend (see handleSend's forward branch).
  const [toRecipient, setToRecipient] = useState<{ userId?: string; email: string }>({ email: "" });

  useEffect(() => {
    if (!isForward) return;
    let cancelled = false;
    listInternalNoteRecipients()
      .then((candidates) => {
        if (cancelled) return;
        const eligible = candidates.filter(
          (u) => u.user_id !== currentUser?.user_id && INTERNAL_RECIPIENT_ROLE_ORDER.includes(u.role_name)
        );
        setAllInternalUsers(eligible);
      })
      .catch(() => {
        if (!cancelled) setAllInternalUsers([]);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isForward]);

  const internalRecipientOptions = useMemo<RecipientOption[]>(
    () =>
      allInternalUsers.map((user) => ({
        id: user.user_id,
        label: user.name,
        email: user.email,
        sublabel: user.email,
        group: user.role_name,
      })),
    [allInternalUsers]
  );

  useEffect(() => {
    if (localDraft) {
      pushToast("Restored your locally saved draft.", "info");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fetches the selected "From" client's known contacts whenever it
  // changes — mirrors TicketComposer.tsx's/MessageDetailsView.tsx's
  // own effect for their reply "To" pickers. Forward mode never shows
  // a client picker at all, so it's excluded; a cleared/unset clientId
  // just means no contact suggestions yet, not an error.
  useEffect(() => {
    if (isForward || !clientId) {
      setClientContacts([]);
      return;
    }
    let cancelled = false;
    listClientContacts(clientId)
      .then((contacts) => {
        if (!cancelled) setClientContacts(contacts);
      })
      .catch(() => {
        if (!cancelled) setClientContacts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isForward, clientId]);

  const canCompose = composableClients.length > 0;
  const isEmpty = isRichTextEmpty(bodyHtml);
  // Every comma-separated entry in "To" — a dropdown-picked contact
  // and a manually-typed external address are both just entries in
  // this same list, so neither kind is treated as more "valid" than
  // the other (this is also the fix for the reported bug: canSend
  // used to require the typed text to literally match a client, which
  // left an external address stuck disabled — it no longer looks at
  // clientId at all here, only at whether every entry is a valid
  // email).
  const toEntries = useMemo(() => parseEmails(toEmail), [toEmail]);
  const invalidToEntries = useMemo(
    () => toEntries.filter((entry) => !isValidEmailAddress(entry)),
    [toEntries]
  );
  // Cc/Bcc are optional everywhere (an empty value is never an error),
  // but a non-empty entry must still be a real address — validated
  // for both Compose and Forward (see canSend below). This used to be
  // Forward-only, which meant a malformed Cc/Bcc address silently sent
  // successfully from plain Compose — a real gap, not intentional
  // scoping (Reply's own Cc/Bcc, a separate hand-rolled implementation
  // in TicketComposer.tsx/MessageDetailsView.tsx, is unrelated and
  // untouched here).
  const ccEntries = useMemo(() => parseEmails(cc), [cc]);
  const bccEntries = useMemo(() => parseEmails(bcc), [bcc]);
  const invalidCcEntries = useMemo(
    () => ccEntries.filter((entry) => !isValidEmailAddress(entry)),
    [ccEntries]
  );
  const invalidBccEntries = useMemo(
    () => bccEntries.filter((entry) => !isValidEmailAddress(entry)),
    [bccEntries]
  );
  // Forward mode: original attachments already occupy part of the
  // 10-attachment total the backend enforces (original + new <= 10),
  // so newly-added attachments are capped to whatever's left rather
  // than the full 10 — see AttachmentUploader's maxFiles prop.
  const originalAttachmentCount = initialValues?.originalAttachmentCount ?? 0;
  const remainingAttachmentSlots = isForward
    ? Math.max(0, MAX_ATTACHMENT_FILES - originalAttachmentCount)
    : MAX_ATTACHMENT_FILES;

  const canSend = Boolean(
    clientId &&
      toEntries.length > 0 &&
      invalidToEntries.length === 0 &&
      subject.trim() &&
      !isEmpty &&
      invalidCcEntries.length === 0 &&
      invalidBccEntries.length === 0
  );

  // The "To" field is a single text input (never a separate field —
  // see the component's own comment on parseEmails/Cc/Bcc for the
  // established comma-separated-multiple-addresses convention this
  // reuses) with a suggestion dropdown layered on top: suggestions are
  // the selected "From" client's known contacts, filtered by whatever
  // is typed after the last comma, excluding contacts already present
  // in the field. Selecting one fills in just that in-progress segment
  // (see handleSelectContactSuggestion) rather than replacing the
  // whole field, so it composes naturally with already-entered
  // recipients. Text that never matches a suggestion is still a
  // perfectly valid recipient — it's simply an external address.
  const toLastSegment = useMemo(() => {
    const segments = toEmail.split(",");
    return segments[segments.length - 1].trim().toLowerCase();
  }, [toEmail]);

  const toSuggestions = useMemo(() => {
    if (!clientId) return [];
    const chosen = new Set(toEntries.map((entry) => entry.toLowerCase()));
    return clientContacts.filter((contact) => {
      if (chosen.has(contact.email.toLowerCase())) return false;
      if (!toLastSegment) return true;
      return (
        contact.email.toLowerCase().includes(toLastSegment) ||
        (contact.name ?? "").toLowerCase().includes(toLastSegment)
      );
    });
  }, [clientContacts, clientId, toEntries, toLastSegment]);

  const selectedClient = composableClients.find((c) => c.client_id === clientId);

  function handleFromChange(newClientId: string) {
    setClientId(newClientId);
    // Compose mode's recipient suggestions are specific to whichever
    // client this message is filed under — switching "From" clears
    // them rather than leaving a stale contact address associated
    // with the wrong client. Forward mode's recipient is an internal
    // user, unrelated to which client mailbox is sending, so it's
    // left untouched there.
    if (!isForward) setToEmail("");
  }

  function handleSelectContactSuggestion(contact: ClientContact) {
    const segments = toEmail.split(",");
    segments[segments.length - 1] = ` ${contact.email}`;
    setToEmail(
      segments
        .map((segment) => segment.trim())
        .filter(Boolean)
        .join(", ")
    );
    setShowToSuggestions(false);
  }

  function handleClearRecipient() {
    setToEmail("");
  }

  function handleSaveDraft() {
    const draft: LocalDraft = { clientId, toEmail, cc, bcc, subject, bodyHtml };
    window.localStorage.setItem(LOCAL_DRAFT_KEY, JSON.stringify(draft));
    pushToast("Draft saved on this device.", "success");
  }

  function handleDiscard() {
    clearLocalDraft();
    onDiscard();
  }

  async function handleSend() {
    if (!canSend) return;

    // A composer-agnostic gate: don't send while a pasted screenshot
    // is still uploading (or failed to upload) — see RichTextEditor's
    // onImageUpload wiring below (handleComposeImageUpload).
    if (hasPendingImageUploads) return;

    const richBodyHtml = isRichContent(bodyHtml) ? resolveInlineImageSources(bodyHtml) : undefined;

    if (isForward) {
      if (!onForwardSend || !initialValues?.interactionId || !toRecipient.email) return;
      const result = await onForwardSend({
        interactionId: initialValues.interactionId,
        clientId,
        recipientUserId: toRecipient.userId,
        recipientEmail: toRecipient.userId ? undefined : toRecipient.email,
        cc: ccEntries,
        bcc: bccEntries,
        subject: subject.trim(),
        message: htmlToPlainText(bodyHtml),
        files,
        bodyHtml: richBodyHtml,
        inlineImageInteractionIds: pastedImageInteractionIdsRef.current,
      });
      if (result) {
        clearLocalDraft();
      }
      return;
    }

    // onSend/POST /inbox/compose still take one primary `to_email`
    // (see ComposeEmailRequest on the backend, deliberately
    // unchanged) — "To" supporting several entries is a UI-level
    // convenience, so every recipient past the first rides along as
    // an additional Cc rather than requiring a backend/API change.
    const [primaryTo, ...extraTo] = toEntries;
    const result = await onSend({
      clientId,
      toEmail: primaryTo,
      subject: subject.trim(),
      message: htmlToPlainText(bodyHtml),
      bodyHtml: richBodyHtml,
      cc: Array.from(new Set([...extraTo, ...parseEmails(cc)])),
      bcc: parseEmails(bcc),
      files,
      inlineImageInteractionIds: pastedImageInteractionIdsRef.current,
    });
    if (result) {
      clearLocalDraft();
    }
  }

  return (
    <div
      className={cn(
        "flex flex-col overflow-hidden",
        variant !== "panel" && "rounded-xl border border-border bg-card shadow-card"
      )}
    >
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card px-5 py-4">
        <div className="flex flex-col gap-1.5">
          {isForward && onBack && (
            <button
              type="button"
              onClick={onBack}
              className="flex w-fit items-center gap-1.5 text-xs font-semibold text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back
            </button>
          )}
          <h2 className="text-[16px] font-semibold text-foreground">
            {isForward ? "Forward Message" : "New Message"}
          </h2>
        </div>
        <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground" onClick={handleDiscard}>
          <Trash2 className="h-3.5 w-3.5" />
          Discard
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {clientsLoading ? (
          <WorkflowLoader loading size={56} />
        ) : clientsError ? (
          <div className="rounded-lg border border-border bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
            Couldn't load clients. Try refreshing the page.
          </div>
        ) : !canCompose ? (
          <div className="rounded-lg border border-border bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
            {!currentUser
              ? "Loading..."
              : !canComposeExternally
                ? "You don't have permission to compose external mail. Ask an administrator to grant you the \"communication:reply_external\" permission."
                : "There are no clients available for you to compose mail to."}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">From</label>
              {/* The actual sending mailbox for BOTH Compose and
                  Forward — whichever client is picked here, the
                  outbound send goes out from that client's own
                  configured mailbox (falling back to the shared
                  mailbox for a client with none configured), enforced
                  server-side regardless of what's selected here (see
                  ensure_can_compose_for_client). Sourced from the same
                  composableClients scoping (Account Manager: own
                  clients only; else: unrestricted) already used
                  elsewhere in this component, never a hardcoded list.
                  In Compose mode, selecting one also populates the
                  "To" field's contact suggestions below; Forward mode
                  doesn't use client-contact suggestions since its "To"
                  is always an internal user. */}
              <Select value={clientId} onValueChange={handleFromChange}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a client" />
                </SelectTrigger>
                <SelectContent>
                  {composableClients.map((client) => (
                    <SelectItem key={client.client_id} value={client.client_id}>
                      {client.name}
                      {client.inbox_email ? ` · ${client.inbox_email}` : " · (no distribution email configured)"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">To</label>
              {isForward ? (
                <RecipientCombobox
                  options={internalRecipientOptions}
                  groupOrder={INTERNAL_RECIPIENT_ROLE_ORDER}
                  value={toRecipient.email}
                  onChange={({ email, matchedOption }) => {
                    setToRecipient(
                      matchedOption
                        ? { userId: matchedOption.id, email: matchedOption.email }
                        : { email }
                    );
                    // Keeps the pre-existing canSend/invalidToEntries
                    // validation (computed from toEmail) working
                    // unchanged for Forward too.
                    setToEmail(email);
                  }}
                  resetKey={initialValues?.interactionId ?? "compose"}
                  placeholder="Search internal users, or type any email…"
                  inputClassName="flex h-11 w-full rounded-lg border border-border bg-card px-4 py-2.5 pr-8 text-sm text-foreground transition-colors placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
                  emptyStateLabel="No matching internal users — the typed address will be used as an external recipient."
                  // The existing invalidToEntries block just below
                  // (shared with non-forward Compose's own "To" field)
                  // already renders this exact message from the same
                  // toEmail value — showing the combobox's own inline
                  // error too would duplicate it.
                  showInlineError={false}
                />
              ) : (
                <div className="relative">
                  <div className="relative">
                    <Input
                      type="text"
                      value={toEmail}
                      onChange={(e) => {
                        setToEmail(e.target.value);
                        setShowToSuggestions(true);
                      }}
                      onFocus={() => setShowToSuggestions(true)}
                      onBlur={() => window.setTimeout(() => setShowToSuggestions(false), 150)}
                      placeholder="Select a contact or enter an email…"
                      className="pr-8"
                      aria-invalid={invalidToEntries.length > 0}
                    />
                    {toEmail.length > 0 && (
                      <button
                        type="button"
                        onClick={handleClearRecipient}
                        aria-label="Clear recipients"
                        className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>

                  {showToSuggestions && (
                    <div className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-md border border-border bg-popover shadow-md">
                      {!clientId ? (
                        <p className="px-3 py-2.5 text-xs text-muted-foreground">
                          Select a client in the From field to see their known contacts, or type
                          an external address directly.
                        </p>
                      ) : toSuggestions.length === 0 ? (
                        <p className="px-3 py-2.5 text-xs text-muted-foreground">
                          No matching contact — the typed address will be used as-is.
                        </p>
                      ) : (
                        toSuggestions.map((contact) => (
                          <button
                            type="button"
                            key={contact.email}
                            // onMouseDown (not onClick) fires before the
                            // input's onBlur closes the dropdown.
                            onMouseDown={(e) => {
                              e.preventDefault();
                              handleSelectContactSuggestion(contact);
                            }}
                            className="flex w-full flex-col items-start px-3 py-1.5 text-left text-sm text-foreground transition-colors hover:bg-muted"
                          >
                            <span className="font-medium">{contact.name ?? contact.email}</span>
                            {contact.name && (
                              <span className="text-[11px] text-muted-foreground">
                                {contact.email}
                              </span>
                            )}
                          </button>
                        ))
                      )}
                    </div>
                  )}
                </div>
              )}
              {invalidToEntries.length > 0 && (
                <p className="mt-1 text-[11px] text-destructive">
                  {invalidToEntries.length === 1
                    ? `Enter a valid email address. "${invalidToEntries[0]}" isn't valid.`
                    : "Enter a valid email address for every entry, separated by commas."}
                </p>
              )}
              {isForward && (
                <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                  Search internal users by name or email, or type any valid email address to
                  forward to someone outside the organization.
                </p>
              )}
              {!isForward && (
                <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                  {selectedClient
                    ? `Filed under ${selectedClient.name} — pick one of their contacts above, or add any external address (separate multiple with commas).`
                    : "Select a client in the From field above, then pick a contact or type any external address (separate multiple with commas)."}
                </p>
              )}
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Cc</label>
                <Input
                  value={cc}
                  onChange={(e) => setCc(e.target.value)}
                  placeholder="cc@example.com, ..."
                  aria-invalid={invalidCcEntries.length > 0}
                />
                {invalidCcEntries.length > 0 && (
                  <p className="mt-1 text-[11px] text-destructive">
                    {invalidCcEntries.length === 1
                      ? `Enter a valid email address. "${invalidCcEntries[0]}" isn't valid.`
                      : "Enter a valid email address for every entry, separated by commas."}
                  </p>
                )}
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Bcc</label>
                <Input
                  value={bcc}
                  onChange={(e) => setBcc(e.target.value)}
                  placeholder="bcc@example.com, ..."
                  aria-invalid={invalidBccEntries.length > 0}
                />
                {invalidBccEntries.length > 0 && (
                  <p className="mt-1 text-[11px] text-destructive">
                    {invalidBccEntries.length === 1
                      ? `Enter a valid email address. "${invalidBccEntries[0]}" isn't valid.`
                      : "Enter a valid email address for every entry, separated by commas."}
                  </p>
                )}
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Subject</label>
              <Input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject" />
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Message</label>
              <RichTextEditor
                value={bodyHtml}
                onChange={setBodyHtml}
                placeholder="Write your message..."
                minHeight="12rem"
                onImageUpload={handleComposeImageUpload}
                onPendingImageUploadsChange={setHasPendingImageUploads}
              />
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Attachments</label>
              {isForward && originalAttachmentCount > 0 && (
                <p className="mb-1.5 text-[11px] leading-relaxed text-muted-foreground">
                  {originalAttachmentCount} original attachment
                  {originalAttachmentCount === 1 ? "" : "s"} will be forwarded automatically. You
                  can add up to {remainingAttachmentSlots} more ({MAX_ATTACHMENT_FILES} total).
                </p>
              )}
              <AttachmentUploader files={files} onFilesChange={setFiles} maxFiles={remainingAttachmentSlots} />
            </div>
          </div>
        )}
      </div>

      {canCompose && (
        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3.5">
          <Button variant="outline" onClick={handleSaveDraft} className="gap-1.5">
            <Save className="h-3.5 w-3.5" />
            Save Draft
          </Button>
          <Button
            onClick={handleSend}
            disabled={!canSend || isSending || hasPendingImageUploads}
            className="gap-1.5"
          >
            <Send className="h-3.5 w-3.5" />
            Send
          </Button>
        </div>
      )}
    </div>
  );
}
