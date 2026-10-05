"use client";

import { useEffect, useRef, useState } from "react";
import { useEditorState, type Editor } from "@tiptap/react";
import {
  Baseline,
  Bold,
  ChevronDown,
  Highlighter,
  Italic,
  Link as LinkIcon,
  List,
  ListIndentDecrease,
  ListIndentIncrease,
  ListOrdered,
  Quote,
  Redo,
  RemoveFormatting,
  Strikethrough,
  TextAlignCenter,
  TextAlignEnd,
  TextAlignJustify,
  TextAlignStart,
  Underline,
  Undo,
  Unlink,
} from "lucide-react";

import { cn } from "@/lib/utils";
import {
  EMAIL_DEFAULT_FONT_FAMILY,
  EMAIL_DEFAULT_FONT_SIZE,
  FONT_FAMILY_OPTIONS,
  FONT_SIZE_OPTIONS,
  HIGHLIGHT_PALETTE,
  TEXT_COLOR_PALETTE,
  findFontFamilyOption,
  fontSizeToPoints,
  normalizeLinkUrl,
} from "@tw/lib/emailHtml";

type Alignment = "left" | "center" | "right" | "justify";

// Re-evaluated on every editor transaction, INCLUDING selection-only
// ones (TipTap v3's useEditor no longer re-renders on transactions by
// default) — this is what keeps the toolbar's active/disabled states
// tracking the cursor instead of lagging until the next keystroke.
// getAttributes("textStyle") also reads stored marks, so a font/size/
// color picked with an empty selection shows immediately, before any
// text is typed with it.
function selectToolbarState({ editor }: { editor: Editor | null }) {
  if (!editor) return null;
  const textStyle = editor.getAttributes("textStyle");
  const alignment: Alignment =
    (["center", "right", "justify"] as const).find((value) => editor.isActive({ textAlign: value })) ?? "left";
  return {
    bold: editor.isActive("bold"),
    italic: editor.isActive("italic"),
    underline: editor.isActive("underline"),
    strike: editor.isActive("strike"),
    bulletList: editor.isActive("bulletList"),
    orderedList: editor.isActive("orderedList"),
    blockquote: editor.isActive("blockquote"),
    link: editor.isActive("link"),
    linkHref: (editor.getAttributes("link").href as string | undefined) ?? "",
    alignment,
    fontFamily: (textStyle.fontFamily as string | undefined) ?? null,
    fontSize: (textStyle.fontSize as string | undefined) ?? null,
    color: (textStyle.color as string | undefined) ?? null,
    backgroundColor: (textStyle.backgroundColor as string | undefined) ?? null,
    canUndo: editor.can().undo(),
    canRedo: editor.can().redo(),
    canIndent: editor.can().indent(),
    canOutdent: editor.can().outdent(),
    editable: editor.isEditable,
  };
}

// Toolbar controls must never steal the editor's DOM focus/selection on
// mousedown — otherwise a click on Bold with a word selected would
// collapse the selection before the command ever ran.
const keepEditorFocus = (event: React.MouseEvent) => event.preventDefault();

interface ToolbarButtonProps {
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  label: string;
  shortcut?: string;
  children: React.ReactNode;
}

function ToolbarButton({ onClick, active, disabled, label, shortcut, children }: ToolbarButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active ?? undefined}
      title={shortcut ? `${label} (${shortcut})` : label}
      disabled={disabled}
      onMouseDown={keepEditorFocus}
      onClick={onClick}
      className={cn(
        "flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40",
        active && "bg-primary/15 text-primary hover:bg-primary/15 hover:text-primary"
      )}
    >
      {children}
    </button>
  );
}

function Divider() {
  return <div className="mx-1 h-4 w-px shrink-0 bg-border" aria-hidden />;
}

function ToolbarGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div role="group" aria-label={label} className="flex items-center gap-0.5">
      {children}
    </div>
  );
}

// Lightweight anchored popover (no focus trap) — a Radix menu would
// close the moment the native <input type="color"> dialog takes focus,
// unmounting the very input that is reporting the chosen color.
function ToolbarPopover({
  label,
  trigger,
  disabled,
  children,
}: {
  label: string;
  trigger: React.ReactNode;
  disabled?: boolean;
  children: (close: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-label={label}
        title={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={disabled}
        onMouseDown={keepEditorFocus}
        onClick={() => setOpen((value) => !value)}
        className="flex h-7 shrink-0 items-center gap-0.5 rounded-md px-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
      >
        {trigger}
        <ChevronDown className="h-3 w-3" />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label={label}
          className="absolute left-0 top-full z-50 mt-1 rounded-md border border-border bg-popover p-2 text-popover-foreground shadow-md"
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

function ColorPalette({
  label,
  colors,
  defaultLabel,
  onPick,
  onReset,
  close,
}: {
  label: string;
  colors: { label: string; value: string }[];
  defaultLabel: string;
  onPick: (color: string) => void;
  onReset: () => void;
  close: () => void;
}) {
  return (
    <div className="w-44 space-y-2">
      <button
        type="button"
        onMouseDown={keepEditorFocus}
        onClick={() => {
          onReset();
          close();
        }}
        className="w-full rounded px-2 py-1 text-left text-xs hover:bg-muted"
      >
        {defaultLabel}
      </button>
      <div className="grid grid-cols-7 gap-1">
        {colors.map((color) => (
          <button
            key={color.value}
            type="button"
            aria-label={`${label}: ${color.label}`}
            title={color.label}
            onMouseDown={keepEditorFocus}
            onClick={() => {
              onPick(color.value);
              close();
            }}
            className="h-5 w-5 rounded border border-border"
            style={{ backgroundColor: color.value }}
          />
        ))}
      </div>
      <label className="flex items-center justify-between gap-2 px-1 text-xs">
        Custom…
        <input
          type="color"
          aria-label={`${label}: custom`}
          className="h-6 w-10 cursor-pointer border-0 bg-transparent p-0"
          onChange={(event) => onPick(event.target.value)}
        />
      </label>
    </div>
  );
}

function LinkEditor({ editor, href, close }: { editor: Editor; href: string; close: () => void }) {
  const [value, setValue] = useState(href || "");
  const [error, setError] = useState<string | null>(null);

  const apply = () => {
    const url = normalizeLinkUrl(value);
    if (!url) {
      setError("Enter a valid http(s) web address or email address.");
      return;
    }
    const chain = editor.chain().focus();
    if (editor.state.selection.empty && !editor.isActive("link")) {
      // Nothing selected — insert the address itself as the link text.
      chain
        .insertContent({ type: "text", text: value.trim(), marks: [{ type: "link", attrs: { href: url } }] })
        .run();
    } else {
      chain.extendMarkRange("link").setLink({ href: url }).run();
    }
    close();
  };

  return (
    <form
      className="flex w-64 flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        apply();
      }}
    >
      <input
        autoFocus
        type="text"
        aria-label="Link URL"
        placeholder="https://example.com"
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          setError(null);
        }}
        className="h-8 rounded-md border border-input bg-background px-2 text-sm"
      />
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        {href && (
          <button
            type="button"
            onClick={() => {
              editor.chain().focus().extendMarkRange("link").unsetLink().run();
              close();
            }}
            className="rounded-md px-2 py-1 text-xs hover:bg-muted"
          >
            Remove link
          </button>
        )}
        <button type="submit" className="rounded-md bg-primary px-2 py-1 text-xs text-primary-foreground">
          Apply
        </button>
      </div>
    </form>
  );
}

const selectClassName =
  "h-7 shrink-0 rounded-md border border-input bg-background px-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-40";

export function EmailEditorToolbar({ editor }: { editor: Editor | null }) {
  const state = useEditorState({ editor, selector: selectToolbarState });
  if (!editor || !state) return null;

  const disabled = !state.editable;
  const fontOption = findFontFamilyOption(state.fontFamily);
  const fontValue = fontOption?.value ?? (state.fontFamily ? "__custom" : EMAIL_DEFAULT_FONT_FAMILY);
  const sizeValue = fontSizeToPoints(state.fontSize) ?? fontSizeToPoints(EMAIL_DEFAULT_FONT_SIZE) ?? "11";

  return (
    <div
      role="toolbar"
      aria-label="Formatting"
      className="flex flex-wrap items-center gap-x-0.5 gap-y-1 border-b border-border px-2 py-1.5"
    >
      <ToolbarGroup label="Text">
        <select
          aria-label="Font"
          title="Font"
          disabled={disabled}
          value={fontValue}
          onChange={(event) => {
            const value = event.target.value;
            // The default font is never written explicitly — it comes
            // from the email's own wrapper (see emailHtml.ts).
            if (value === EMAIL_DEFAULT_FONT_FAMILY) editor.chain().focus().unsetFontFamily().run();
            else editor.chain().focus().setFontFamily(value).run();
          }}
          className={cn(selectClassName, "w-[7.5rem]")}
        >
          {state.fontFamily && !fontOption && (
            <option value="__custom" disabled>
              {state.fontFamily.split(",")[0].replace(/['"]/g, "")}
            </option>
          )}
          {FONT_FAMILY_OPTIONS.map((option) => (
            <option key={option.label} value={option.value} style={{ fontFamily: option.value }}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Font size"
          title="Font size"
          disabled={disabled}
          value={FONT_SIZE_OPTIONS.includes(sizeValue) ? sizeValue : "__custom"}
          onChange={(event) => {
            const size = `${event.target.value}pt`;
            if (size === EMAIL_DEFAULT_FONT_SIZE) editor.chain().focus().unsetFontSize().run();
            else editor.chain().focus().setFontSize(size).run();
          }}
          className={cn(selectClassName, "w-14")}
        >
          {!FONT_SIZE_OPTIONS.includes(sizeValue) && (
            <option value="__custom" disabled>
              {sizeValue}
            </option>
          )}
          {FONT_SIZE_OPTIONS.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </ToolbarGroup>
      <Divider />
      <ToolbarGroup label="Character formatting">
        <ToolbarButton
          label="Bold"
          shortcut="Ctrl+B"
          active={state.bold}
          disabled={disabled}
          onClick={() => editor.chain().focus().toggleBold().run()}
        >
          <Bold className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="Italic"
          shortcut="Ctrl+I"
          active={state.italic}
          disabled={disabled}
          onClick={() => editor.chain().focus().toggleItalic().run()}
        >
          <Italic className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="Underline"
          shortcut="Ctrl+U"
          active={state.underline}
          disabled={disabled}
          onClick={() => editor.chain().focus().toggleUnderline().run()}
        >
          <Underline className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="Strikethrough"
          shortcut="Ctrl+Shift+S"
          active={state.strike}
          disabled={disabled}
          onClick={() => editor.chain().focus().toggleStrike().run()}
        >
          <Strikethrough className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarPopover
          label="Font color"
          disabled={disabled}
          trigger={
            <span className="flex flex-col items-center">
              <Baseline className="h-3.5 w-3.5" />
              <span
                data-testid="font-color-indicator"
                className="-mt-0.5 h-[3px] w-3.5 rounded-sm"
                style={{ backgroundColor: state.color ?? "#000000" }}
              />
            </span>
          }
        >
          {(close) => (
            <ColorPalette
              label="Font color"
              colors={TEXT_COLOR_PALETTE}
              defaultLabel="Automatic"
              onPick={(color) => editor.chain().focus().setColor(color).run()}
              onReset={() => editor.chain().focus().unsetColor().run()}
              close={close}
            />
          )}
        </ToolbarPopover>
        <ToolbarPopover
          label="Highlight color"
          disabled={disabled}
          trigger={
            <span className="flex flex-col items-center">
              <Highlighter className="h-3.5 w-3.5" />
              <span
                className="-mt-0.5 h-[3px] w-3.5 rounded-sm border border-border/60"
                style={{ backgroundColor: state.backgroundColor ?? "transparent" }}
              />
            </span>
          }
        >
          {(close) => (
            <ColorPalette
              label="Highlight color"
              colors={HIGHLIGHT_PALETTE}
              defaultLabel="No highlight"
              onPick={(color) => editor.chain().focus().setBackgroundColor(color).run()}
              onReset={() => editor.chain().focus().unsetBackgroundColor().run()}
              close={close}
            />
          )}
        </ToolbarPopover>
        <ToolbarButton
          label="Clear formatting"
          disabled={disabled}
          onClick={() =>
            // Character formatting only (links and lists are content,
            // not formatting) plus paragraph alignment/indent.
            editor
              .chain()
              .focus()
              .unsetMark("bold")
              .unsetMark("italic")
              .unsetMark("underline")
              .unsetMark("strike")
              .unsetMark("code")
              .unsetMark("textStyle")
              .unsetTextAlign()
              .updateAttributes("paragraph", { indent: 0 })
              .run()
          }
        >
          <RemoveFormatting className="h-3.5 w-3.5" />
        </ToolbarButton>
      </ToolbarGroup>
      <Divider />
      <ToolbarGroup label="Paragraph">
        <ToolbarButton
          label="Bulleted list"
          active={state.bulletList}
          disabled={disabled}
          onClick={() => editor.chain().focus().toggleBulletList().run()}
        >
          <List className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="Numbered list"
          active={state.orderedList}
          disabled={disabled}
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
        >
          <ListOrdered className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="Decrease indent"
          shortcut="Ctrl+["
          disabled={disabled || !state.canOutdent}
          onClick={() => editor.chain().focus().outdent().run()}
        >
          <ListIndentDecrease className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="Increase indent"
          shortcut="Ctrl+]"
          disabled={disabled || !state.canIndent}
          onClick={() => editor.chain().focus().indent().run()}
        >
          <ListIndentIncrease className="h-3.5 w-3.5" />
        </ToolbarButton>
        {(
          [
            ["left", "Align left", "Ctrl+Shift+L", TextAlignStart],
            ["center", "Center", "Ctrl+Shift+E", TextAlignCenter],
            ["right", "Align right", "Ctrl+Shift+R", TextAlignEnd],
            ["justify", "Justify", "Ctrl+Shift+J", TextAlignJustify],
          ] as const
        ).map(([alignment, label, shortcut, Icon]) => (
          <ToolbarButton
            key={alignment}
            label={label}
            shortcut={shortcut}
            active={state.alignment === alignment}
            disabled={disabled}
            onClick={() =>
              alignment === "left"
                ? editor.chain().focus().unsetTextAlign().run()
                : editor.chain().focus().setTextAlign(alignment).run()
            }
          >
            <Icon className="h-3.5 w-3.5" />
          </ToolbarButton>
        ))}
        <ToolbarButton
          label="Quote"
          active={state.blockquote}
          disabled={disabled}
          onClick={() => editor.chain().focus().toggleBlockquote().run()}
        >
          <Quote className="h-3.5 w-3.5" />
        </ToolbarButton>
      </ToolbarGroup>
      <Divider />
      <ToolbarGroup label="Insert">
        <ToolbarPopover
          label={state.link ? "Edit link" : "Insert link"}
          disabled={disabled}
          trigger={<LinkIcon className={cn("h-3.5 w-3.5", state.link && "text-primary")} />}
        >
          {(close) => <LinkEditor editor={editor} href={state.linkHref} close={close} />}
        </ToolbarPopover>
        {state.link && (
          <ToolbarButton
            label="Remove link"
            disabled={disabled}
            onClick={() => editor.chain().focus().extendMarkRange("link").unsetLink().run()}
          >
            <Unlink className="h-3.5 w-3.5" />
          </ToolbarButton>
        )}
      </ToolbarGroup>
      <Divider />
      <ToolbarGroup label="Edit">
        <ToolbarButton
          label="Undo"
          shortcut="Ctrl+Z"
          disabled={disabled || !state.canUndo}
          onClick={() => editor.chain().focus().undo().run()}
        >
          <Undo className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="Redo"
          shortcut="Ctrl+Y"
          disabled={disabled || !state.canRedo}
          onClick={() => editor.chain().focus().redo().run()}
        >
          <Redo className="h-3.5 w-3.5" />
        </ToolbarButton>
      </ToolbarGroup>
    </div>
  );
}
