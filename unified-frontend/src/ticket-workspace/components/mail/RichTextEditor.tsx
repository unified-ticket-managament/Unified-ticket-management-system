"use client";

import { useEffect, useMemo, useRef } from "react";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import TiptapImage from "@tiptap/extension-image";
import { Table } from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import {
  Bold,
  Italic,
  Link as LinkIcon,
  List,
  ListOrdered,
  Quote,
  Redo,
  Strikethrough,
  Undo,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { createDropHandler, createPasteHandler } from "@tw/lib/clipboardPaste";
import { type ImageUploader, useImagePasteUploads } from "@tw/hooks/useImagePasteUploads";
import { hasFailedImageUpload } from "@tw/lib/richText";
import { TableBubbleMenu } from "@tw/components/mail/TableBubbleMenu";

// Pasted-inline-image support (see lib/clipboardPaste.ts) needs a
// few custom attributes preserved through TipTap's HTML
// serialization that the base Image node doesn't carry by default —
// data-local-id (matches a just-pasted node back to its in-flight
// upload), data-attachment-id/data-content-id (the real backend
// reference once uploaded — see resolveInlineImageSources in
// lib/richText.ts, which reads data-content-id at send time), and
// data-upload-status (drives the error-state outline below).
const PastedImage = TiptapImage.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      "data-local-id": { default: null },
      "data-attachment-id": { default: null },
      "data-content-id": { default: null },
      "data-upload-status": { default: null },
    };
  },
});

interface RichTextEditorProps {
  value: string;
  onChange: (html: string) => void;
  placeholder?: string;
  minHeight?: string;
  disabled?: boolean;
  /**
   * Uploads a pasted/dropped screenshot through whichever attachment
   * endpoint this composer is already configured with, returning the
   * stored attachment's id and content_id. Omit for a composer with
   * no attachment-upload wiring yet — pasted images still preview
   * locally but are immediately marked as failed rather than hanging.
   */
  onImageUpload?: ImageUploader;
  /**
   * Fires whenever this editor has at least one pasted-image upload
   * still in flight OR permanently failed (oversized, network error,
   * no upload wiring for this composer) — composers should disable
   * Send while true, so a just-pasted image is never silently
   * dropped from the outgoing message with no indication to the user.
   */
  onPendingImageUploadsChange?: (hasPending: boolean) => void;
}

interface ToolbarButtonProps {
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  label: string;
  children: React.ReactNode;
}

function ToolbarButton({ onClick, active, disabled, label, children }: ToolbarButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40",
        active && "bg-primary/15 text-primary hover:bg-primary/15 hover:text-primary"
      )}
    >
      {children}
    </button>
  );
}

function Toolbar({ editor }: { editor: Editor | null }) {
  if (!editor) return null;

  return (
    <div className="flex flex-wrap items-center gap-0.5 border-b border-border px-2 py-1.5">
      <ToolbarButton
        label="Bold"
        active={editor.isActive("bold")}
        onClick={() => editor.chain().focus().toggleBold().run()}
      >
        <Bold className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        label="Italic"
        active={editor.isActive("italic")}
        onClick={() => editor.chain().focus().toggleItalic().run()}
      >
        <Italic className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        label="Strikethrough"
        active={editor.isActive("strike")}
        onClick={() => editor.chain().focus().toggleStrike().run()}
      >
        <Strikethrough className="h-3.5 w-3.5" />
      </ToolbarButton>
      <div className="mx-1 h-4 w-px bg-border" />
      <ToolbarButton
        label="Bullet list"
        active={editor.isActive("bulletList")}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
      >
        <List className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        label="Numbered list"
        active={editor.isActive("orderedList")}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
      >
        <ListOrdered className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        label="Quote"
        active={editor.isActive("blockquote")}
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
      >
        <Quote className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        label="Link"
        active={editor.isActive("link")}
        onClick={() => {
          const previousUrl = editor.getAttributes("link").href as string | undefined;
          const url = window.prompt("Link URL", previousUrl ?? "https://");
          if (url === null) return;
          if (!url) {
            editor.chain().focus().extendMarkRange("link").unsetLink().run();
            return;
          }
          editor.chain().focus().extendMarkRange("link").setLink({ href: url }).run();
        }}
      >
        <LinkIcon className="h-3.5 w-3.5" />
      </ToolbarButton>
      <div className="mx-1 h-4 w-px bg-border" />
      <ToolbarButton
        label="Undo"
        disabled={!editor.can().undo()}
        onClick={() => editor.chain().focus().undo().run()}
      >
        <Undo className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        label="Redo"
        disabled={!editor.can().redo()}
        onClick={() => editor.chain().focus().redo().run()}
      >
        <Redo className="h-3.5 w-3.5" />
      </ToolbarButton>
    </div>
  );
}

export function RichTextEditor({
  value,
  onChange,
  placeholder = "Write your message...",
  minHeight = "9rem",
  disabled = false,
  onImageUpload,
  onPendingImageUploadsChange,
}: RichTextEditorProps) {
  // useEditor's own config here only ever runs once (this file's
  // existing convention — editable/content changes are pushed via
  // explicit editor.setEditable/setContent calls below, not by
  // relying on useEditor re-running), so editorProps.handlePaste/
  // handleDrop must be stable closures that forward to whatever the
  // *latest* upload handler is, via a ref — not a value that closes
  // over a possibly-stale onImageUpload/editor from first render.
  const handleImageFileRef = useRef<(file: File, localId: string) => void>(() => {});

  const handlePaste = useMemo(
    () =>
      createPasteHandler({
        onImageFile: (file, localId) => handleImageFileRef.current(file, localId),
      }),
    []
  );
  const handleDrop = useMemo(
    () =>
      createDropHandler({
        onImageFile: (file, localId) => handleImageFileRef.current(file, localId),
      }),
    []
  );

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: false }),
      Link.configure({ openOnClick: false, autolink: true }),
      Placeholder.configure({ placeholder }),
      PastedImage.configure({ inline: true, allowBase64: false }),
      Table.configure({ resizable: false }),
      TableRow,
      TableHeader,
      TableCell,
    ],
    content: value,
    editable: !disabled,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class:
          "min-h-[--rte-min-h] px-3 py-2.5 text-sm text-foreground focus:outline-none [&_p]:mb-2 [&_p:last-child]:mb-0 [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_a]:text-primary [&_a]:underline [&_strong]:font-semibold [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_table]:my-2 [&_table]:border-collapse [&_table]:w-full [&_td]:border [&_td]:border-border [&_td]:p-1.5 [&_td]:align-top [&_th]:border [&_th]:border-border [&_th]:bg-muted [&_th]:p-1.5 [&_th]:text-left [&_th]:font-semibold [&_img]:mb-2 [&_img]:max-w-full [&_img]:rounded [&_img[data-upload-status=uploading]]:opacity-60 [&_img[data-upload-status=error]]:outline [&_img[data-upload-status=error]]:outline-2 [&_img[data-upload-status=error]]:outline-destructive",
      },
      handlePaste,
      handleDrop,
    },
    onUpdate: ({ editor: updated }) => onChange(updated.getHTML()),
  });

  const { handleImageFile, hasPendingUploads } = useImagePasteUploads(editor, onImageUpload);

  useEffect(() => {
    handleImageFileRef.current = handleImageFile;
  }, [handleImageFile]);

  // `value` (the parent-owned HTML, kept in sync via onChange on
  // every doc update) is re-scanned for a failed-upload marker on
  // every render — self-correcting: deleting the broken image node
  // clears this on the very next keystroke, unlike a manually
  // incremented/decremented counter. Combined with hasPendingUploads
  // into one "don't let Send silently drop pasted content" signal.
  useEffect(() => {
    onPendingImageUploadsChange?.(hasPendingUploads || hasFailedImageUpload(value));
  }, [hasPendingUploads, value, onPendingImageUploadsChange]);

  // Keep the editor in sync when the parent resets `value` out from
  // under it (switching threads, discarding a draft) — Tiptap is
  // uncontrolled internally, so this is the escape hatch for
  // externally-driven resets rather than every keystroke.
  useEffect(() => {
    if (!editor) return;
    if (value !== editor.getHTML()) {
      editor.commands.setContent(value, { emitUpdate: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, value]);

  useEffect(() => {
    editor?.setEditable(!disabled);
  }, [editor, disabled]);

  return (
    <div
      className={cn("overflow-hidden rounded-lg border border-input bg-background", disabled && "opacity-60")}
      style={{ ["--rte-min-h" as string]: minHeight }}
    >
      <Toolbar editor={editor} />
      <TableBubbleMenu editor={editor} />
      <EditorContent editor={editor} />
    </div>
  );
}

export function isRichTextEmpty(html: string): boolean {
  const stripped = html.replace(/<[^>]*>/g, "").trim();
  return stripped.length === 0;
}
