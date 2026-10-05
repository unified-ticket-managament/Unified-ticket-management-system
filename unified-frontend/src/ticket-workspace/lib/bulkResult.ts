// Turns POST /inbox/bulk-action's structured result into the toast the
// user reads. Reasons from the backend are already generic (they never
// name clients or tickets), so they are safe to show as-is.

export interface BulkItemResult {
  interaction_id: string;
  status: "success" | "failed" | "skipped";
  reason?: string | null;
  ticket_id?: string | null;
}

export interface BulkActionResult {
  requested: number;
  succeeded: number;
  failed: number;
  skipped?: number;
  results: BulkItemResult[];
}

export interface BulkSummary {
  message: string;
  tone: "success" | "info" | "error";
  // Ids that did not succeed (client-skipped + server-failed) — the
  // caller keeps exactly these selected so the user can retry or inspect.
  remainingIds: string[];
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

export function summarizeBulkResult(
  result: BulkActionResult,
  clientSkippedIds: readonly string[] = []
): BulkSummary {
  const failedIds = result.results
    .filter((r) => r.status !== "success")
    .map((r) => r.interaction_id);
  const skipped = clientSkippedIds.length + (result.skipped ?? 0);
  const notProcessed = result.failed + skipped;

  const parts: string[] = [];
  if (result.succeeded > 0) {
    parts.push(`${plural(result.succeeded, "action", "actions")} completed.`);
  }
  if (result.failed > 0) {
    parts.push(
      `${plural(result.failed, "message", "messages")} could not be processed.`
    );
  }
  if (clientSkippedIds.length > 0) {
    parts.push(
      `${plural(clientSkippedIds.length, "message was", "messages were")} not eligible and skipped.`
    );
  }
  if (parts.length === 0) parts.push("Nothing to do.");

  return {
    message: parts.join(" "),
    tone:
      notProcessed === 0 ? "success" : result.succeeded > 0 ? "info" : "error",
    remainingIds: [...clientSkippedIds, ...failedIds],
  };
}
