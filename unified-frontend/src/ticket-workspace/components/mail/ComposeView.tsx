"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Save, Send, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AttachmentUploader } from "@tw/components/mail/AttachmentUploader";
import { RichTextEditor, isRichTextEmpty } from "@tw/components/mail/RichTextEditor";
import { listRbacRoles, listRbacUsers, type RbacUserSummary } from "@tw/api/rbacUsers";
import { useAuthContext } from "@tw/context/AuthContext";
import { useToast } from "@tw/context/ToastContext";
import { htmlToPlainText } from "@tw/lib/richText";
import type { ClientResponse } from "@tw/types";

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
  initialValues?: ComposeInitialValues;
  isSending: boolean;
  onSend: (payload: {
    clientId: string;
    toEmail: string;
    subject: string;
    message: string;
    cc: string[];
    bcc: string[];
    files: File[];
  }) => Promise<unknown>;
  onDiscard: () => void;
  // Only rendered (as a "← Back" control) when this view is in
  // Forward mode — Discard already covers "abandon and return to the
  // inbox" for a brand-new Compose; Back specifically returns to the
  // exact message that was being forwarded, preserving the mailbox/
  // selection/scroll state the task's Back-button requirement asks
  // for, with no new routing (see InboxPage.tsx's handleComposeBack).
  onBack?: () => void;
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
export function ComposeView({ clients, initialValues, isSending, onSend, onDiscard, onBack }: ComposeViewProps) {
  const { currentUser } = useAuthContext();
  const { pushToast } = useToast();
  const isForward = initialValues?.mode === "forward";

  const composableClients = useMemo(() => {
    if (!currentUser) return [];
    if (currentUser.role === "Site Lead" || currentUser.role === "Super Admin") return clients;
    if (currentUser.role === "Account Manager") {
      return clients.filter((c) => c.account_manager_id === currentUser.user_id);
    }
    return [];
  }, [clients, currentUser]);

  const localDraft = useMemo(() => (initialValues ? null : readLocalDraft()), [initialValues]);

  const [clientId, setClientId] = useState(initialValues?.clientId ?? localDraft?.clientId ?? "");
  const [toEmail, setToEmail] = useState(initialValues?.toEmail ?? localDraft?.toEmail ?? "");
  const [cc, setCc] = useState(localDraft?.cc ?? "");
  const [bcc, setBcc] = useState(localDraft?.bcc ?? "");
  const [subject, setSubject] = useState(initialValues?.subject ?? localDraft?.subject ?? "");
  const [bodyHtml, setBodyHtml] = useState(initialValues?.bodyHtml ?? localDraft?.bodyHtml ?? "");
  const [files, setFiles] = useState<File[]>([]);

  // Forward's "To" data source — every active internal user, grouped
  // by role. Fetched only in Forward mode (Compose's own client
  // picker needs none of this). Grouped once, right at fetch time, so
  // rendering never has to re-derive a user's role name.
  const [internalRecipientGroups, setInternalRecipientGroups] = useState<
    Record<string, RbacUserSummary[]>
  >({});
  const [allInternalUsers, setAllInternalUsers] = useState<RbacUserSummary[]>([]);
  const [toUserId, setToUserId] = useState("");

  useEffect(() => {
    if (!isForward) return;
    let cancelled = false;
    Promise.all([listRbacUsers(), listRbacRoles()])
      .then(([users, roles]) => {
        if (cancelled) return;
        const roleNameById = new Map(roles.map((r) => [r.role_id, r.name]));
        const eligible = users.filter(
          (u) =>
            u.is_active &&
            u.user_id !== currentUser?.user_id &&
            INTERNAL_RECIPIENT_ROLE_ORDER.includes(roleNameById.get(u.role_id) ?? "")
        );
        const groups: Record<string, RbacUserSummary[]> = {};
        for (const roleName of INTERNAL_RECIPIENT_ROLE_ORDER) groups[roleName] = [];
        for (const user of eligible) {
          const roleName = roleNameById.get(user.role_id);
          if (roleName) groups[roleName].push(user);
        }
        setAllInternalUsers(eligible);
        setInternalRecipientGroups(groups);
      })
      .catch(() => {
        if (!cancelled) {
          setAllInternalUsers([]);
          setInternalRecipientGroups({});
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isForward]);

  function handleInternalRecipientChange(userId: string) {
    setToUserId(userId);
    const user = allInternalUsers.find((u) => u.user_id === userId);
    setToEmail(user?.email ?? "");
  }

  useEffect(() => {
    if (localDraft) {
      pushToast("Restored your locally saved draft.", "info");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Covers a restored local draft whose client list wasn't loaded yet
  // at mount — resolves the recipient from the preset client once the
  // client list is available. The "To" dropdown is the only recipient
  // input now (no separate free-text field to preserve), so this
  // always wins once clientId is set. Forward mode is deliberately
  // excluded — its "To" is an internal user, never derived from the
  // client, and clientId there is only carried along to satisfy
  // POST /inbox/compose's required field (see handleSend below), not
  // to drive the recipient.
  useEffect(() => {
    if (isForward || !clientId || toEmail.trim()) return;
    const client = composableClients.find((c) => c.client_id === clientId);
    if (client?.inbox_email) setToEmail(client.inbox_email);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composableClients, isForward]);

  const canCompose = composableClients.length > 0;
  const isEmpty = isRichTextEmpty(bodyHtml);
  const canSend = Boolean(clientId && toEmail.trim() && subject.trim() && !isEmpty);

  // Every real client now sends/receives through the one shared
  // ticketing@probeps.com mailbox — there's no more per-client "From"
  // identity to pick (see root CLAUDE.md's client-matching rework).
  // The "To" dropdown is the single source of recipient selection —
  // picking a client resolves the actual recipient address internally
  // from that client's own real address (Client.inbox_email); there's
  // no separate recipient-email input to keep in sync.
  function handleClientChange(nextClientId: string) {
    setClientId(nextClientId);
    const client = composableClients.find((c) => c.client_id === nextClientId);
    setToEmail(client?.inbox_email ?? "");
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
    const result = await onSend({
      clientId,
      toEmail: toEmail.trim(),
      subject: subject.trim(),
      message: htmlToPlainText(bodyHtml),
      cc: parseEmails(cc),
      bcc: parseEmails(bcc),
      files,
    });
    if (result) {
      clearLocalDraft();
    }
  }

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-border bg-card shadow-card">
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
        {!canCompose ? (
          <div className="rounded-lg border border-border bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
            {currentUser
              ? "Composing new mail is only available to Account Managers (for their own clients) and Site Lead/Super Admin."
              : "Loading..."}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">From</label>
              <div className="flex h-9 items-center rounded-md border border-border bg-muted/30 px-3 text-sm text-muted-foreground">
                Ticketing Support &lt;ticketing@probeps.com&gt;
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">To</label>
              {isForward ? (
                <Select value={toUserId} onValueChange={handleInternalRecipientChange}>
                  <SelectTrigger>
                    <SelectValue placeholder="Choose an internal recipient" />
                  </SelectTrigger>
                  <SelectContent>
                    {INTERNAL_RECIPIENT_ROLE_ORDER.filter(
                      (roleName) => (internalRecipientGroups[roleName]?.length ?? 0) > 0
                    ).map((roleName) => (
                      <SelectGroup key={roleName}>
                        <SelectLabel>{roleName}</SelectLabel>
                        {internalRecipientGroups[roleName].map((user) => (
                          <SelectItem key={user.user_id} value={user.user_id}>
                            {user.name} · {user.email}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Select value={clientId} onValueChange={handleClientChange}>
                  <SelectTrigger>
                    <SelectValue placeholder="Choose a client to email" />
                  </SelectTrigger>
                  <SelectContent>
                    {composableClients.map((client) => (
                      <SelectItem key={client.client_id} value={client.client_id}>
                        {client.name} · {client.inbox_email}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              {isForward && (
                <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                  Forwarding is limited to internal organization users — no external addresses.
                </p>
              )}
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Cc</label>
                <Input value={cc} onChange={(e) => setCc(e.target.value)} placeholder="cc@example.com, ..." />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Bcc</label>
                <Input value={bcc} onChange={(e) => setBcc(e.target.value)} placeholder="bcc@example.com, ..." />
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Subject</label>
              <Input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject" />
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Message</label>
              <RichTextEditor value={bodyHtml} onChange={setBodyHtml} placeholder="Write your message..." minHeight="12rem" />
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Attachments</label>
              <AttachmentUploader files={files} onFilesChange={setFiles} />
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
          <Button onClick={handleSend} disabled={!canSend || isSending} className="gap-1.5">
            <Send className="h-3.5 w-3.5" />
            Send
          </Button>
        </div>
      )}
    </div>
  );
}
