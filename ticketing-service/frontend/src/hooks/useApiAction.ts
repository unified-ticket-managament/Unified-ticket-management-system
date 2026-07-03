import { useCallback, useRef, useState } from "react";
import { useToast } from "@/context/ToastContext";

// ==========================================================
// useApiAction
//
// Wraps a single backend call with loading state and toast
// feedback, so every action button in the demo follows the
// same pattern: disable while loading, show a toast with
// the result, and let the caller react to success.
//
// Guards against stale responses: if `run()` is called again
// before a previous call resolves (e.g. an effect re-fires when
// `agentName` changes while the old fetch for the previous agent
// is still in flight), only the *latest* call is allowed to show
// a toast or flip `isLoading` back off. Without this, a slow,
// now-irrelevant response can resolve after a newer one already
// succeeded and show a confusing/incorrect toast (this was the
// root cause of the "brief blank flash + wrong error toast" seen
// when switching agents and navigating in the same tick).
// ==========================================================

export function useApiAction<TArgs extends unknown[], TResult>(
  action: (...args: TArgs) => Promise<TResult>,
  options?: {
    successMessage?: string | ((result: TResult) => string);
  }
) {
  const [isLoading, setIsLoading] = useState(false);
  const { pushToast } = useToast();
  const requestIdRef = useRef(0);

  const run = useCallback(
    async (...args: TArgs): Promise<TResult | null> => {
      const requestId = ++requestIdRef.current;
      setIsLoading(true);
      try {
        const result = await action(...args);
        const isStale = requestId !== requestIdRef.current;
        if (isStale) return result;

        const message =
          typeof options?.successMessage === "function"
            ? options.successMessage(result)
            : options?.successMessage;

        if (message) {
          pushToast(message, "success");
        }

        return result;
      } catch (error) {
        const isStale = requestId !== requestIdRef.current;
        if (isStale) return null;

        const message =
          error instanceof Error ? error.message : "Request failed.";
        pushToast(message, "error");
        return null;
      } finally {
        if (requestId === requestIdRef.current) setIsLoading(false);
      }
    },
    [action, options, pushToast]
  );

  return { run, isLoading };
}
