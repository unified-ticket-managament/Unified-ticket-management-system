// crypto.randomUUID() is only defined in a secure context (HTTPS, or the
// browser's localhost exception) — it's undefined when this app is served
// over plain HTTP from a non-localhost origin. Falls back to a
// timestamp+random string, which is fine here: this key only needs to be
// unique per Send click, not cryptographically random (see
// dispatch_idempotency_key on the backend — a plain String(255), no UUID
// format required). Same guard pattern as clipboardPaste.ts's
// generateLocalId().
export function generateIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `idem-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
