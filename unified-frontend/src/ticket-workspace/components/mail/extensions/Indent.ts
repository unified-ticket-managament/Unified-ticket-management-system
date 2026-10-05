import { type CommandProps, Extension } from "@tiptap/core";

import { INDENT_STEP_PX, MAX_INDENT_LEVEL } from "@tw/lib/emailHtml";

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    indent: {
      /** Increase indent: nests a list item, or steps a paragraph's left margin. */
      indent: () => ReturnType;
      /** Decrease indent: un-nests a list item, or steps a paragraph's left margin back. */
      outdent: () => ReturnType;
    };
  }
}

// margin-left (px/pt/in/em, as written by this extension or pasted
// from Word/Outlook) -> whole indent levels.
export function parseIndentLevel(marginLeft: string | null | undefined): number {
  if (!marginLeft) return 0;
  const match = marginLeft.trim().match(/^(\d*\.?\d+)(px|pt|in|em)?$/i);
  if (!match) return 0;
  const factor: Record<string, number> = { px: 1, pt: 4 / 3, in: 96, em: 16 };
  const px = Number(match[1]) * factor[(match[2] ?? "px").toLowerCase()];
  return Math.min(MAX_INDENT_LEVEL, Math.max(0, Math.round(px / INDENT_STEP_PX)));
}

/**
 * Outlook-style Increase/Decrease Indent. Inside a list it is real list
 * nesting (sink/lift the list item — proper nested <ul>/<ol>, never
 * spaces); elsewhere it is a block-level `indent` attribute rendered as
 * an inline `margin-left` in INDENT_STEP_PX steps — the representation
 * every email client honors (backend html_sanitizer.py allows
 * margin-left in outbound style).
 */
export const Indent = Extension.create<{ types: string[] }>({
  name: "indent",

  addOptions() {
    return { types: ["paragraph"] };
  },

  addGlobalAttributes() {
    return [
      {
        types: this.options.types,
        attributes: {
          indent: {
            default: 0,
            parseHTML: (element) => parseIndentLevel(element.style.marginLeft),
            renderHTML: (attributes) =>
              attributes.indent > 0 ? { style: `margin-left: ${attributes.indent * INDENT_STEP_PX}px` } : {},
          },
        },
      },
    ];
  },

  addCommands() {
    const types = this.options.types;
    // Mutates the command's shared `tr` (TipTap's command manager does
    // the dispatching); returns whether anything would change, so
    // editor.can().outdent() is false at indent 0.
    const step = (delta: number, { state, tr, dispatch }: CommandProps) => {
      const { from, to } = state.selection;
      let changed = false;
      state.doc.nodesBetween(from, to, (node, pos, parent) => {
        if (!types.includes(node.type.name)) return true;
        // List-item paragraphs are indented by nesting the item
        // itself, never by a margin on the paragraph inside it.
        if (parent?.type.name === "listItem") return false;
        const current = Number(node.attrs.indent) || 0;
        const next = Math.min(MAX_INDENT_LEVEL, Math.max(0, current + delta));
        if (next !== current) {
          if (dispatch) tr.setNodeMarkup(pos, undefined, { ...node.attrs, indent: next });
          changed = true;
        }
        return false;
      });
      return changed;
    };

    return {
      indent: () => (props) =>
        props.editor.isActive("listItem") ? props.commands.sinkListItem("listItem") : step(1, props),
      outdent: () => (props) =>
        props.editor.isActive("listItem") ? props.commands.liftListItem("listItem") : step(-1, props),
    };
  },

  addKeyboardShortcuts() {
    return {
      "Mod-]": () => this.editor.commands.indent(),
      "Mod-[": () => this.editor.commands.outdent(),
    };
  },
});
