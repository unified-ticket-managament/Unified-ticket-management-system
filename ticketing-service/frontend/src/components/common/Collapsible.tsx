import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

interface CollapsibleProps {
  title: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
  className?: string;
}

/**
 * A "line — centered pill — line" expand/collapse divider — used for
 * "N previous messages" in a mail thread. Its only consumer today is
 * EmailDetails.tsx, so it's styled specifically as a divider between
 * message cards rather than a generic accordion.
 */
export function Collapsible({ title, defaultOpen = false, children, className = "" }: CollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={className}>
      <div className="flex items-center gap-3">
        <div className="h-px flex-1 bg-border" />
        <button
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex flex-none items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1 text-[11px] font-medium text-muted transition-colors hover:text-slate-700 focus-visible:outline-none"
        >
          {title}
          <ChevronDown
            size={13}
            className={`flex-none transition-transform duration-150 ${open ? "rotate-180" : ""}`}
          />
        </button>
        <div className="h-px flex-1 bg-border" />
      </div>
      {open && <div className="mt-3">{children}</div>}
    </div>
  );
}
