// Synchronous fallback used only until WorkflowContext's initial
// GET /agents fetch resolves (or if it fails) — the real, complete
// agent directory lives there, sourced from the backend.
export const DEFAULT_AGENT = "Emma Watts";
