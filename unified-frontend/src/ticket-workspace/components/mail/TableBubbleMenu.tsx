"use client";

// Tiptap's Table/TableRow/TableHeader/TableCell extensions (registered in
// RichTextEditor.tsx) already support every command used below — no UI
// exposed any of them until now. This is a floating menu that appears only
// while the cursor/selection is inside a table, giving access to the row/
// column/header/delete commands that were previously only reachable via
// the editor's programmatic API.

import type { Editor } from "@tiptap/react";
import { BubbleMenu } from "@tiptap/react/menus";

import { cn } from "@/lib/utils";

interface TableMenuButtonProps {
  onClick: () => void;
  disabled?: boolean;
  label: string;
}

function TableMenuButton({ onClick, disabled, label }: TableMenuButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "whitespace-nowrap rounded-md px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
      )}
    >
      {label}
    </button>
  );
}

// The bubble menu's default anchor is the current text selection's own
// client rect — inside a table cell (every cell wraps its content in a
// <p>), that rect comes back degenerate (zero-width, pinned to the
// document's top-left) in this app's setup, throwing the whole menu's
// position off by hundreds of pixels. Anchoring to the enclosing
// <table> element's own (always well-formed) bounding rect instead
// sidesteps that entirely.
function getTableVirtualElement(editor: Editor) {
  const { node } = editor.view.domAtPos(editor.state.selection.anchor);
  const el = node instanceof HTMLElement ? node : node.parentElement;
  const tableEl = el?.closest("table") ?? null;
  if (!tableEl) return null;
  return { getBoundingClientRect: () => tableEl.getBoundingClientRect() };
}

export function TableBubbleMenu({ editor }: { editor: Editor | null }) {
  if (!editor) return null;

  return (
    <BubbleMenu
      editor={editor}
      pluginKey="tableBubbleMenu"
      shouldShow={({ editor: e }) => e.isActive("table")}
      getReferencedVirtualElement={() => getTableVirtualElement(editor)}
      options={{ placement: "top-start", offset: 8, flip: true, shift: true }}
      className="flex flex-wrap items-center gap-0.5 rounded-lg border border-border bg-popover p-1 shadow-md"
    >
      <TableMenuButton
        label="Add row above"
        disabled={!editor.can().addRowBefore()}
        onClick={() => editor.chain().focus().addRowBefore().run()}
      />
      <TableMenuButton
        label="Add row below"
        disabled={!editor.can().addRowAfter()}
        onClick={() => editor.chain().focus().addRowAfter().run()}
      />
      <TableMenuButton
        label="Delete row"
        disabled={!editor.can().deleteRow()}
        onClick={() => editor.chain().focus().deleteRow().run()}
      />
      <div className="mx-0.5 h-4 w-px bg-border" />
      <TableMenuButton
        label="Add column left"
        disabled={!editor.can().addColumnBefore()}
        onClick={() => editor.chain().focus().addColumnBefore().run()}
      />
      <TableMenuButton
        label="Add column right"
        disabled={!editor.can().addColumnAfter()}
        onClick={() => editor.chain().focus().addColumnAfter().run()}
      />
      <TableMenuButton
        label="Delete column"
        disabled={!editor.can().deleteColumn()}
        onClick={() => editor.chain().focus().deleteColumn().run()}
      />
      <div className="mx-0.5 h-4 w-px bg-border" />
      <TableMenuButton
        label="Toggle header row"
        disabled={!editor.can().toggleHeaderRow()}
        onClick={() => editor.chain().focus().toggleHeaderRow().run()}
      />
      <TableMenuButton
        label="Delete table"
        disabled={!editor.can().deleteTable()}
        onClick={() => editor.chain().focus().deleteTable().run()}
      />
    </BubbleMenu>
  );
}
