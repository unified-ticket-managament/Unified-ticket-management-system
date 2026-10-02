import { useCallback, useRef, useState, type DragEvent, type ClipboardEvent } from "react";

import { classifyDrop, classifyPaste, isFileDrag, isImageOnlyDrag } from "@tw/lib/attachmentIntake";

// The rich-text editor (TipTap/ProseMirror) keeps its own paste and
// drop handling for images — see lib/clipboardPaste.ts, which this hook
// deliberately does not replace. The drop/paste handlers below only
// decide what to do with *files*, and defer to the editor for images
// that land inside it.
const EDITOR_SELECTOR = ".ProseMirror";
// FileDropzone/AttachmentUploader mark their own drop box with this, so
// a file dropped straight onto it is handled once, by that box.
const DROPZONE_SELECTOR = "[data-attachment-dropzone]";

function closestMatch(target: EventTarget | null, selector: string): boolean {
  return target instanceof Element && target.closest(selector) !== null;
}

interface UseAttachmentIntakeOptions {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}

// Drag-and-drop + paste intake for a whole composer. It only produces
// File[]; validation, dedupe and upload stay in the caller's existing
// attachment pipeline (the same one the Browse button feeds).
export function useAttachmentIntake({ onFiles, disabled = false }: UseAttachmentIntakeOptions) {
  const [isDragging, setIsDragging] = useState(false);
  // dragenter/dragleave fire for every child element crossed, so a plain
  // boolean flickers; counting enters against leaves doesn't.
  const dragDepth = useRef(0);

  const resetDrag = useCallback(() => {
    dragDepth.current = 0;
    setIsDragging(false);
  }, []);

  const onDragEnter = (event: DragEvent<HTMLElement>) => {
    if (disabled || !isFileDrag(event.dataTransfer)) return;
    dragDepth.current += 1;
    // Images dragged over the editor become inline images, not
    // attachments — don't promise "Release to attach" there.
    const editorHandlesIt = closestMatch(event.target, EDITOR_SELECTOR) && isImageOnlyDrag(event.dataTransfer);
    setIsDragging(!editorHandlesIt);
  };

  const onDragOver = (event: DragEvent<HTMLElement>) => {
    if (!isFileDrag(event.dataTransfer)) return;
    // Without this the browser refuses the drop and, worse, opens the file.
    event.preventDefault();
  };

  const onDragLeave = (event: DragEvent<HTMLElement>) => {
    if (!isFileDrag(event.dataTransfer)) return;
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setIsDragging(false);
  };

  const onDropCapture = (event: DragEvent<HTMLElement>) => {
    resetDrag();
    if (!isFileDrag(event.dataTransfer)) return;

    // A disabled composer must still swallow the drop: otherwise the
    // browser navigates to the dropped file and the draft is lost.
    if (disabled) {
      event.preventDefault();
      return;
    }
    if (closestMatch(event.target, DROPZONE_SELECTOR)) return;

    const { attach, consumed } = classifyDrop(event.dataTransfer, closestMatch(event.target, EDITOR_SELECTOR));
    if (consumed) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (attach.length > 0) onFiles(attach);
  };

  const onPasteCapture = (event: ClipboardEvent<HTMLElement>) => {
    if (disabled) return;

    const { attach, consumed } = classifyPaste(event.clipboardData, closestMatch(event.target, EDITOR_SELECTOR));
    if (consumed) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (attach.length > 0) onFiles(attach);
  };

  return {
    isDragging: isDragging && !disabled,
    containerProps: { onDragEnter, onDragOver, onDragLeave, onDropCapture, onPasteCapture },
  };
}
