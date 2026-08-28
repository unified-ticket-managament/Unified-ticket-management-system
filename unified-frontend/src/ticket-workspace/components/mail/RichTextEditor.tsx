"use client";

import { useEffect, useMemo, useRef } from "react";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { TableMap, cellAround } from "@tiptap/pm/tables";
import type { EditorView } from "@tiptap/pm/view";
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
// Bare `width`/`height` HTML attributes (never a CSS `style` — the
// backend sanitizer's allow-list only permits width/height as plain
// attributes on <img>, and they're also the most Outlook-reliable way
// to size an image) — set by the resize handle in the NodeView below,
// read back on send via editor.getHTML() with no extra extraction
// step.
const PastedImage = TiptapImage.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      "data-local-id": { default: null },
      "data-attachment-id": { default: null },
      "data-content-id": { default: null },
      "data-upload-status": { default: null },
      width: {
        default: null,
        parseHTML: (element) => element.getAttribute("width"),
        renderHTML: (attributes) => (attributes.width ? { width: attributes.width } : {}),
      },
      height: {
        default: null,
        parseHTML: (element) => element.getAttribute("height"),
        renderHTML: (attributes) => (attributes.height ? { height: attributes.height } : {}),
      },
    };
  },
  addNodeView() {
    return ({ node, editor, getPos }) => {
      let currentNode = node;

      const wrapper = document.createElement("span");
      wrapper.style.position = "relative";
      wrapper.style.display = "inline-block";
      wrapper.style.maxWidth = "100%";
      wrapper.className = "rte-image-wrapper";

      const img = document.createElement("img");
      img.className = "max-w-full rounded";

      const applyAttrs = (attrs: Record<string, string | number | null | undefined>) => {
        img.setAttribute("src", (attrs.src as string) ?? "");
        for (const key of ["alt", "width", "height", "data-local-id", "data-attachment-id", "data-content-id", "data-upload-status"]) {
          const value = attrs[key];
          if (value === null || value === undefined || value === "") {
            img.removeAttribute(key);
          } else {
            img.setAttribute(key, String(value));
          }
        }
      };
      applyAttrs(currentNode.attrs);
      wrapper.appendChild(img);

      const handle = document.createElement("span");
      handle.contentEditable = "false";
      handle.style.position = "absolute";
      handle.style.right = "-6px";
      handle.style.bottom = "-6px";
      handle.style.width = "12px";
      handle.style.height = "12px";
      handle.style.borderRadius = "9999px";
      handle.style.background = "#2563eb";
      handle.style.border = "2px solid white";
      handle.style.cursor = "nwse-resize";
      handle.style.touchAction = "none";
      wrapper.appendChild(handle);

      let startX = 0;
      let startWidth = 0;
      let aspectRatio = 1;

      const onPointerMove = (event: PointerEvent) => {
        const delta = event.clientX - startX;
        const newWidth = Math.max(40, Math.round(startWidth + delta));
        img.setAttribute("width", String(newWidth));
        img.setAttribute("height", String(Math.round(newWidth / aspectRatio)));
      };

      const commit = () => {
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", commit);
        const pos = getPos();
        if (typeof pos !== "number") return;
        const width = img.getAttribute("width");
        const height = img.getAttribute("height");
        editor.view.dispatch(
          editor.view.state.tr.setNodeMarkup(pos, undefined, {
            ...currentNode.attrs,
            width: width ? Number(width) : null,
            height: height ? Number(height) : null,
          })
        );
      };

      handle.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const rect = img.getBoundingClientRect();
        startX = event.clientX;
        startWidth = rect.width;
        aspectRatio = rect.width / (rect.height || 1);
        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", commit);
      });

      return {
        dom: wrapper,
        update(updatedNode) {
          if (updatedNode.type !== node.type) return false;
          currentNode = updatedNode;
          applyAttrs(currentNode.attrs);
          return true;
        },
        // The drag handle mutates `img`'s width/height attributes
        // directly (see onPointerMove) for zero-latency live feedback
        // instead of dispatching a transaction on every pointermove —
        // without this, ProseMirror's DOMObserver sees those as
        // unexpected external edits and force-rebuilds this node view
        // mid-drag, tearing down the very listeners doing the
        // dragging before pointerup ever gets to commit the result.
        ignoreMutation() {
          return true;
        },
        destroy() {
          window.removeEventListener("pointermove", onPointerMove);
          window.removeEventListener("pointerup", commit);
        },
      };
    };
  },
});

// Whole-table resize — a plain `width` HTML attribute on <table> is
// what Outlook's Word rendering engine reliably honors; colgroup/col
// widths are not (see html_sanitizer.py's matching
// _ALLOWED_ATTRIBUTES/_style_email_tables changes on the backend,
// which read this same attribute). Per-column resize lives separately,
// in the ColumnResize plugin below (a bare `width` attribute per cell
// instead of colgroup/col, for the same Outlook-compatibility reason).
// Mirrors prosemirror-tables' own default wrapper-div-around-table
// structure (contentDOM = tbody) so cell selection/row/column editing
// keep working unchanged.
const ResizableTable = Table.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      width: {
        default: null,
        parseHTML: (element) => element.getAttribute("width"),
        renderHTML: (attributes) => (attributes.width ? { width: attributes.width } : {}),
      },
    };
  },
  addNodeView() {
    return ({ node, editor, getPos, HTMLAttributes }) => {
      let currentNode = node;

      // Two nested divs, not one: the OUTER one clips/scrolls overflow
      // (Column resizing below can grow a table wider than the
      // composer's own width — scrolling this container rather than
      // letting it blow out the editor's layout is what keeps the
      // table "inside the editor/container without causing broken
      // layout" for the per-column case, same goal maxWidth already
      // serves for whole-table resize). The resize handle further down
      // deliberately pokes a few pixels outside the table's own box
      // (so it's grabbable right at the border) — if that positioning
      // happened on the SAME element that clips overflow, the handle
      // would clip itself into invisibility/unclickability the moment
      // the table's width ever equals the wrapper's width (i.e.
      // immediately). The INNER div only positions the handle and
      // never clips, so the handle stays reachable regardless.
      const scrollContainer = document.createElement("div");
      scrollContainer.style.maxWidth = "100%";
      scrollContainer.style.overflowX = "auto";
      scrollContainer.className = "rte-table-scroll";

      const wrapper = document.createElement("div");
      wrapper.style.position = "relative";
      // A plain block-level div defaults to filling the whole
      // available editor width regardless of the <table>'s own
      // (typically much narrower, content-sized) width — the resize
      // handle below is positioned relative to THIS element, so
      // without `fit-content` it ends up hundreds of pixels away from
      // the table's actual right border instead of sitting next to it.
      wrapper.style.width = "fit-content";
      wrapper.className = "rte-table-wrapper";
      scrollContainer.appendChild(wrapper);

      const table = document.createElement("table");
      Object.entries(HTMLAttributes).forEach(([key, value]) => {
        if (value !== null && value !== undefined) table.setAttribute(key, String(value));
      });

      const tbody = document.createElement("tbody");
      table.appendChild(tbody);
      wrapper.appendChild(table);

      const handle = document.createElement("span");
      handle.contentEditable = "false";
      handle.style.position = "absolute";
      handle.style.top = "50%";
      handle.style.right = "-4px";
      handle.style.transform = "translateY(-50%)";
      handle.style.width = "6px";
      handle.style.height = "32px";
      handle.style.borderRadius = "3px";
      handle.style.background = "#94a3b8";
      handle.style.cursor = "ew-resize";
      handle.style.touchAction = "none";
      wrapper.appendChild(handle);

      let startX = 0;
      let startWidth = 0;

      const onPointerMove = (event: PointerEvent) => {
        const delta = event.clientX - startX;
        const newWidth = Math.max(150, Math.round(startWidth + delta));
        table.setAttribute("width", String(newWidth));
        table.style.width = `${newWidth}px`;
      };

      const commit = () => {
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", commit);
        const pos = getPos();
        if (typeof pos !== "number") return;
        const width = table.getAttribute("width");
        editor.view.dispatch(
          editor.view.state.tr.setNodeMarkup(pos, undefined, {
            ...currentNode.attrs,
            width: width ? Number(width) : null,
          })
        );
      };

      // Also stop the paired native "mousedown" (pointerdown's
      // stopPropagation doesn't cover it — they're independent
      // dispatches) from reaching ProseMirror's own click-to-select
      // handling on view.dom; this handle sits outside contentDOM
      // specifically so a click on it is never mistaken for a content
      // click.
      handle.addEventListener("mousedown", (event) => {
        event.preventDefault();
        event.stopPropagation();
      });
      handle.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        event.stopPropagation();
        startX = event.clientX;
        startWidth = table.getBoundingClientRect().width;
        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", commit);
      });

      return {
        dom: scrollContainer,
        contentDOM: tbody,
        update(updatedNode) {
          if (updatedNode.type !== node.type) return false;
          currentNode = updatedNode;
          if (updatedNode.attrs.width) {
            table.setAttribute("width", String(updatedNode.attrs.width));
            table.style.width = `${updatedNode.attrs.width}px`;
          } else {
            table.removeAttribute("width");
            table.style.width = "";
          }
          return true;
        },
        // The drag handle mutates the <table> element's own width
        // attribute/style directly (see onPointerMove) for
        // zero-latency live feedback instead of dispatching a
        // transaction on every pointermove — without this,
        // ProseMirror's DOMObserver sees that as an unexpected
        // external edit and force-rebuilds this node view mid-drag,
        // tearing down the very listeners doing the dragging before
        // pointerup ever gets to commit the result. Only mutations
        // outside contentDOM (tbody) are ours to ignore this way —
        // real content edits inside tbody still need normal handling.
        ignoreMutation(mutation) {
          return !tbody.contains(mutation.target);
        },
        destroy() {
          window.removeEventListener("pointermove", onPointerMove);
          window.removeEventListener("pointerup", commit);
        },
      };
    };
  },
});

// Per-column resizing. TipTap's Table extension has its own built-in
// column-resize plugin (`resizable: true`), but it stores widths as a
// `colwidth` node attribute rendered into a <colgroup>/<col> pair —
// exactly the mechanism ResizableTable's own comment above already
// rules out (Outlook's Word rendering engine doesn't reliably honor
// colgroup/col; html_sanitizer.py strips those tags outright, see
// test_colgroup_and_col_are_stripped_from_outbound_tables). So this
// reimplements only the drag-interaction half of that plugin — reusing
// its own TableMap/cellAround helpers from prosemirror-tables rather
// than re-deriving table topology by hand — while writing a bare
// `width` HTML attribute onto every cell in the dragged column
// instead, mirroring ResizableTable's own table-width attribute and
// html_sanitizer.py's matching td/th width allowance.
const ResizableTableCell = TableCell.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      width: {
        default: null,
        parseHTML: (element) => element.getAttribute("width"),
        renderHTML: (attributes) => (attributes.width ? { width: attributes.width } : {}),
      },
    };
  },
});

const ResizableTableHeader = TableHeader.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      width: {
        default: null,
        parseHTML: (element) => element.getAttribute("width"),
        renderHTML: (attributes) => (attributes.width ? { width: attributes.width } : {}),
      },
    };
  },
});

const MIN_COLUMN_WIDTH = 48;
const RESIZE_HOT_ZONE_PX = 6;

// Writes `width` onto every single-column cell in the dragged column
// (every row, via TableMap so rowspan/colspan are resolved correctly —
// the same lookup prosemirror-tables' own updateColumnWidth performs
// internally, just targeting our own attribute instead of `colwidth`).
// A cell that spans multiple columns is left untouched: a single
// column's drag can't cleanly redistribute into a merged cell's width
// without also touching the other columns it spans, which would
// silently affect a column the user never touched.
function updateColumnWidth(view: EditorView, cellPos: number, width: number) {
  const { state } = view;
  const $cell = state.doc.resolve(cellPos);
  const table = $cell.node(-1);
  const cellNode = $cell.nodeAfter;
  if (!table || table.type.spec.tableRole !== "table" || !cellNode) return;

  const map = TableMap.get(table);
  const start = $cell.start(-1);
  const col = map.colCount(cellPos - start) + (Number(cellNode.attrs.colspan) || 1) - 1;

  let tr = state.tr;
  let changed = false;
  for (let row = 0; row < map.height; row++) {
    const mapIndex = row * map.width + col;
    if (row && map.map[mapIndex] === map.map[mapIndex - map.width]) continue; // rowspan continuation
    const cellStart = map.map[mapIndex];
    const node = table.nodeAt(cellStart);
    if (!node || (Number(node.attrs.colspan) || 1) !== 1) continue;
    if (node.attrs.width === width) continue;
    tr = tr.setNodeMarkup(start + cellStart, undefined, { ...node.attrs, width });
    changed = true;
  }
  if (changed) view.dispatch(tr);
}

// Finds the cell (if any) whose right edge the pointer is currently
// within RESIZE_HOT_ZONE_PX of — the same "posAtDOM + cellAround"
// approach prosemirror-tables' own plugin uses to resolve a DOM
// coordinate back to a real cell position, so column topology (which
// table, which row, which cell) is always read from the live DOM
// rather than assumed.
function findColumnBoundaryCell(
  view: EditorView,
  event: PointerEvent
): { cellPos: number; cellEl: HTMLElement } | null {
  const targetEl = event.target;
  if (!(targetEl instanceof Element)) return null;
  const cellEl = targetEl.closest("td, th");
  if (!(cellEl instanceof HTMLElement) || !view.dom.contains(cellEl)) return null;

  const rect = cellEl.getBoundingClientRect();
  if (event.clientX < rect.right - RESIZE_HOT_ZONE_PX || event.clientX > rect.right + RESIZE_HOT_ZONE_PX) {
    return null;
  }

  let innerPos: number;
  try {
    innerPos = view.posAtDOM(cellEl, 0);
  } catch {
    return null;
  }
  const $cell = cellAround(view.state.doc.resolve(innerPos));
  if (!$cell) return null;
  return { cellPos: $cell.pos, cellEl };
}

interface ColumnDragState {
  cellPos: number;
  colIndex: number;
  startX: number;
  startWidth: number;
  currentWidth: number;
  tableEl: HTMLTableElement;
}

const ColumnResize = Extension.create({
  name: "columnResize",
  addProseMirrorPlugins() {
    let dragState: ColumnDragState | null = null;

    return [
      new Plugin({
        key: new PluginKey("columnResize"),
        props: {
          handleDOMEvents: {
            pointermove(view, event) {
              if (dragState || !view.editable) return false;
              const hit = findColumnBoundaryCell(view, event as PointerEvent);
              view.dom.style.cursor = hit ? "col-resize" : "";
              return false;
            },
            pointerleave(view) {
              if (!dragState) view.dom.style.removeProperty("cursor");
              return false;
            },
            pointerdown(view, event) {
              if (!view.editable) return false;
              const hit = findColumnBoundaryCell(view, event as PointerEvent);
              if (!hit) return false;

              const rowEl = hit.cellEl.parentElement;
              const tableEl = hit.cellEl.closest("table");
              if (!rowEl || !tableEl) return false;
              const colIndex = Array.prototype.indexOf.call(rowEl.children, hit.cellEl);

              event.preventDefault();
              const startWidth = hit.cellEl.getBoundingClientRect().width;
              dragState = {
                cellPos: hit.cellPos,
                colIndex,
                startX: (event as PointerEvent).clientX,
                startWidth,
                currentWidth: startWidth,
                tableEl,
              };

              const onPointerMove = (moveEvent: PointerEvent) => {
                const active = dragState;
                if (!active) return;
                const delta = moveEvent.clientX - active.startX;
                const newWidth = Math.max(MIN_COLUMN_WIDTH, Math.round(active.startWidth + delta));
                active.currentWidth = newWidth;
                // Live-updates every row's cell at this column index (not
                // just the dragged one) so the whole column visibly
                // resizes together while dragging — the real commit below
                // is the source of truth, this is only DOM feedback.
                if (active.colIndex >= 0) {
                  active.tableEl.querySelectorAll(":scope > tbody > tr").forEach((tr) => {
                    const cell = tr.children[active.colIndex] as HTMLElement | undefined;
                    cell?.setAttribute("width", String(newWidth));
                  });
                }
              };

              const commit = () => {
                window.removeEventListener("pointermove", onPointerMove);
                window.removeEventListener("pointerup", commit);
                const finished = dragState;
                dragState = null;
                view.dom.style.removeProperty("cursor");
                if (finished) updateColumnWidth(view, finished.cellPos, finished.currentWidth);
              };

              window.addEventListener("pointermove", onPointerMove);
              window.addEventListener("pointerup", commit);
              return true;
            },
          },
        },
      }),
    ];
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
      ResizableTable.configure({ resizable: false }),
      TableRow,
      ResizableTableHeader,
      ResizableTableCell,
      ColumnResize,
    ],
    content: value,
    editable: !disabled,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class:
          "min-h-[--rte-min-h] px-3 py-2.5 text-sm text-foreground focus:outline-none [&_p]:mb-2 [&_p:last-child]:mb-0 [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_a]:text-primary [&_a]:underline [&_strong]:font-semibold [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_table]:my-2 [&_table]:border-collapse [&_table]:max-w-full [&_td]:border [&_td]:border-border [&_td]:p-1.5 [&_td]:align-top [&_th]:border [&_th]:border-border [&_th]:bg-muted [&_th]:p-1.5 [&_th]:text-left [&_th]:font-semibold [&_img]:mb-2 [&_img]:max-w-full [&_img]:rounded [&_img[data-upload-status=uploading]]:opacity-60 [&_img[data-upload-status=error]]:outline [&_img[data-upload-status=error]]:outline-2 [&_img[data-upload-status=error]]:outline-destructive",
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
