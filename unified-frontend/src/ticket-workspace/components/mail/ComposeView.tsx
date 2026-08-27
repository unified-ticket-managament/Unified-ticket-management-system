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
import {
  createComposeDraft,
  discardComposeDraft as discardComposeDraftRequest,
  saveComposeDraft,
  uploadComposeInlineImage,
} from "@tw/api/inbox";
import { listClientContacts } from "@tw/api/clients";
import { MultiRecipientCombobox, type RecipientChip } from "@tw/components/common/MultiRecipientCombobox";
import type { RecipientOption } from "@tw/components/common/RecipientCombobox";
import { DistributionListMultiSelect } from "@tw/components/common/DistributionListMultiSelect";
import { useAuthContext } from "@tw/context/AuthContext";
import { useToast } from "@tw/context/ToastContext";
import {
  escapeHtml,
  filterLiveInlineImageIds,
  htmlToPlainText,
  isRichContent,
  resolveInlineImageSources,
  type TrackedInlineImage,
} from "@tw/lib/richText";
import { isValidEmailAddress } from "@tw/lib/validation";
import { MAX_ATTACHMENT_FILES, formatBytes, iconForFilename, previewHrefFor } from "@tw/lib/attachmentMeta";
import { generateIdempotencyKey } from "@tw/lib/idempotency";
import { mergedClientFilterOptions } from "@tw/lib/clientFilter";
import type {
  AttachmentMeta,
  CategoryResponse,
  ClientContact,
  ClientResponse,
  InternalNoteRecipientCandidate,
} from "@tw/types";

// Prefix marking a "From" Select value as a category mailbox rather
// than a client id — the two live in one combined option/value space
// (see composableSenders below) since the underlying Select can only
// carry a single string value.
const CATEGORY_FROM_PREFIX = "category:";

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
  categoryId?: string | null;
  toEmail?: string;
  // Every additional "To" recipient past the first — only ever set
  // when reopening a saved Compose draft that had more than one.
  toEmails?: string[];
  cc?: string[];
  bcc?: string[];
  subject?: string;
  bodyHtml?: string;
  // Plain-text fallback for restoring a saved Compose draft whose
  // message was never given rich HTML (body_html null) — same
  // escape-and-wrap treatment ReplyComposer.tsx uses for its own
  // initialMessage. Ignored whenever bodyHtml above is present.
  message?: string;
  // Set only when reopening a previously-saved Compose draft (see
  // InboxPage.tsx's handleOpen) — lets this session update that same
  // draft row on every subsequent save instead of creating a new one.
  draftInteractionId?: string;
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
  // The original message's own attachment metadata (forward mode
  // only) — rendered as an openable list so the user can verify what's
  // being forwarded before sending; these are already stored server-
  // side (real download_url), never re-uploaded.
  originalAttachments?: AttachmentMeta[];
}

interface ComposeViewProps {
  clients: ClientResponse[];
  // Categories with a configured inbox_email are offered as
  // additional "From" mailbox options, alongside active clients — see
  // composableSenders below (reuses lib/clientFilter.ts's existing
  // mergedClientFilterOptions, the same active-clients+inbox-mail-
  // categories merge already used by Mail's own Clients filter).
  categories: CategoryResponse[];
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
    clientId?: string;
    categoryId?: string;
    toEmail?: string;
    // Every additional "To" entry past the first — real recipients,
    // never Cc (see handleSend's non-forward branch).
    toEmails?: string[];
    subject: string;
    message: string;
    bodyHtml?: string;
    cc: string[];
    bcc: string[];
    files: File[];
    inlineImageInteractionIds?: string[];
    distributionListIds?: string[];
    idempotencyKey?: string;
  }) => Promise<unknown>;
  // Forward mode's own Send path — distinct from onSend since
  // forwarding can address a mix of internal organization users (by
  // user_id, resolved server-side to their real email), arbitrary
  // external addresses, and Distribution Lists (resolved server-side
  // to their current active members), and creates a different kind
  // of communication (see InteractionService.forward_to_internal_user).
  // At least one of the three must be non-empty. Only required when
  // initialValues.mode === "forward".
  onForwardSend?: (payload: {
    interactionId: string;
    clientId?: string;
    categoryId?: string;
    recipientUserIds?: string[];
    recipientEmails?: string[];
    distributionListIds?: string[];
    cc?: string[];
    bcc?: string[];
    subject: string;
    message: string;
    files: File[];
    bodyHtml?: string;
    inlineImageInteractionIds?: string[];
    idempotencyKey?: string;
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
  categories,
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

  // "From" option set — active clients (composableClients, already
  // role-scoped above) plus categories with a configured inbox_email,
  // deduped by name collision — reuses lib/clientFilter.ts's existing
  // mergedClientFilterOptions as-is (already used by Mail's own
  // Clients filter dropdown for this exact rule set) rather than
  // re-deriving the same active/inbox-email filtering here. Category
  // options are intentionally NOT further scoped per-role the way
  // composableClients is for Account Manager — the backend's own
  // ensure_can_compose_for_category is the real gate; an Account
  // Manager who isn't that category's Reporting Manager sees the
  // option but gets a clean rejection on Send, same "frontend
  // filtering is a convenience, never the real gate" convention this
  // component already follows for client ownership.
  const { activeClients, categoryOptions } = useMemo(
    () => mergedClientFilterOptions(composableClients, categories),
    [composableClients, categories]
  );

  // "From" — which client this message is filed under (still a
  // required field on POST /inbox/compose regardless of who the
  // actual recipient turns out to be). Picking one here is what
  // drives the "To" field's contact suggestions below; it no longer
  // doubles as the recipient itself, which is also what fixes the
  // "external address left Send disabled" bug — canSend (below) no
  // longer requires the "To" text to match a client at all.
  const [clientId, setClientId] = useState(initialValues?.clientId ?? "");
  // "From" — category-mailbox counterpart to clientId, mutually
  // exclusive with it. See handleFromChange for how the single
  // Select's value space encodes which of the two is selected.
  const [categoryId, setCategoryId] = useState(initialValues?.categoryId ?? "");
  // "To" — the actual recipient(s). A plain comma-separated address
  // list, same convention as Cc/Bcc (parseEmails below) rather than a
  // chip UI, so entering more than one is just typing/selecting more
  // than once. Independent of clientId: a manually-typed external
  // address is exactly as valid a recipient as a dropdown-picked
  // contact, which is what makes canSend correct for both cases.
  const [toEmail, setToEmail] = useState(
    () =>
      [initialValues?.toEmail, ...(initialValues?.toEmails ?? [])]
        .filter((entry): entry is string => Boolean(entry))
        .join(", ")
  );
  // Combobox UI state for the (non-forward) "To" field below — the
  // input's value IS toEmail itself (no separate query string).
  const [showToSuggestions, setShowToSuggestions] = useState(false);
  // Known contact addresses for the selected "From" client — backs
  // the "To" suggestion dropdown, same listClientContacts endpoint
  // TicketComposer.tsx/MessageDetailsView.tsx already use for their
  // own reply "To" pickers.
  const [clientContacts, setClientContacts] = useState<ClientContact[]>([]);
  const [cc, setCc] = useState(() => (initialValues?.cc ?? []).join(", "));
  const [bcc, setBcc] = useState(() => (initialValues?.bcc ?? []).join(", "));
  // Distribution Lists to include as recipients — a genuine
  // additional "To" recipient in both modes (Forward and Compose
  // alike have no fixed thread), resolved server-side to current
  // active members. Always its own, additional field — never folded
  // into the "To" input's own suggestion list, since a list expands
  // to N members at send time, not one value.
  const [distributionListIds, setDistributionListIds] = useState<string[]>([]);
  const [subject, setSubject] = useState(initialValues?.subject ?? "");
  const [bodyHtml, setBodyHtml] = useState(() => {
    if (initialValues?.bodyHtml) return initialValues.bodyHtml;
    if (initialValues?.message) {
      return `<p>${escapeHtml(initialValues.message).replace(/\n/g, "<br/>")}</p>`;
    }
    return "";
  });
  const [files, setFiles] = useState<File[]>([]);
  const [hasPendingImageUploads, setHasPendingImageUploads] = useState(false);
  // The server-side Compose draft backing this session, once one
  // exists — set on the very first autosave/manual Save Draft (see
  // persistDraft below), or immediately if reopening a previously-
  // saved draft. A plain ref (not state): persistDraft reads/writes it
  // synchronously across overlapping debounced calls, and nothing here
  // needs a re-render when it changes. Never used in Forward mode —
  // Forward has no draft concept in this pass.
  const draftInteractionIdRef = useRef<string | null>(initialValues?.draftInteractionId ?? null);
  const [draftStatus, setDraftStatus] = useState<"idle" | "saving" | "saved">("idle");
  const skipNextAutoSaveRef = useRef(true);
  const savedIndicatorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Interaction ids of any screenshot pasted/dropped into the editor,
  // staged via uploadComposeInlineImage (see RichTextEditor's
  // onImageUpload below) and reassigned onto the real outbound
  // message at Send time — same pattern TicketComposer.tsx already
  // uses via pastedImageInteractionIdsRef for Reply/Note. Tracked as
  // {interactionId, contentId} pairs so a deleted/replaced image can
  // be filtered back out at Send time via filterLiveInlineImageIds.
  const pastedImageInteractionIdsRef = useRef<TrackedInlineImage[]>([]);
  // One Send idempotency key per mounted composer instance, not one
  // per click — a double-click (or a manual retry after a failed
  // send) must reuse the same key so the backend's own dedup (a
  // unique index on the key) can actually collapse them. useRef's
  // initial-value argument only takes effect on the first render, so
  // this is still just one generated key per composer instance.
  const idempotencyKeyRef = useRef<string>(generateIdempotencyKey());

  async function handleComposeImageUpload(file: File) {
    const res = await uploadComposeInlineImage(file);
    pastedImageInteractionIdsRef.current.push({
      interactionId: res.interaction_id,
      contentId: res.content_id,
    });
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
  // Forward's "To" — multiple recipients (internal users and/or
  // external addresses), each a chip. Which of the two a chip is
  // gets resolved at send time (see handleSend's forward branch) by
  // matching its email against internalRecipientOptions, rather than
  // stored per-chip — RecipientChip carries only email/label.
  const [toChips, setToChips] = useState<RecipientChip[]>([]);

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

  // Upserts this session's Compose draft — creates it on the very
  // first call (once), updates it in place on every subsequent one.
  // Mirrors ReplyComposer.tsx's persistDraft/onSaveDraft pattern for
  // pre-ticket Reply drafts; Compose needed its own sibling rather
  // than reusing that one, since a brand-new outbound message has no
  // existing thread root to attach a child draft to (see the backend
  // service methods' own docstrings). Never called in Forward mode.
  async function persistDraft() {
    setDraftStatus("saving");
    const request = {
      client_id: clientId || null,
      category_id: categoryId || null,
      to_email: toEntries[0],
      to_emails: toEntries.slice(1),
      cc: parseEmails(cc),
      bcc: parseEmails(bcc),
      subject,
      message: htmlToPlainText(bodyHtml),
      body_html: isRichContent(bodyHtml) ? resolveInlineImageSources(bodyHtml) : undefined,
    };
    try {
      const result = draftInteractionIdRef.current
        ? await saveComposeDraft(draftInteractionIdRef.current, request)
        : await createComposeDraft(request);
      draftInteractionIdRef.current = result.interaction_id;
      setDraftStatus("saved");
      if (savedIndicatorTimerRef.current) clearTimeout(savedIndicatorTimerRef.current);
      savedIndicatorTimerRef.current = setTimeout(() => setDraftStatus("idle"), 2500);
      return result;
    } catch {
      setDraftStatus("idle");
      return null;
    }
  }

  // Continuous auto-save — debounced, never in Forward mode (Forward
  // has no draft concept in this pass). Skips the very first render
  // so opening the composer (possibly already prefilled from a
  // reopened draft) doesn't immediately re-save what it was just
  // given. An entirely empty, untouched draft is never saved either —
  // there's nothing worth persisting until something's actually typed.
  useEffect(() => {
    if (isForward) return;
    if (skipNextAutoSaveRef.current) {
      skipNextAutoSaveRef.current = false;
      return;
    }
    if (
      !clientId &&
      !categoryId &&
      !toEmail.trim() &&
      !cc.trim() &&
      !bcc.trim() &&
      !subject.trim() &&
      isRichTextEmpty(bodyHtml)
    ) {
      return;
    }

    const timer = setTimeout(() => {
      persistDraft();
    }, 1200);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, categoryId, toEmail, cc, bcc, subject, bodyHtml, isForward]);

  useEffect(() => {
    return () => {
      if (savedIndicatorTimerRef.current) clearTimeout(savedIndicatorTimerRef.current);
    };
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

  const canCompose = activeClients.length > 0 || categoryOptions.length > 0;
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
  const originalAttachments = initialValues?.originalAttachments ?? [];
  const remainingAttachmentSlots = isForward
    ? Math.max(0, MAX_ATTACHMENT_FILES - originalAttachmentCount)
    : MAX_ATTACHMENT_FILES;

  // Forward's "To" is a chip list (MultiRecipientCombobox) — every
  // chip it produces is already individually validated at add-time
  // (or matched against a known internal user), so there's no
  // separate "invalid entries" condition to check for it the way
  // plain Compose's comma-separated toEmail field still needs.
  const hasRecipientSource = isForward
    ? toChips.length > 0 || distributionListIds.length > 0
    : toEntries.length > 0 || distributionListIds.length > 0;
  const hasInvalidTo = isForward ? false : invalidToEntries.length > 0;

  const canSend = Boolean(
    (clientId || categoryId) &&
      hasRecipientSource &&
      !hasInvalidTo &&
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

  // "From" Select's combined value space: a bare id is a client,
  // CATEGORY_FROM_PREFIX + id is a category — see the constant's own
  // comment above for why one Select needs to carry both kinds.
  const fromValue = clientId || (categoryId ? `${CATEGORY_FROM_PREFIX}${categoryId}` : "");

  function handleFromChange(newValue: string) {
    if (newValue.startsWith(CATEGORY_FROM_PREFIX)) {
      setCategoryId(newValue.slice(CATEGORY_FROM_PREFIX.length));
      setClientId("");
    } else {
      setClientId(newValue);
      setCategoryId("");
    }
    // Compose mode's recipient suggestions are specific to whichever
    // client this message is filed under — switching "From" clears
    // them rather than leaving a stale contact address associated
    // with the wrong client (a category has no contacts of its own,
    // so selecting one also clears toEmail via this same path — the
    // existing !clientId guard on the contacts-fetch effect below
    // already no-ops correctly once clientId is empty). Forward
    // mode's recipient is an internal user, unrelated to which
    // mailbox is sending, so it's left untouched there.
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

  async function handleSaveDraft() {
    const result = await persistDraft();
    pushToast(result ? "Draft saved." : "Couldn't save draft. Try again.", result ? "success" : "error");
  }

  async function handleDiscard() {
    if (draftInteractionIdRef.current) {
      await discardComposeDraftRequest(draftInteractionIdRef.current);
      draftInteractionIdRef.current = null;
    }
    onDiscard();
  }

  async function handleSend() {
    if (!canSend) return;

    // A composer-agnostic gate: don't send while a pasted screenshot
    // is still uploading (or failed to upload) — see RichTextEditor's
    // onImageUpload wiring below (handleComposeImageUpload).
    if (hasPendingImageUploads) return;

    const richBodyHtml = isRichContent(bodyHtml) ? resolveInlineImageSources(bodyHtml) : undefined;
    // Only submit ids for images still actually present (as a real
    // cid: reference) in the body being sent — a paste-then-delete/
    // replace/undo before Send must not resurrect a stale attachment.
    // See lib/richText.ts's filterLiveInlineImageIds for why this is
    // needed on top of resolveInlineImageSources alone.
    const liveInlineImageInteractionIds = filterLiveInlineImageIds(
      richBodyHtml ?? "",
      pastedImageInteractionIdsRef.current
    );

    if (isForward) {
      if (!onForwardSend || !initialValues?.interactionId) return;
      if (toChips.length === 0 && distributionListIds.length === 0) return;
      // Each chip is either a known internal user (by email match
      // against internalRecipientOptions) or a genuinely external
      // address — resolved here, at send time, rather than stored per
      // chip, since RecipientChip itself only carries email/label.
      const recipientUserIds: string[] = [];
      const recipientEmails: string[] = [];
      for (const chip of toChips) {
        const matched = internalRecipientOptions.find(
          (option) => option.email.toLowerCase() === chip.email.toLowerCase()
        );
        if (matched) {
          recipientUserIds.push(matched.id);
        } else {
          recipientEmails.push(chip.email);
        }
      }
      const result = await onForwardSend({
        interactionId: initialValues.interactionId,
        clientId: clientId || undefined,
        categoryId: categoryId || undefined,
        recipientUserIds,
        recipientEmails,
        distributionListIds,
        cc: ccEntries,
        bcc: bccEntries,
        subject: subject.trim(),
        message: htmlToPlainText(bodyHtml),
        files,
        bodyHtml: richBodyHtml,
        inlineImageInteractionIds: liveInlineImageInteractionIds,
        idempotencyKey: idempotencyKeyRef.current,
      });
      if (result) {
        pastedImageInteractionIdsRef.current = [];
      }
      return;
    }

    // POST /inbox/compose now accepts to_emails (plural) alongside
    // to_email — every "To" entry is sent as a real recipient, never
    // downgraded into Cc (a real, reported bug: the outbound Graph
    // message and the persisted Sent record both ended up with the
    // wrong To/Cc split when more than one address was typed).
    const [primaryTo, ...extraTo] = toEntries;
    const result = await onSend({
      clientId: clientId || undefined,
      categoryId: categoryId || undefined,
      toEmail: primaryTo,
      toEmails: extraTo,
      subject: subject.trim(),
      message: htmlToPlainText(bodyHtml),
      bodyHtml: richBodyHtml,
      cc: parseEmails(cc),
      bcc: parseEmails(bcc),
      files,
      inlineImageInteractionIds: liveInlineImageInteractionIds,
      distributionListIds,
      idempotencyKey: idempotencyKeyRef.current,
    });
    if (result) {
      pastedImageInteractionIdsRef.current = [];
      // The message just sent through the normal compose_email path
      // above (unchanged, already-tested) — any server-side draft
      // this session had been autosaving is now obsolete; clean it up
      // so it doesn't linger in the Drafts list.
      if (draftInteractionIdRef.current) {
        await discardComposeDraftRequest(draftInteractionIdRef.current);
        draftInteractionIdRef.current = null;
      }
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
                : "There are no clients or category mailboxes available for you to compose mail from."}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">From</label>
              {/* The actual sending mailbox for BOTH Compose and
                  Forward — whichever option is picked here, the
                  outbound send goes out from that client's own
                  configured mailbox (falling back to the shared
                  mailbox for a client with none configured) or, for a
                  category option, that category's own inbox_email —
                  enforced server-side regardless of what's selected
                  here (see ensure_can_compose_for_client/
                  ensure_can_compose_for_category). Options are active
                  clients (role-scoped: Account Manager sees only
                  their own; else unrestricted) plus categories with a
                  configured inbox_email, deduped by name — see
                  mergedClientFilterOptions (lib/clientFilter.ts),
                  reused as-is. In Compose mode, selecting a client
                  also populates the "To" field's contact suggestions
                  below (a category has none of its own); Forward mode
                  doesn't use client-contact suggestions since its "To"
                  is always an internal user. */}
              <Select value={fromValue} onValueChange={handleFromChange}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a client or category mailbox" />
                </SelectTrigger>
                <SelectContent>
                  {activeClients.map((client) => (
                    <SelectItem key={client.client_id} value={client.client_id}>
                      {client.name}
                      {client.inbox_email ? ` · ${client.inbox_email}` : " · (no distribution email configured)"}
                    </SelectItem>
                  ))}
                  {categoryOptions.map((category) => (
                    <SelectItem
                      key={category.category_id}
                      value={`${CATEGORY_FROM_PREFIX}${category.category_id}`}
                    >
                      {category.category_name} · {category.inbox_email}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">To</label>
              {isForward ? (
                <MultiRecipientCombobox
                  options={internalRecipientOptions}
                  groupOrder={INTERNAL_RECIPIENT_ROLE_ORDER}
                  value={toChips}
                  onChange={setToChips}
                  resetKey={initialValues?.interactionId ?? "compose"}
                  placeholder="Search internal users, or type any email…"
                  emptyStateLabel="No matching internal users — type a full email address and press Enter to add it as an external recipient."
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
              {!isForward && invalidToEntries.length > 0 && (
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

            <div>
              <DistributionListMultiSelect
                label="Distribution Groups"
                hint="Each active member is added as a real additional To recipient."
                selectedIds={distributionListIds}
                onChange={setDistributionListIds}
              />
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
                <div className="mb-2">
                  <p className="mb-1.5 text-[11px] leading-relaxed text-muted-foreground">
                    {originalAttachmentCount} original attachment
                    {originalAttachmentCount === 1 ? "" : "s"} will be forwarded automatically. You
                    can add up to {remainingAttachmentSlots} more ({MAX_ATTACHMENT_FILES} total).
                    You cannot remove them here.
                  </p>
                  <ul className="flex flex-col gap-1.5">
                    {originalAttachments.map((attachment) => {
                      const Icon = iconForFilename(attachment.filename);
                      return (
                        <li
                          key={attachment.id}
                          className="flex items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-1.5"
                        >
                          <Icon className="h-3.5 w-3.5 flex-none text-muted-foreground" />
                          <a
                            href={previewHrefFor(attachment)}
                            target="_blank"
                            rel="noopener noreferrer"
                            title="Open to preview"
                            className="min-w-0 flex-1 truncate text-xs font-medium text-foreground hover:underline"
                          >
                            {attachment.filename}
                          </a>
                          <span className="flex-none text-[11px] text-muted-foreground">
                            {formatBytes(attachment.size)}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
              <AttachmentUploader files={files} onFilesChange={setFiles} maxFiles={remainingAttachmentSlots} />
            </div>
          </div>
        )}
      </div>

      {canCompose && (
        <div className="flex items-center justify-between gap-2 border-t border-border px-5 py-3.5">
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            {!isForward && draftStatus === "saving" && "Saving draft…"}
            {!isForward && draftStatus === "saved" && "Draft saved"}
          </div>
          <div className="flex items-center gap-2">
            {!isForward && (
              <Button
                variant="outline"
                onClick={handleSaveDraft}
                disabled={draftStatus === "saving"}
                className="gap-1.5"
              >
                <Save className="h-3.5 w-3.5" />
                Save Draft
              </Button>
            )}
            <Button
              onClick={handleSend}
              disabled={!canSend || isSending || hasPendingImageUploads}
              className="gap-1.5"
            >
              <Send className="h-3.5 w-3.5" />
              Send
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
