"use client";

import { Check } from "lucide-react";

import {
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
} from "@/components/ui/context-menu";
import {
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { buildFolderTree, type FolderNode } from "@tw/lib/folderTree";
import type { MailFolder } from "@tw/types";

// The nested folder list shared by every "Move to" menu (message
// actions, right-click, bulk bar, reading pane). A folder with
// subfolders becomes a submenu whose first entry files into that folder
// itself; leaves are plain items.
const PRIMS = {
  dropdown: {
    Item: DropdownMenuItem,
    Separator: DropdownMenuSeparator,
    Sub: DropdownMenuSub,
    SubTrigger: DropdownMenuSubTrigger,
    SubContent: DropdownMenuSubContent,
  },
  context: {
    Item: ContextMenuItem,
    Separator: ContextMenuSeparator,
    Sub: ContextMenuSub,
    SubTrigger: ContextMenuSubTrigger,
    SubContent: ContextMenuSubContent,
  },
} as const;

interface FolderMoveItemsProps {
  kind: "dropdown" | "context";
  folders: MailFolder[];
  currentFolderId?: string | null;
  onPick: (folderId: string) => void;
}

export function FolderMoveItems({ kind, folders, currentFolderId, onPick }: FolderMoveItemsProps) {
  const { Item, Separator, Sub, SubTrigger, SubContent } = PRIMS[kind];

  const check = (id: string) => (
    <Check className={cn("mr-2 h-3.5 w-3.5", currentFolderId === id ? "opacity-100" : "opacity-0")} />
  );

  const render = (node: FolderNode) => {
    const { folder, children } = node;
    const label = folder.name.trim();
    if (children.length === 0) {
      return (
        <Item key={folder.folder_id} onSelect={() => onPick(folder.folder_id)}>
          {check(folder.folder_id)}
          <span className="truncate">{label}</span>
        </Item>
      );
    }
    return (
      <Sub key={folder.folder_id}>
        <SubTrigger>
          <span className="truncate">{label}</span>
        </SubTrigger>
        <SubContent className="max-h-72 overflow-y-auto">
          <Item onSelect={() => onPick(folder.folder_id)}>
            {check(folder.folder_id)}
            <span className="truncate">{label}</span>
          </Item>
          <Separator />
          {children.map(render)}
        </SubContent>
      </Sub>
    );
  };

  return <>{buildFolderTree(folders).map(render)}</>;
}
