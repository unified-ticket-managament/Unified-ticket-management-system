import { cancelSend } from "@tw/api/interaction";
import type { ToastVariant } from "@tw/context/ToastContext";

// Matches the backend's own undo_send.UNDO_SEND_WINDOW_SECONDS —
// purely presentational here (a countdown display / how long the
// toast stays up); the backend enforces the real deadline
// independently and remains authoritative regardless of what this
// value is set to.
export const UNDO_SEND_WINDOW_MS = 10_000;

type PushToast = (
  message: string,
  variant?: ToastVariant,
  options?: { action?: { label: string; onClick: () => void }; durationMs?: number }
) => void;

// Shared by every outbound send path (Compose, ticket-level Reply,
// pre-ticket Reply/Draft-send) — see root CLAUDE.md's Issue 8 section
// for why all four call sites funnel through this one helper instead
// of each re-implementing its own Undo toast. `interactionId` is
// whatever the just-completed send's own response returned; the
// actual cancellation call — and therefore whether Undo still works —
// is decided entirely server-side (InteractionService.cancel_pending_send).
export function showUndoSendToast(
  pushToast: PushToast,
  interactionId: string | null | undefined,
  sentMessage: string
): void {
  if (!interactionId) {
    // No interaction id on the response (shouldn't happen for a real
    // send) — fall back to a plain toast rather than offering an
    // Undo button that has nothing to act on.
    pushToast(sentMessage, "success");
    return;
  }

  pushToast(sentMessage, "success", {
    durationMs: UNDO_SEND_WINDOW_MS,
    action: {
      label: "Undo",
      onClick: () => {
        cancelSend(interactionId)
          .then(() => pushToast("Send canceled.", "info"))
          .catch((error: unknown) => {
            // The backend is the sole authority on whether the
            // window was still open (Cases C/G/I from the Issue 8
            // spec) — a 400 here means it already went out, or was
            // already canceled; never claim success client-side.
            pushToast(
              error instanceof Error
                ? error.message
                : "Couldn't undo — it may have already been sent.",
              "error"
            );
          });
      },
    },
  });
}
