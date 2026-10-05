import { Node, mergeAttributes } from "@tiptap/core";

import { SIGNATURE_MARKER_ATTR } from "@tw/lib/signatures";

// The composer's managed signature block — `<div data-utms-signature=
// "<id>">…</div>` (see lib/signatures.ts). Without a node of its own,
// ProseMirror would drop the wrapper <div> on the very first parse
// (the schema has no generic div), and the composer could no longer
// tell which content is the signature when the user switches to
// another one. Its content is ordinary blocks, so the signature stays
// fully editable in place. The marker attribute never reaches a
// recipient — the backend's outbound sanitizer strips every data-*
// attribute, leaving a plain <div>.
export const SignatureBlock = Node.create({
  name: "signatureBlock",
  group: "block",
  content: "block+",
  defining: true,

  addAttributes() {
    return {
      signatureId: {
        default: "",
        parseHTML: (element) => element.getAttribute(SIGNATURE_MARKER_ATTR) ?? "",
        renderHTML: (attributes) => ({ [SIGNATURE_MARKER_ATTR]: attributes.signatureId ?? "" }),
      },
    };
  },

  parseHTML() {
    return [{ tag: `div[${SIGNATURE_MARKER_ATTR}]` }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes), 0];
  },
});
