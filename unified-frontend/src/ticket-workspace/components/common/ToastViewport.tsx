import type { ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { useToast } from "@tw/context/ToastContext";

const variantStyles: Record<string, string> = {
  success: "border-success/20 bg-surface text-slate-800",
  error: "border-danger/20 bg-surface text-slate-800",
  info: "border-accent/20 bg-surface text-slate-800",
};

const variantIcon: Record<string, ReactNode> = {
  success: <CheckCircle2 size={17} className="flex-none text-success" />,
  error: <AlertCircle size={17} className="flex-none text-danger" />,
  info: <Info size={17} className="flex-none text-accent" />,
};

export function ToastViewport() {
  const { toasts, dismissToast } = useToast();

  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-96 max-w-[calc(100vw-2.5rem)] flex-col gap-2.5">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          onClick={() => dismissToast(toast.id)}
          className={`pointer-events-auto flex cursor-pointer items-start gap-2.5 rounded-md2 border px-4 py-3.5 text-[13px] font-medium leading-snug shadow-popover animate-fadeSlideIn ${
            variantStyles[toast.variant] ?? variantStyles.info
          }`}
        >
          {variantIcon[toast.variant] ?? variantIcon.info}
          <span className="flex-1">{toast.message}</span>
          {toast.action && (
            <button
              type="button"
              onClick={(e) => {
                // Stop this click reaching the toast's own onClick
                // (which would dismiss it before onClick below runs)
                // — the action itself is responsible for dismissing
                // via its own dismissToast call.
                e.stopPropagation();
                toast.action?.onClick();
                dismissToast(toast.id);
              }}
              className="flex-none rounded-md2 px-2 py-1 text-[12px] font-semibold text-accent underline-offset-2 hover:underline"
            >
              {toast.action.label}
            </button>
          )}
          <X size={14} className="mt-0.5 flex-none text-muted" />
        </div>
      ))}
    </div>
  );
}
