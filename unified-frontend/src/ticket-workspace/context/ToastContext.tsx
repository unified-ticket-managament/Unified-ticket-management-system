import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

// ==========================================================
// Minimal toast/notification system.
//
// Used to surface API success and error messages from
// action buttons across the demo, without each component
// re-implementing its own alert UI.
// ==========================================================

export type ToastVariant = "success" | "error" | "info";

// Optional action button — used by the Undo-Send toast (Issue 8) so a
// just-sent Compose/Reply can be canceled within its real, backend-
// enforced window. Every other existing pushToast call in the app
// simply never sets this, so nothing about their rendering changes.
export interface ToastAction {
  label: string;
  onClick: () => void;
}

interface Toast {
  id: number;
  message: string;
  variant: ToastVariant;
  action?: ToastAction;
}

interface PushToastOptions {
  action?: ToastAction;
  // Defaults to 4000ms, same as every existing toast — the Undo-Send
  // toast passes durationMs matching the backend's own real
  // cancellation window (see undo_send.UNDO_SEND_WINDOW_SECONDS on
  // the backend) so the toast never disappears while Undo would still
  // actually work server-side.
  durationMs?: number;
}

interface ToastContextValue {
  toasts: Toast[];
  pushToast: (message: string, variant?: ToastVariant, options?: PushToastOptions) => void;
  dismissToast: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

let toastCounter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const pushToast = useCallback(
    (message: string, variant: ToastVariant = "info", options?: PushToastOptions) => {
      const id = ++toastCounter;
      setToasts((prev) => [...prev, { id, message, variant, action: options?.action }]);
      window.setTimeout(() => dismissToast(id), options?.durationMs ?? 4000);
    },
    [dismissToast]
  );

  return (
    <ToastContext.Provider value={{ toasts, pushToast, dismissToast }}>
      {children}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used inside a <ToastProvider>.");
  }
  return ctx;
}
