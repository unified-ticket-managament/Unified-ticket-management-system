"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { useSettingsStore } from "@/store/settings-store";

// Outlook-style three-panel Mail workspace shell: Mail Folders | Message
// List | Message Details, touching directly with a single draggable
// divider line between each pair — no card gaps between them, since the
// whole thing shares one outer card (border/rounded/shadow) instead of
// each panel having its own. Mail-specific (components/mail/ only, used
// solely by InboxPage.tsx) — no other page renders this.
const FOLDER_MIN_WIDTH = 180;
const LIST_MIN_WIDTH = 240;
const DETAIL_MIN_WIDTH = 340;
// Required default ratio: folder : list : detail = 1 : 1 : 3.
const RATIO_TOTAL = 5;

type DragTarget = "folder" | "list";

interface DragState {
  target: DragTarget;
  startX: number;
  startFolderWidth: number;
  startListWidth: number;
  containerWidth: number;
}

interface MailWorkspaceLayoutProps {
  folderPanel: ReactNode;
  // Either provide listPanel+detailPanel (the normal three-panel
  // list/reading-pane split) or wideContent (e.g. Rules — not a mail
  // list/detail pair at all) — wideContent, when present, replaces
  // both and spans the space they'd otherwise occupy; the folder
  // panel and its own divider are unaffected either way.
  listPanel?: ReactNode;
  detailPanel?: ReactNode;
  wideContent?: ReactNode;
}

export function MailWorkspaceLayout({
  folderPanel,
  listPanel,
  detailPanel,
  wideContent,
}: MailWorkspaceLayoutProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [folderWidth, setFolderWidth] = useState<number | null>(null);
  const [listWidth, setListWidth] = useState<number | null>(null);
  const [activeDrag, setActiveDrag] = useState<DragTarget | null>(null);
  const dragRef = useRef<DragState | null>(null);

  // Only the list|detail divider persists — the folder|list divider
  // deliberately stays non-persisted, independent of both this and the
  // main app sidebar's own persisted width.
  const persistedListWidth = useSettingsStore((s) => s.mailMessageListWidth);
  const setPersistedListWidth = useSettingsStore((s) => s.setMailMessageListWidth);
  // Mirrors the live "list" drag value so endDrag (a stable callback,
  // can't safely close over fresh listWidth state) can read the final
  // value on pointerup.
  const listWidthRef = useRef<number | null>(null);

  // Seed default pixel widths, in the required 1:1:3 ratio, from the
  // workspace's own measured width the first time it's known — this
  // scales sensibly across monitor sizes instead of a hardcoded guess.
  // The list width additionally restores a persisted value (if the
  // user ever dragged it before), clamped against the current
  // measurement — kept in this one effect, rather than a second effect
  // keyed off persistedListWidth, so a restored width renders on the
  // very first paint instead of flashing the ratio default first.
  useEffect(() => {
    if (folderWidth !== null || listWidth !== null) return;
    const total = containerRef.current?.getBoundingClientRect().width;
    if (!total) return;
    const unit = total / RATIO_TOTAL;
    const seededFolderWidth = Math.max(FOLDER_MIN_WIDTH, Math.round(unit));
    setFolderWidth(seededFolderWidth);
    if (persistedListWidth != null) {
      const maxList = Math.max(LIST_MIN_WIDTH, total - seededFolderWidth - DETAIL_MIN_WIDTH);
      setListWidth(Math.min(Math.max(persistedListWidth, LIST_MIN_WIDTH), maxList));
    } else {
      setListWidth(Math.max(LIST_MIN_WIDTH, Math.round(unit)));
    }
  }, [folderWidth, listWidth, persistedListWidth]);

  // `cleanupRef` holds the exact remove-listener closure a given
  // beginDrag() call installed, so endDrag can tear it down without
  // ever needing to reference its own name (a `const foo =
  // useCallback(() => { ...foo... })` can't safely close over its own
  // not-yet-assigned binding) — every ref access below stays inside a
  // useCallback/useEffect, never read from render body directly.
  const cleanupRef = useRef<() => void>(() => {});

  const handlePointerMove = useCallback((event: PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    const deltaX = event.clientX - drag.startX;

    if (drag.target === "folder") {
      const maxFolder = Math.max(FOLDER_MIN_WIDTH, drag.containerWidth - drag.startListWidth - DETAIL_MIN_WIDTH);
      const next = Math.min(Math.max(drag.startFolderWidth + deltaX, FOLDER_MIN_WIDTH), maxFolder);
      setFolderWidth(next);
    } else {
      const maxList = Math.max(LIST_MIN_WIDTH, drag.containerWidth - drag.startFolderWidth - DETAIL_MIN_WIDTH);
      const next = Math.min(Math.max(drag.startListWidth + deltaX, LIST_MIN_WIDTH), maxList);
      listWidthRef.current = next;
      setListWidth(next);
    }
  }, []);

  const endDrag = useCallback(() => {
    const wasListDrag = dragRef.current?.target === "list";
    dragRef.current = null;
    setActiveDrag(null);
    cleanupRef.current();
    cleanupRef.current = () => {};
    if (wasListDrag && listWidthRef.current != null) {
      setPersistedListWidth(listWidthRef.current);
    }
    listWidthRef.current = null;
  }, [setPersistedListWidth]);

  const beginDrag = useCallback(
    (target: DragTarget) => (event: React.PointerEvent) => {
      const container = containerRef.current;
      if (!container || folderWidth == null || listWidth == null) return;
      event.preventDefault();
      dragRef.current = {
        target,
        startX: event.clientX,
        startFolderWidth: folderWidth,
        startListWidth: listWidth,
        containerWidth: container.getBoundingClientRect().width,
      };
      setActiveDrag(target);
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", endDrag);
      cleanupRef.current = () => {
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", endDrag);
      };
    },
    [folderWidth, listWidth, handlePointerMove, endDrag]
  );

  // Re-clamp both widths if the container shrinks enough that the
  // detail panel would otherwise be squeezed below its own minimum —
  // keeps every panel usable across a window resize, not just at drag
  // time.
  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const total = entries[0]?.contentRect.width;
      if (!total) return;
      setFolderWidth((current) =>
        current == null ? current : Math.min(current, Math.max(FOLDER_MIN_WIDTH, total - LIST_MIN_WIDTH - DETAIL_MIN_WIDTH))
      );
      setListWidth((current) =>
        current == null ? current : Math.min(current, Math.max(LIST_MIN_WIDTH, total - FOLDER_MIN_WIDTH - DETAIL_MIN_WIDTH))
      );
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // Safety net for unmounting mid-drag (e.g. navigating away from Mail
  // while a divider is still being dragged) — removes whatever
  // pointermove/pointerup listeners the in-flight drag attached, so
  // they don't linger on `window` past this component's lifetime.
  // `endDrag` is a stable (empty-deps) callback, so this only re-runs
  // if it's ever recreated, not on every render.
  useEffect(() => () => endDrag(), [endDrag]);

  const isWide = wideContent !== undefined;

  return (
    <div
      ref={containerRef}
      className="flex h-[calc(100vh-7rem)] min-w-0 overflow-hidden rounded-xl border border-border bg-card shadow-card"
    >
      <div className="h-full min-w-0 overflow-hidden" style={{ width: folderWidth ?? undefined, flex: folderWidth == null ? "1 1 0%" : "0 0 auto" }}>
        {folderPanel}
      </div>

      <Divider active={activeDrag === "folder"} onPointerDown={beginDrag("folder")} />

      {isWide ? (
        <div className="h-full min-w-0 flex-1 overflow-y-auto">{wideContent}</div>
      ) : (
        <>
          <div
            className="h-full min-w-0 overflow-hidden"
            style={{ width: listWidth ?? undefined, flex: listWidth == null ? "1 1 0%" : "0 0 auto" }}
          >
            {listPanel}
          </div>

          <Divider active={activeDrag === "list"} onPointerDown={beginDrag("list")} />

          <div className="h-full min-w-0 flex-1 overflow-y-auto" style={{ minWidth: DETAIL_MIN_WIDTH }}>
            {detailPanel}
          </div>
        </>
      )}
    </div>
  );
}

function Divider({
  active,
  onPointerDown,
}: {
  active: boolean;
  onPointerDown: (event: React.PointerEvent) => void;
}) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      onPointerDown={onPointerDown}
      className={cn(
        "relative z-10 w-1 flex-none cursor-col-resize touch-none select-none",
        "after:absolute after:inset-y-0 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-border after:transition-colors",
        "hover:after:bg-primary/50",
        active && "after:bg-primary/60"
      )}
    />
  );
}
