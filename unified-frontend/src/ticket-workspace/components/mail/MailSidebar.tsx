"use client";

import { memo, type ReactNode, useCallback, useMemo, useState } from "react";
import {
  Archive,
  Bell,
  FileEdit,
  Flag,
  ChevronRight,
  Folder,
  FolderOutput,
  FolderPlus,
  Inbox as InboxIcon,
  KeyRound,
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
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { cn } from "@/lib/utils";
import { CreateFolderDialog } from "@tw/components/mail/CreateFolderDialog";
import { MoveFolderDialog } from "@tw/components/mail/MoveFolderDialog";
import { useApiAction } from "@tw/hooks/useApiAction";
import { ancestorIds, buildFolderTree, flattenVisible } from "@tw/lib/folderTree";
import type { MailViewKey } from "@tw/hooks/useMailInbox";
import type { MailFolder } from "@tw/types";

// Exact order required by the Mail spec: Compose, All, Inbox, OTPs,
// My Claims, Sent, Drafts, Replied, Ticketed, Archived.
// Compose is rendered separately above this list (it's an action,
// not a folder view).
const VIEW_ITEMS: Array<{ key: MailViewKey; label: string; icon: LucideIcon }> = [
  { key: "pending", label: "All", icon: InboxIcon },
  { key: "unassigned", label: "Inbox", icon: UserX },
  // Fixed system section, not a mail folder — OTP mail the backend's
  // OTP classifier flagged (GET /inbox?view=otp), kept out of
  // Inbox/All server-side. Badge = unread OTPs.
  { key: "otp", label: "OTPs", icon: KeyRound },
  { key: "mine", label: "My Tickets", icon: UserCheck },
  { key: "sent", label: "Sent", icon: Send },
  { key: "drafts", label: "Drafts", icon: FileEdit },
  { key: "replied", label: "Replied", icon: Reply },
  { key: "ticketed", label: "Ticketed", icon: TicketIcon },
  { key: "archived", label: "Archived", icon: Archive },
  // The caller's own flagged mail across every folder (GET /inbox?view=flagged).
  { key: "flagged", label: "Flagged", icon: Flag },
  // Soft-deleted mail (GET /inbox?view=trash) — restorable.
  { key: "trash", label: "Trash", icon: Trash2 },
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
  onCreateFolder: (name: string, parentFolderId?: string | null) => Promise<MailFolder>;
  onRenameFolder: (folderId: string, name: string) => Promise<MailFolder>;
  onMoveFolder: (folderId: string, parentFolderId: string | null) => Promise<MailFolder>;
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

const EXPANDED_KEY = "mail_folder_expanded";

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
  onRenameFolder,
  onMoveFolder,
  onDeleteFolder,
  canManageRules,
  rulesActive,
  onOpenRules,
  variant = "standalone",
}: MailSidebarProps) {
  const viewItems = hideMyClaims ? VIEW_ITEMS.filter((item) => item.key !== "mine") : VIEW_ITEMS;
  const [createOpen, setCreateOpen] = useState(false);
  const [deletingFolder, setDeletingFolder] = useState<MailFolder | null>(null);
  const [subfolderParent, setSubfolderParent] = useState<MailFolder | null>(null);
  const [renamingFolder, setRenamingFolder] = useState<MailFolder | null>(null);
  const [movingFolder, setMovingFolder] = useState<MailFolder | null>(null);

  // Expand/collapse is pure UI state, persisted per browser.
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(EXPANDED_KEY);
      return new Set<string>(raw ? JSON.parse(raw) : []);
    } catch {
      return new Set<string>();
    }
  });
  const updateExpanded = useCallback((fn: (prev: Set<string>) => Set<string>) => {
    setExpanded((prev) => {
      const next = fn(prev);
      try {
        localStorage.setItem(EXPANDED_KEY, JSON.stringify([...next]));
      } catch {
        /* storage unavailable: state still works for this session */
      }
      return next;
    });
  }, []);
  const toggleExpanded = (id: string) =>
    updateExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // The path to the active folder is always revealed (derived, not stored).
  const shownExpanded = useMemo(
    () => (activeFolderId ? new Set([...expanded, ...ancestorIds(folders, activeFolderId)]) : expanded),
    [expanded, folders, activeFolderId]
  );

  const folderRows = useMemo(
    () => flattenVisible(buildFolderTree(folders), shownExpanded),
    [folders, shownExpanded]
  );
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
          folderRows.map(({ folder, depth, children }) => {
            const isActive = !isComposing && activeFolderId === folder.folder_id;
            const hasChildren = children.length > 0;
            const isOpen = shownExpanded.has(folder.folder_id);
            const label = folder.name.trim();
            return (
              <ContextMenu key={folder.folder_id} modal={false}>
                <ContextMenuTrigger asChild>
                  <div
                    data-active={isActive}
                    role="treeitem"
                    aria-level={depth + 1}
                    aria-expanded={hasChildren ? isOpen : undefined}
                    aria-selected={isActive}
                    style={{ paddingLeft: 6 + depth * 14 }}
                    className={cn(
                      "group flex items-center gap-1 rounded-lg pr-1.5 py-2 text-left text-[13px] font-medium transition-all duration-150",
                      isActive
                        ? "bg-primary/10 text-primary"
                        : "text-foreground/80 hover:bg-muted hover:text-foreground"
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => toggleExpanded(folder.folder_id)}
                      aria-label={isOpen ? `Collapse ${label}` : `Expand ${label}`}
                      tabIndex={hasChildren ? 0 : -1}
                      className={cn(
                        "flex h-5 w-5 flex-none items-center justify-center rounded text-muted-foreground hover:text-foreground",
                        !hasChildren && "invisible"
                      )}
                    >
                      <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", isOpen && "rotate-90")} />
                    </button>
                    <button
                      type="button"
                      onClick={() => onSelectFolder(folder.folder_id)}
                      title={label}
                      className="flex flex-1 items-center gap-2.5 overflow-hidden text-left"
                    >
                      <Folder className={cn("h-4 w-4 flex-none", isActive ? "text-primary" : "text-muted-foreground")} />
                      <span className="truncate">{label}</span>
                      <CountBadge count={folderCounts[folder.folder_id] ?? 0} />
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeletingFolder(folder);
                      }}
                      aria-label={`Delete ${label}`}
                      className="flex-none rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </ContextMenuTrigger>
                <ContextMenuContent className="w-48" onCloseAutoFocus={(e) => e.preventDefault()}>
                  <ContextMenuItem onSelect={() => onSelectFolder(folder.folder_id)}>
                    <Folder className="mr-2 h-4 w-4" />
                    Open
                  </ContextMenuItem>
                  <ContextMenuItem onSelect={() => setSubfolderParent(folder)}>
                    <FolderPlus className="mr-2 h-4 w-4" />
                    Create subfolder
                  </ContextMenuItem>
                  <ContextMenuItem onSelect={() => setRenamingFolder(folder)}>
                    <Pencil className="mr-2 h-4 w-4" />
                    Rename
                  </ContextMenuItem>
                  <ContextMenuItem onSelect={() => setMovingFolder(folder)}>
                    <FolderOutput className="mr-2 h-4 w-4" />
                    Move
                  </ContextMenuItem>
                  <ContextMenuSeparator />
                  <ContextMenuItem
                    onSelect={() => setDeletingFolder(folder)}
                    className="text-destructive focus:text-destructive"
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    Delete
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            );
          })
        )}
      </div>

      <CreateFolderDialog open={createOpen} onOpenChange={setCreateOpen} onCreate={(name) => onCreateFolder(name, null)} />
      <CreateFolderDialog
        open={!!subfolderParent}
        onOpenChange={(open) => !open && setSubfolderParent(null)}
        onCreate={(name) => onCreateFolder(name, subfolderParent?.folder_id ?? null)}
        title="Create Subfolder"
        parentName={subfolderParent?.name.trim() ?? null}
        successMessage="Subfolder created."
      />
      <CreateFolderDialog
        open={!!renamingFolder}
        onOpenChange={(open) => !open && setRenamingFolder(null)}
        onCreate={(name) => onRenameFolder(renamingFolder!.folder_id, name)}
        title="Rename Folder"
        submitLabel="Rename"
        initialName={renamingFolder?.name.trim() ?? ""}
        successMessage="Folder renamed."
      />
      <MoveFolderDialog
        folder={movingFolder}
        folders={folders}
        onOpenChange={(open) => !open && setMovingFolder(null)}
        onMove={onMoveFolder}
      />

      <AlertDialog
        open={!!deletingFolder}
        onOpenChange={(open) => !open && setDeletingFolder(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete folder</AlertDialogTitle>
            <AlertDialogDescription>
              Delete folder &quot;{deletingFolder?.name.trim()}&quot;? Any emails filed here will
              become unfiled. Subfolders are kept and move up one level.
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
