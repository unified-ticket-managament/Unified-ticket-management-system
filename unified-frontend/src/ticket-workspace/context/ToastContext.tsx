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

interface Toast {
  id: number;
  message: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  toasts: Toast[];
  pushToast: (message: string, variant?: ToastVariant) => void;
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
    (message: string, variant: ToastVariant = "info") => {
      const id = ++toastCounter;
      setToasts((prev) => [...prev, { id, message, variant }]);
      window.setTimeout(() => dismissToast(id), 4000);
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
