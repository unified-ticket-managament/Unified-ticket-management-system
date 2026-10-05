// Bulk Reply / Reply All / Forward are never one combined message and
// never auto-sent. The selection becomes an ordered queue and the user
// works through it ONE interaction at a time in the existing composer
// (the same hand-off the per-message menu uses), with the existing send
// confirmation, recipient validation and audit for each. Pure so the
// "each message independent, nothing merged" rule is unit-testable.

export type BulkComposeAction = "reply" | "replyAll" | "forward";

export interface BulkComposeQueue {
  action: BulkComposeAction;
  ids: readonly string[];
  index: number;
  // Selected rows the action does not apply to (reported, not dropped).
  skippedIds: readonly string[];
}

export function createComposeQueue(
  action: BulkComposeAction,
  eligibleIds: readonly string[],
  skippedIds: readonly string[] = []
): BulkComposeQueue | null {
  const ids = Array.from(new Set(eligibleIds));
  if (ids.length === 0) return null;
  return { action, ids, index: 0, skippedIds };
}

export function currentQueueId(queue: BulkComposeQueue): string {
  return queue.ids[queue.index];
}

// Moves to the next message; null when the queue is finished.
export function advanceQueue(queue: BulkComposeQueue): BulkComposeQueue | null {
  if (queue.index + 1 >= queue.ids.length) return null;
  return { ...queue, index: queue.index + 1 };
}

export function queueProgressLabel(queue: BulkComposeQueue): string {
  return `Message ${queue.index + 1} of ${queue.ids.length}`;
}

export function queueActionLabel(action: BulkComposeAction): string {
  return action === "reply"
    ? "Reply"
    : action === "replyAll"
      ? "Reply All"
      : "Forward";
}
