// Multi-select state for the Mail list. Pure on purpose (no React, no
// path aliases) so the rules — checkbox toggle, Ctrl/Cmd+Click, select
// all visible, right-click targeting — are unit-testable with
// `node --test`. Selection is always a Set of interaction ids, so a
// duplicate id can never be selected twice.
//
// Right-click rule (desktop-mail convention, documented in one place):
//   - right-clicking a SELECTED row keeps the whole selection and opens
//     the bulk menu for it;
//   - right-clicking an UNSELECTED row replaces the selection with just
//     that row and opens the single-message menu.

export type MailPlatform = "mac" | "other";

export type SelectedIds = ReadonlySet<string>;

export const EMPTY_SELECTION: SelectedIds = new Set<string>();

export function detectPlatform(
  nav?: { platform?: string; userAgent?: string } | null
): MailPlatform {
  const source =
    nav ?? (typeof navigator !== "undefined" ? (navigator as Navigator) : null);
  const text = `${source?.platform ?? ""} ${source?.userAgent ?? ""}`;
  return /mac|iphone|ipad|ipod/i.test(text) ? "mac" : "other";
}

// Windows/Linux → Ctrl, macOS → Cmd. Ctrl+Click on macOS is the
// platform's right-click, so it is deliberately NOT a multi-select
// modifier there.
export function isMultiSelectModifier(
  event: { ctrlKey?: boolean; metaKey?: boolean },
  platform: MailPlatform
): boolean {
  return platform === "mac" ? Boolean(event.metaKey) : Boolean(event.ctrlKey);
}

export function toggleSelected(selection: SelectedIds, id: string): Set<string> {
  const next = new Set(selection);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

export function selectOnly(id: string): Set<string> {
  return new Set([id]);
}

export function selectAllVisible(visibleIds: readonly string[]): Set<string> {
  return new Set(visibleIds);
}

export function clearSelection(): Set<string> {
  return new Set();
}

export function areAllSelected(
  selection: SelectedIds,
  visibleIds: readonly string[]
): boolean {
  return visibleIds.length > 0 && visibleIds.every((id) => selection.has(id));
}

// Drops ids that are no longer in the loaded list (refetch, deletion).
// Returns the SAME set when nothing changed so callers can skip a render.
export function pruneSelection(
  selection: SelectedIds,
  loadedIds: readonly string[]
): SelectedIds {
  if (selection.size === 0) return selection;
  const loaded = new Set(loadedIds);
  let changed = false;
  const next = new Set<string>();
  for (const id of selection) {
    if (loaded.has(id)) next.add(id);
    else changed = true;
  }
  return changed ? next : selection;
}

export type ContextMenuKind = "single" | "bulk";

export function resolveContextTarget(
  selection: SelectedIds,
  rightClickedId: string
): { selection: SelectedIds; kind: ContextMenuKind } {
  if (selection.has(rightClickedId)) {
    // A lone selected row still gets the normal single-message menu;
    // "bulk" only means more than one message is targeted.
    return {
      selection,
      kind: selection.size > 1 ? "bulk" : "single",
    };
  }
  return { selection: selectOnly(rightClickedId), kind: "single" };
}

// What a row click should do given the held modifier. Ctrl/Cmd+Click
// toggles and must NOT open the message (opening would change the
// reading pane and, upstream, mark the thread read).
export type RowClickIntent = "toggle" | "open";

export function resolveRowClick(
  event: { ctrlKey?: boolean; metaKey?: boolean },
  platform: MailPlatform
): RowClickIntent {
  return isMultiSelectModifier(event, platform) ? "toggle" : "open";
}

export function selectionLabel(count: number): string {
  return `${count} selected`;
}
