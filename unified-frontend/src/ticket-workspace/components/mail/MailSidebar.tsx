"use client";

import { memo, type ReactNode, useState } from "react";
import {
  Archive,
  Bell,
  FileEdit,
  Folder,
  Inbox as InboxIcon,
  Pencil,
  Plus,
  Reply,
  Send,
  Ticket as TicketIcon,
  Trash2,
  UserCheck,
  UserX,
  Workflow,
  type LucideIcon,
} from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CreateFolderDialog } from "@tw/components/mail/CreateFolderDialog";
import { useApiAction } from "@tw/hooks/useApiAction";
import type { MailViewKey } from "@tw/hooks/useMailInbox";
import type { MailFolder } from "@tw/types";

// Exact order required by the Mail spec: Compose, Inbox, Unassigned,
// My Claims, Sent, Drafts, Replied, Ticketed, Archived.
// Compose is rendered separately above this list (it's an action,
// not a folder view).
const VIEW_ITEMS: Array<{ key: MailViewKey; label: string; icon: LucideIcon }> = [
  { key: "pending", label: "Inbox", icon: InboxIcon },
  { key: "unassigned", label: "Unassigned", icon: UserX },
  { key: "mine", label: "My Tickets", icon: UserCheck },
  { key: "sent", label: "Sent", icon: Send },
  { key: "drafts", label: "Drafts", icon: FileEdit },
  { key: "replied", label: "Replied", icon: Reply },
  { key: "ticketed", label: "Ticketed", icon: TicketIcon },
  { key: "archived", label: "Archived", icon: Archive },
  // Internal system notices (SLA breach ladder + escalation workflow)
  // rendered in mail format — see useMailInbox.ts's systemNotifications
  // and SystemMailList/SystemMailDetailsView. Not part of the Mail
  // spec's original required order above; appended rather than
  // inserted so that order stays intact.
  { key: "system", label: "System", icon: Bell },
];

interface MailSidebarProps {
  activeView: MailViewKey;
  isComposing: boolean;
  onSelectView: (view: MailViewKey) => void;
  onCompose: () => void;
  counts: Partial<Record<MailViewKey, number>>;
  // "My Claims" is hidden specifically for Staff — every other role
  // with a Mail tab keeps it (nothing else in this sidebar is
  // role-gated per-item today).
  hideMyClaims: boolean;
  // Custom mail folders (e.g. ones a Mail Rule filed an email into) —
  // rendered as their own section below the main view list, mutually
  // exclusive with the normal view tabs above (selecting a folder
  // doesn't change activeView; selecting a view clears the folder).
  folders: MailFolder[];
  folderCounts: Record<string, number>;
  activeFolderId: string | null;
  onSelectFolder: (folderId: string) => void;
  onCreateFolder: (name: string) => Promise<MailFolder>;
  onDeleteFolder: (folderId: string) => Promise<void>;
  // Rules moved under Mail — visible only to the roles holding
  // rule:manage (Super Admin, Site Lead, Account Manager, Team Lead).
  // Mutually exclusive with every view/folder above, same as Compose.
  canManageRules: boolean;
  rulesActive: boolean;
  onOpenRules: () => void;
  // "standalone" (default) keeps this component's own card chrome and
  // fixed viewport-relative sizing for any caller rendering it on its
  // own. "panel" — used by the Outlook-style three-panel Mail
  // workspace, see InboxPage.tsx/MailWorkspaceLayout.tsx — drops that
  // chrome and fills its parent panel's own width/height instead,
  // since the workspace's outer container already supplies the card
  // look for the whole three-panel area.
  variant?: "standalone" | "panel";
}

function CountBadge({ count }: { count: number }): ReactNode {
  if (!count) return null;
  return (
    <span className="ml-auto min-w-[1.375rem] rounded-full bg-muted px-1.5 py-0.5 text-center text-[11px] font-semibold tabular-nums text-muted-foreground group-data-[active=true]:bg-primary/15 group-data-[active=true]:text-primary">
      {count > 99 ? "99+" : count}
    </span>
  );
}

// Memoized: InboxPage re-renders on every Mail search keystroke (the
// search box's state lives in the same hook this sidebar reads its
// props from), and this sidebar's own content — nav items — has
// nothing to do with the search text. Only actually skips re-rendering
// if its props are referentially stable; see useMailInbox's
// setActiveView (useCallback-wrapped) and InboxPage's own
// useCallback-wrapped handlers passed in below.
export const MailSidebar = memo(function MailSidebar({
  activeView,
  isComposing,
  onSelectView,
  onCompose,
  counts,
  hideMyClaims,
  folders,
  folderCounts,
  activeFolderId,
  onSelectFolder,
  onCreateFolder,
  onDeleteFolder,
  canManageRules,
  rulesActive,
  onOpenRules,
  variant = "standalone",
}: MailSidebarProps) {
  const viewItems = hideMyClaims ? VIEW_ITEMS.filter((item) => item.key !== "mine") : VIEW_ITEMS;
  const [createOpen, setCreateOpen] = useState(false);
  const [deletingFolder, setDeletingFolder] = useState<MailFolder | null>(null);
  const { run: runDeleteFolder, isLoading: isDeletingFolder } = useApiAction(onDeleteFolder, {
    successMessage: "Folder deleted.",
  });

  async function handleConfirmDelete() {
    if (!deletingFolder) return;
    const result = await runDeleteFolder(deletingFolder.folder_id);
    // useApiAction returns undefined (not null) for a void action's
    // success — only a genuine thrown error resolves to null, so any
    // non-null result (including undefined) here means the delete
    // actually went through.
    if (result !== null) setDeletingFolder(null);
  }

  return (
    <aside
      className={cn(
        "flex flex-col gap-4 overflow-y-auto p-3",
        variant === "panel"
          ? "h-full w-full"
          : "w-full rounded-xl border border-border bg-card shadow-card lg:sticky lg:top-0 lg:h-[calc(100vh-7rem)] lg:w-[248px] lg:flex-none"
      )}
    >
      <Button
        onClick={onCompose}
        data-active={isComposing}
        size="sm"
        className="h-9 w-fit self-start gap-2 rounded-lg px-4 text-[13px] font-semibold shadow-sm"
      >
        <Pencil className="h-3.5 w-3.5" />
        Compose
      </Button>

      <nav className="flex flex-col gap-0.5">
        {viewItems.map((item) => {
          const Icon = item.icon;
          const isActive = !isComposing && activeView === item.key;
          return (
            <button
              key={item.key}
              type="button"
              data-active={isActive}
              onClick={() => onSelectView(item.key)}
              className={cn(
                "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] font-medium transition-all duration-150",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-foreground/80 hover:translate-x-0.5 hover:bg-muted hover:text-foreground"
              )}
            >
              <Icon className={cn("h-4 w-4 flex-none", isActive ? "text-primary" : "text-muted-foreground")} />
              <span className="truncate">{item.label}</span>
              <CountBadge count={counts[item.key] ?? 0} />
            </button>
          );
        })}
      </nav>

      {canManageRules && (
        <div className="flex flex-col gap-0.5 border-t border-border pt-3">
          <button
            type="button"
            data-active={rulesActive}
            onClick={onOpenRules}
            className={cn(
              "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] font-medium transition-all duration-150",
              rulesActive
                ? "bg-primary/10 text-primary"
                : "text-foreground/80 hover:translate-x-0.5 hover:bg-muted hover:text-foreground"
            )}
          >
            <Workflow className={cn("h-4 w-4 flex-none", rulesActive ? "text-primary" : "text-muted-foreground")} />
            <span className="truncate">Rules</span>
          </button>
        </div>
      )}

      <div className="flex flex-col gap-0.5 border-t border-border pt-3">
        <div className="flex items-center justify-between px-3 pb-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Folders
          </p>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-5 w-5 text-muted-foreground hover:text-foreground"
            onClick={() => setCreateOpen(true)}
            aria-label="Create folder"
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>
        {folders.length === 0 ? (
          <p className="px-3 py-1 text-[12px] text-muted-foreground">
            No folders yet — create one to organize mail.
          </p>
        ) : (
          folders.map((folder) => {
            const isActive = !isComposing && activeFolderId === folder.folder_id;
            return (
              <div
                key={folder.folder_id}
                data-active={isActive}
                className={cn(
                  "group flex items-center gap-2.5 rounded-lg pl-3 pr-1.5 py-2 text-left text-[13px] font-medium transition-all duration-150",
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-foreground/80 hover:bg-muted hover:text-foreground"
                )}
              >
                <button
                  type="button"
                  onClick={() => onSelectFolder(folder.folder_id)}
                  className="flex flex-1 items-center gap-2.5 overflow-hidden text-left"
                >
                  <Folder className={cn("h-4 w-4 flex-none", isActive ? "text-primary" : "text-muted-foreground")} />
                  <span className="truncate">{folder.name.trim()}</span>
                  <CountBadge count={folderCounts[folder.folder_id] ?? 0} />
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeletingFolder(folder);
                  }}
                  aria-label={`Delete ${folder.name.trim()}`}
                  className="flex-none rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            );
          })
        )}
      </div>

      <CreateFolderDialog open={createOpen} onOpenChange={setCreateOpen} onCreate={onCreateFolder} />

      <AlertDialog
        open={!!deletingFolder}
        onOpenChange={(open) => !open && setDeletingFolder(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete folder</AlertDialogTitle>
            <AlertDialogDescription>
              Delete folder &quot;{deletingFolder?.name.trim()}&quot;? Any emails filed here will
              become unfiled.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction disabled={isDeletingFolder} onClick={handleConfirmDelete}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </aside>
  );
});
