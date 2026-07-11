import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Archive,
  FileText,
  Folder,
  Inbox,
  MailPlus,
  Plus,
  Send,
  Ticket,
  Trash2,
  UserCheck,
  UserX,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useAuthContext } from "@/context/AuthContext";
import type { MailViewKey } from "@/hooks/useMailInbox";
import type { MailFolder } from "@/types";

const VIEW_ITEMS: Array<{ key: MailViewKey; label: string; icon: LucideIcon }> = [
  { key: "pending", label: "Inbox", icon: Inbox },
  { key: "unassigned", label: "Unassigned", icon: UserX },
  { key: "mine", label: "My Claims", icon: UserCheck },
  { key: "sent", label: "Sent", icon: Send },
  { key: "drafts", label: "Drafts", icon: FileText },
  { key: "replied", label: "Replied", icon: MailPlus },
  { key: "ticketed", label: "Ticketed", icon: Ticket },
  { key: "archived", label: "Archived", icon: Archive },
];

// "Compose" has no raw outbound-authoring feature in this app yet —
// the closest real equivalent is simulating an inbound email via
// Create Dummy Mail. Hidden entirely for roles that can't reach that
// page (mirrors Sidebar.tsx's own hideForRoles — Site Lead only).
const COMPOSE_HIDDEN_ROLES = ["Staff", "Team Lead", "Account Manager", "Super Admin"];

interface MailSidebarProps {
  activeView: MailViewKey;
  onSelectView: (view: MailViewKey) => void;
  counts: Record<MailViewKey, number>;
  isSupervisor: boolean;
  folders: MailFolder[];
  folderCounts: Record<string, number>;
  activeFolder: string | null;
  onSelectFolder: (folderId: string | null) => void;
  onCreateFolder: (name: string) => Promise<MailFolder | null>;
  onDeleteFolder: (folderId: string) => Promise<void>;
}

export function MailSidebar({
  activeView,
  onSelectView,
  counts,
  isSupervisor,
  folders,
  folderCounts,
  activeFolder,
  onSelectFolder,
  onCreateFolder,
  onDeleteFolder,
}: MailSidebarProps) {
  const { currentUser } = useAuthContext();
  const canCompose = !COMPOSE_HIDDEN_ROLES.includes(currentUser?.role ?? "");

  const [isCreating, setIsCreating] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");

  async function handleCreateFolder() {
    const name = newFolderName.trim();
    if (!name) {
      setIsCreating(false);
      return;
    }
    const folder = await onCreateFolder(name);
    setNewFolderName("");
    setIsCreating(false);
    if (folder) onSelectFolder(folder.folder_id);
  }

  return (
    <div className="flex h-full flex-col gap-4 rounded-md2 border border-border bg-surface p-3 shadow-xs">
      {canCompose && (
        <Link
          to="/create-mail"
          className="flex items-center justify-center gap-2 rounded-md2 bg-accent px-4 py-2.5 text-[13px] font-semibold text-white shadow-xs transition-colors hover:bg-accent-600"
        >
          <MailPlus size={15} />
          Compose
        </Link>
      )}

      <nav className="flex flex-col gap-0.5">
        <p className="mb-1 px-2.5 text-[10px] font-semibold uppercase tracking-wider text-muted/70">
          Mail
        </p>
        {VIEW_ITEMS.map((item) => {
          const isActive = !activeFolder && activeView === item.key;
          const Icon = item.icon;
          return (
            <button
              key={item.key}
              onClick={() => onSelectView(item.key)}
              aria-pressed={isActive}
              className={`flex items-center gap-2.5 rounded-md2 px-2.5 py-2 text-[13px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${
                isActive
                  ? "bg-accent/10 text-accent"
                  : "text-slate-600 hover:bg-surfaceHover hover:text-slate-900"
              }`}
            >
              <Icon size={16} className="flex-none" strokeWidth={2.1} />
              <span className="flex-1 truncate text-left">{item.label}</span>
              <span
                className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                  isActive ? "bg-accent/20 text-accent" : "bg-slate-100 text-slate-500"
                }`}
              >
                {counts[item.key] ?? 0}
              </span>
            </button>
          );
        })}

        {isSupervisor && (
          <button
            onClick={() => onSelectView("all")}
            aria-pressed={!activeFolder && activeView === "all"}
            title="Every client's mail, not just yours — for when an Account Manager is on leave"
            className={`mt-1 flex items-center gap-2.5 rounded-md2 border-t border-border px-2.5 pt-2.5 pb-2 text-[13px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${
              !activeFolder && activeView === "all"
                ? "bg-accent/10 text-accent"
                : "text-slate-600 hover:bg-surfaceHover hover:text-slate-900"
            }`}
          >
            <Inbox size={16} className="flex-none" strokeWidth={2.1} />
            <span className="flex-1 truncate text-left">All Inboxes</span>
            <span
              className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                !activeFolder && activeView === "all" ? "bg-accent/20 text-accent" : "bg-slate-100 text-slate-500"
              }`}
            >
              {counts.all ?? 0}
            </span>
          </button>
        )}
      </nav>

      <div className="flex flex-col gap-0.5 border-t border-border pt-3">
        <div className="mb-1 flex items-center justify-between px-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted/70">
            Folders
          </p>
          <button
            onClick={() => setIsCreating((prev) => !prev)}
            title="New folder"
            className="rounded p-0.5 text-muted/70 hover:bg-surfaceHover hover:text-slate-900"
          >
            {isCreating ? <X size={13} /> : <Plus size={13} />}
          </button>
        </div>

        {isCreating && (
          <div className="mb-1 flex items-center gap-1 px-2.5">
            <input
              autoFocus
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreateFolder();
                if (e.key === "Escape") setIsCreating(false);
              }}
              placeholder="Folder name"
              className="w-full rounded-md2 border border-border bg-white px-2 py-1 text-[12px] outline-none focus:ring-2 focus:ring-accent/40"
            />
          </div>
        )}

        {folders.length === 0 && !isCreating && (
          <p className="px-2.5 text-[12px] text-muted/60">No folders yet.</p>
        )}

        {folders.map((folder) => {
          const isActive = activeFolder === folder.folder_id;
          return (
            <div
              key={folder.folder_id}
              className={`group flex items-center gap-2.5 rounded-md2 px-2.5 py-2 text-[13px] font-medium transition-colors ${
                isActive ? "bg-accent/10 text-accent" : "text-slate-600 hover:bg-surfaceHover hover:text-slate-900"
              }`}
            >
              <button
                onClick={() => onSelectFolder(isActive ? null : folder.folder_id)}
                aria-pressed={isActive}
                className="flex flex-1 items-center gap-2.5 text-left focus-visible:outline-none"
              >
                <Folder size={16} className="flex-none" strokeWidth={2.1} />
                <span className="flex-1 truncate">{folder.name}</span>
                <span
                  className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                    isActive ? "bg-accent/20 text-accent" : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {folderCounts[folder.folder_id] ?? 0}
                </span>
              </button>
              <button
                onClick={() => onDeleteFolder(folder.folder_id)}
                title="Delete folder"
                className="flex-none rounded p-0.5 text-muted/50 opacity-0 hover:text-danger group-hover:opacity-100"
              >
                <Trash2 size={13} />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
