"use client";

import { useMemo } from "react";
import { Folder, FolderOutput } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useApiAction } from "@tw/hooks/useApiAction";
import { buildFolderTree, flattenVisible, subtreeIds } from "@tw/lib/folderTree";
import type { MailFolder } from "@tw/types";

interface MoveFolderDialogProps {
  // The folder being moved; null closes the dialog.
  folder: MailFolder | null;
  folders: MailFolder[];
  onOpenChange: (open: boolean) => void;
  onMove: (folderId: string, parentFolderId: string | null) => Promise<MailFolder>;
}

// Pick a new parent (or Root) for a folder. The folder itself and its
// own subfolders are not offered — the backend rejects cycles too, this
// just avoids showing choices that can never succeed.
export function MoveFolderDialog({ folder, folders, onOpenChange, onMove }: MoveFolderDialogProps) {
  const { run, isLoading } = useApiAction(
    (parentId: string | null) => onMove(folder!.folder_id, parentId),
    { successMessage: "Folder moved." }
  );

  const rows = useMemo(() => {
    if (!folder) return [];
    const excluded = subtreeIds(folders, folder.folder_id);
    const allowed = folders.filter((f) => !excluded.has(f.folder_id));
    const tree = buildFolderTree(allowed);
    const all = new Set(allowed.map((f) => f.folder_id));
    return flattenVisible(tree, all);
  }, [folder, folders]);

  async function pick(parentId: string | null) {
    if (!folder || isLoading) return;
    if ((folder.parent_folder_id ?? null) === parentId) {
      onOpenChange(false);
      return;
    }
    const result = await run(parentId);
    if (result) onOpenChange(false);
  }

  return (
    <Dialog open={!!folder} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Move &quot;{folder?.name.trim()}&quot;</DialogTitle>
        </DialogHeader>
        <div className="max-h-72 space-y-0.5 overflow-y-auto" role="listbox" aria-label="Destination folder">
          <button
            type="button"
            role="option"
            aria-selected={!folder?.parent_folder_id}
            onClick={() => pick(null)}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-muted"
          >
            <FolderOutput className="h-4 w-4 text-muted-foreground" />
            Root (top level)
          </button>
          {rows.map((node) => (
            <button
              key={node.folder.folder_id}
              type="button"
              role="option"
              aria-selected={folder?.parent_folder_id === node.folder.folder_id}
              onClick={() => pick(node.folder.folder_id)}
              style={{ paddingLeft: 8 + node.depth * 14 }}
              className={cn(
                "flex w-full items-center gap-2 rounded-md py-1.5 pr-2 text-left text-[13px] hover:bg-muted",
                folder?.parent_folder_id === node.folder.folder_id && "bg-primary/10 text-primary"
              )}
            >
              <Folder className="h-4 w-4 flex-none text-muted-foreground" />
              <span className="truncate">{node.folder.name.trim()}</span>
            </button>
          ))}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
