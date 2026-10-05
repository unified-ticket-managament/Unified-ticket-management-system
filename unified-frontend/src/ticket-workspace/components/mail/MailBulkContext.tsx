"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { bulkMailAction, type BulkMailActionPayload } from "@tw/api/inbox";
import {
  BulkCreateTicketDialog,
  BulkLinkTicketDialog,
  type BulkCreateTicketChoice,
} from "@tw/components/mail/BulkTicketDialogs";
import { useAuthContext } from "@tw/context/AuthContext";
import { useToast } from "@tw/context/ToastContext";
import {
  advanceQueue,
  createComposeQueue,
  currentQueueId,
  queueActionLabel,
  queueProgressLabel,
  type BulkComposeAction,
  type BulkComposeQueue,
} from "@tw/lib/bulkComposeQueue";
import { summarizeBulkResult } from "@tw/lib/bulkResult";
import {
  EMPTY_SELECTION,
  clearSelection,
  detectPlatform,
  pruneSelection,
  selectAllVisible,
  toggleSelected,
  type MailPlatform,
  type SelectedIds,
} from "@tw/lib/mailSelection";
import {
  partitionForBulkAction,
  type BulkActionKey,
  type BulkActionPermissions,
  type MessageActionKey,
  type MessageActionRow,
} from "@tw/lib/messageActions";

// Everything multi-select + bulk lives behind this one provider so the
// four MessageList call sites in InboxPage stay unchanged: rows read
// the selection from context, and the toolbar / right-click menu call
// `runBulk`. The provider owns no business rules — it partitions the
// selection by what the UI may offer, makes ONE request to
// POST /inbox/bulk-action (or, for Reply / Reply All / Forward, walks
// the selection one message at a time through the existing composer),
// and the backend authorizes every interaction again on its own.

export interface MailBulkContextValue {
  selectedIds: SelectedIds;
  platform: MailPlatform;
  perms: BulkActionPermissions;
  // The Trash view: menus offer only Restore.
  isTrash: boolean;
  busy: boolean;
  toggle: (id: string) => void;
  selectAll: (ids: readonly string[]) => void;
  setSelection: (ids: SelectedIds) => void;
  clear: () => void;
  prune: (loadedIds: readonly string[]) => void;
  // Personal Flag / Pin on ONE message (same POST /inbox/bulk-action as the
  // toolbar, with a single id). Quiet on success; the list refetches so a
  // pin re-sorts server-side.
  markMessage: (
    interactionId: string,
    action: "flag" | "unflag" | "pin" | "unpin"
  ) => Promise<void>;
  runBulk: (
    action: BulkActionKey,
    rows: readonly MessageActionRow[],
    options?: { folderId?: string | null }
  ) => void;
}

const MailBulkContext = createContext<MailBulkContextValue | null>(null);

// Null outside the provider so MessageList stays usable anywhere it is
// rendered without bulk support.
export function useMailBulk(): MailBulkContextValue | null {
  return useContext(MailBulkContext);
}

type PendingDialog =
  | { kind: "createTicket" | "linkTicket" | "delete"; eligibleIds: string[]; skippedIds: string[] }
  | null;

interface MailBulkProviderProps {
  children: ReactNode;
  // Changes whenever the visible list is swapped out (view / folder),
  // which must drop the selection.
  resetKey: string;
  isTrash?: boolean;
  onMessageAction: (interactionId: string, action: MessageActionKey) => void | Promise<void>;
  refreshAfterMutation: () => Promise<void>;
}

const BULK_ACTION_TO_API: Partial<Record<BulkActionKey, BulkMailActionPayload["action"]>> = {
  markRead: "mark_read",
  markUnread: "mark_unread",
  flag: "flag",
  unflag: "unflag",
  pin: "pin",
  unpin: "unpin",
  archive: "archive",
  move: "move",
  delete: "delete",
  restore: "restore",
  createTicket: "create_ticket",
  linkTicket: "link_ticket",
};

export function MailBulkProvider({
  children,
  resetKey,
  isTrash = false,
  onMessageAction,
  refreshAfterMutation,
}: MailBulkProviderProps) {
  const { currentUser } = useAuthContext();
  const { pushToast } = useToast();
  const [selectedIds, setSelectedIds] = useState<SelectedIds>(EMPTY_SELECTION);
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<PendingDialog>(null);
  const [queue, setQueue] = useState<BulkComposeQueue | null>(null);
  const platform = useMemo(() => detectPlatform(), []);

  const permissionList = currentUser?.permissions;
  const perms = useMemo<BulkActionPermissions>(() => {
    const has = (permission: string) => !!permissionList?.includes(permission);
    return {
      replyExternal: has("communication:reply_external"),
      createTicket: has("ticket:create"),
      attachToTicket: has("communication:attach_to_ticket"),
      archive: has("communication:archive"),
      moveToFolder: has("communication:move_to_folder"),
      hideInteraction: has("ticket:hide_interaction"),
    };
  }, [permissionList]);

  const toggle = useCallback(
    (id: string) => setSelectedIds((prev) => toggleSelected(prev, id)),
    []
  );
  const selectAll = useCallback(
    (ids: readonly string[]) => setSelectedIds(selectAllVisible(ids)),
    []
  );
  const clear = useCallback(() => setSelectedIds(clearSelection()), []);
  const prune = useCallback(
    (loadedIds: readonly string[]) => setSelectedIds((prev) => pruneSelection(prev, loadedIds)),
    []
  );

  // View or folder switched → the old rows are gone; so is the selection
  // (and any half-finished reply queue that belonged to them).
  const firstResetRef = useRef(true);
  useEffect(() => {
    if (firstResetRef.current) {
      firstResetRef.current = false;
      return;
    }
    setSelectedIds(clearSelection());
    setQueue(null);
    setDialog(null);
  }, [resetKey]);

  const execute = useCallback(
    async (payload: BulkMailActionPayload, skippedIds: readonly string[]) => {
      setBusy(true);
      try {
        const result = await bulkMailAction(payload);
        const summary = summarizeBulkResult(result, skippedIds);
        pushToast(summary.message, summary.tone);
        // Successes leave the selection; failed/skipped rows stay
        // selected so the user can see and retry exactly those.
        setSelectedIds(new Set(summary.remainingIds));
        await refreshAfterMutation();
      } catch (error) {
        pushToast(error instanceof Error ? error.message : "Bulk action failed.", "error");
      } finally {
        setBusy(false);
      }
    },
    [pushToast, refreshAfterMutation]
  );

  const runBulk = useCallback<MailBulkContextValue["runBulk"]>(
    (action, rows, options) => {
      const { eligibleIds, skippedIds } = partitionForBulkAction(action, rows, perms);
      if (eligibleIds.length === 0) {
        pushToast("None of the selected messages can be processed with this action.", "info");
        return;
      }

      if (action === "reply" || action === "replyAll" || action === "forward") {
        const next = createComposeQueue(action as BulkComposeAction, eligibleIds, skippedIds);
        if (!next) return;
        setQueue(next);
        void onMessageAction(currentQueueId(next), action);
        return;
      }

      if (action === "createTicket" || action === "linkTicket" || action === "delete") {
        setDialog({ kind: action, eligibleIds, skippedIds });
        return;
      }

      const apiAction = BULK_ACTION_TO_API[action];
      if (!apiAction) return;
      void execute(
        { interactionIds: eligibleIds, action: apiAction, folderId: options?.folderId },
        skippedIds
      );
    },
    [perms, pushToast, onMessageAction, execute]
  );

  const markMessage = useCallback<MailBulkContextValue["markMessage"]>(
    async (interactionId, action) => {
      try {
        const result = await bulkMailAction({ interactionIds: [interactionId], action });
        if (result.succeeded < 1) {
          pushToast("You can't change that message.", "error");
          return;
        }
        await refreshAfterMutation();
      } catch (error) {
        pushToast(error instanceof Error ? error.message : "Action failed.", "error");
      }
    },
    [pushToast, refreshAfterMutation]
  );

  const closeDialog = () => setDialog(null);

  async function confirmCreate(choice: BulkCreateTicketChoice) {
    if (!dialog) return;
    const { eligibleIds, skippedIds } = dialog;
    await execute(
      {
        interactionIds: eligibleIds,
        action: "create_ticket",
        ticketType: choice.ticketType,
        currentPriority: choice.priority,
        agentId: choice.assignToMe ? currentUser?.user_id : null,
      },
      skippedIds
    );
    setDialog(null);
  }

  async function confirmLink(ticketId: string) {
    if (!dialog) return;
    const { eligibleIds, skippedIds } = dialog;
    await execute({ interactionIds: eligibleIds, action: "link_ticket", ticketId }, skippedIds);
    setDialog(null);
  }

  async function confirmDelete() {
    if (!dialog) return;
    const { eligibleIds, skippedIds } = dialog;
    await execute({ interactionIds: eligibleIds, action: "delete" }, skippedIds);
    setDialog(null);
  }

  function nextInQueue() {
    if (!queue) return;
    const next = advanceQueue(queue);
    setQueue(next);
    if (next) void onMessageAction(currentQueueId(next), next.action);
  }

  const value = useMemo<MailBulkContextValue>(
    () => ({
      selectedIds,
      platform,
      perms,
      isTrash,
      busy,
      toggle,
      selectAll,
      setSelection: setSelectedIds,
      clear,
      prune,
      markMessage,
      runBulk,
    }),
    [selectedIds, platform, perms, isTrash, busy, toggle, selectAll, clear, prune, markMessage, runBulk]
  );

  return (
    <MailBulkContext.Provider value={value}>
      {children}

      <BulkCreateTicketDialog
        open={dialog?.kind === "createTicket"}
        count={dialog?.eligibleIds.length ?? 0}
        busy={busy}
        onCancel={closeDialog}
        onConfirm={confirmCreate}
      />
      <BulkLinkTicketDialog
        open={dialog?.kind === "linkTicket"}
        count={dialog?.eligibleIds.length ?? 0}
        busy={busy}
        onCancel={closeDialog}
        onConfirm={confirmLink}
      />
      <AlertDialog open={dialog?.kind === "delete"}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {dialog?.eligibleIds.length ?? 0} messages?</AlertDialogTitle>
            <AlertDialogDescription>
              The messages move to Trash, where they can be restored (the audit trail is kept). Each
              message is checked on its own; any you can&apos;t delete are reported afterwards.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={closeDialog} disabled={busy}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete} disabled={busy}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {queue && (
        <div
          role="status"
          className="fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-lg border border-border bg-background px-4 py-2.5 text-sm shadow-lg"
        >
          <div className="flex flex-col">
            <span className="font-medium">
              Bulk {queueActionLabel(queue.action)} · {queueProgressLabel(queue)}
            </span>
            <span className="text-xs text-muted-foreground">
              Each message is handled on its own — nothing is sent until you confirm it.
              {queue.skippedIds.length > 0 && ` ${queue.skippedIds.length} not eligible, skipped.`}
            </span>
          </div>
          <Button size="sm" onClick={nextInQueue}>
            {advanceQueue(queue) ? "Next message" : "Finish"}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setQueue(null)}>
            Stop
          </Button>
        </div>
      )}
    </MailBulkContext.Provider>
  );
}
