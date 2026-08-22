// useImagePasteUploads.ts
//
// Owns the "background upload + reconcile the doc" half of pasted-
// screenshot support (see lib/clipboardPaste.ts for the paste-
// detection half). RichTextEditor.tsx wires this hook's
// `handleImageFile` in as clipboardPaste's `onImageFile` callback,
// and exposes `hasPendingUploads` so a composer can block Send while
// an upload is still in flight rather than silently dropping content
// the user just pasted.

import { useCallback, useRef, useState } from "react";
import type { Editor } from "@tiptap/react";

export interface ImageUploadResult {
  attachmentId: string;
  contentId: string;
}

export type ImageUploader = (file: File) => Promise<ImageUploadResult>;

function dedupeKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function findImageNodeByLocalId(
  editor: Editor,
  localId: string
): { pos: number; attrs: Record<string, unknown> } | null {
  let found: { pos: number; attrs: Record<string, unknown> } | null = null;

  editor.state.doc.descendants((node, pos) => {
    if (found) return false;
    if (node.type.name === "image" && node.attrs["data-local-id"] === localId) {
      found = { pos, attrs: node.attrs };
      return false;
    }
    return true;
  });

  return found;
}

/**
 * `onImageUpload`, when supplied, is called once per pasted/dropped
 * image to actually store it (reusing whichever existing attachment
 * endpoint the composer is already configured with) and mint a
 * content_id. When omitted (a composer with no upload wiring yet),
 * pasted images still show their local preview but are immediately
 * marked as a permanent upload error, rather than hanging forever.
 */
export function useImagePasteUploads(editor: Editor | null, onImageUpload?: ImageUploader) {
  const [pendingCount, setPendingCount] = useState(0);
  const inFlightRef = useRef<Set<string>>(new Set());

  const handleImageFile = useCallback(
    (file: File, localId: string) => {
      const key = dedupeKey(file);
      // Defense in depth against the same File object somehow being
      // dispatched twice for one paste event — the real ordering/
      // dedupe guarantee already comes from clipboardPaste.ts calling
      // this exactly once per clipboard item, this just guards
      // against a future regression re-firing it.
      if (inFlightRef.current.has(key)) return;
      inFlightRef.current.add(key);

      const markNode = (attrs: Record<string, unknown>) => {
        if (!editor) return;
        const found = findImageNodeByLocalId(editor, localId);
        if (!found) return;
        editor
          .chain()
          .command(({ tr }) => {
            tr.setNodeMarkup(found.pos, undefined, { ...found.attrs, ...attrs });
            return true;
          })
          .run();
      };

      if (!onImageUpload) {
        markNode({ "data-upload-status": "error" });
        inFlightRef.current.delete(key);
        return;
      }

      setPendingCount((count) => count + 1);

      onImageUpload(file)
        .then((result) => {
          markNode({
            "data-attachment-id": result.attachmentId,
            "data-content-id": result.contentId,
            "data-upload-status": "done",
          });
        })
        .catch(() => {
          markNode({ "data-upload-status": "error" });
        })
        .finally(() => {
          inFlightRef.current.delete(key);
          setPendingCount((count) => Math.max(0, count - 1));
        });
    },
    [editor, onImageUpload]
  );

  return {
    handleImageFile,
    hasPendingUploads: pendingCount > 0,
  };
}
