"use client";

import { useLayoutEffect, useRef, useState } from "react";

// Shared by every message-body renderer (Mail thread bubbles, the
// Interaction Details drawer/full page, and the ticket conversation
// feed) so "clamp to ~3 lines, only show a toggle if it actually
// overflows" isn't reimplemented at each call site. The caller applies
// `ref` and `clampClassName` directly onto its own message-body
// element (never a wrapper div) so line-clamp measures the real
// content, not an extra box around it.
export function useCollapsibleMessage<T extends HTMLElement = HTMLDivElement>(
  deps: unknown[]
) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const ref = useRef<T>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setIsOverflowing(el.scrollHeight - el.clientHeight > 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return {
    ref,
    isExpanded,
    isOverflowing,
    toggle: () => setIsExpanded((prev) => !prev),
    clampClassName: isExpanded ? "" : "line-clamp-3",
  };
}
