import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

interface CollapsibleProps {
  title: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
  className?: string;
}

/**
 * A simple expand/collapse section — used for e.g. "N previous
 * messages" in a mail thread. No accordion/collapsible primitive
 * existed anywhere in this codebase before this, so this is
 * deliberately minimal rather than a full accessible-accordion
 * library replacement.
 */
export function Collapsible({ title, defaultOpen = false, children, className = "" }: CollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={className}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 py-1.5 text-[11px] font-semibold text-muted transition-colors hover:text-slate-700 focus-visible:outline-none"
      >
        <ChevronDown
          size={13}
          className={`flex-none transition-transform duration-150 ${open ? "rotate-180" : ""}`}
        />
        {title}
      </button>
      {open && <div className="mt-1">{children}</div>}
    </div>
  );
}
