"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApiAction } from "@tw/hooks/useApiAction";
import type { MailFolder } from "@tw/types";

interface CreateFolderDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (name: string) => Promise<MailFolder>;
  // Defaults describe "create root folder"; the sidebar reuses this one
  // dialog for "Create subfolder" (parentName) and "Rename" (title,
  // submitLabel, initialName, successMessage, onCreate = rename).
  title?: string;
  submitLabel?: string;
  initialName?: string;
  successMessage?: string;
  parentName?: string | null;
}

// A duplicate-name 409 (and any other failure) surfaces through
// useApiAction's own error-toast path with the backend's own message
// ("A folder with this name already exists.") — run() swallows the
// error and returns null, which is exactly what keeps the dialog open
// below instead of closing on a failed create.
export function CreateFolderDialog({
  open,
  onOpenChange,
  onCreate,
  title = "Create Folder",
  submitLabel = "Create",
  initialName = "",
  successMessage = "Folder created.",
  parentName = null,
}: CreateFolderDialogProps) {
  const [name, setName] = useState(initialName);
  const { run, isLoading } = useApiAction(onCreate, { successMessage });

  // Re-seed whenever the dialog is (re)opened for a different target.
  useEffect(() => {
    if (open) setName(initialName);
  }, [open, initialName]);

  function handleOpenChange(next: boolean) {
    if (!next) setName("");
    onOpenChange(next);
  }

  async function handleCreate() {
    const trimmed = name.trim();
    if (!trimmed) return;
    const result = await run(trimmed);
    if (result) {
      setName("");
      onOpenChange(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {parentName && (
            <p className="text-xs text-muted-foreground">
              Inside &quot;{parentName}&quot;
            </p>
          )}
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="new-folder-name">Folder Name</Label>
          <Input
            id="new-folder-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleCreate();
              }
            }}
            placeholder="Billing"
            maxLength={100}
            autoFocus
          />
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" disabled={!name.trim() || isLoading} onClick={handleCreate}>
            {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
            {submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
