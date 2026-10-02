"use client";

import { useState, type ReactNode } from "react";
import { Maximize2, Minimize2, Minus } from "lucide-react";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

// The double-click email window. NORMAL is, character for character, the
// size this window has always had (it used to be inlined in InboxPage's
// Dialog) — it must not drift, since it is also what "restore" returns
// to. MAXIMIZED only widens it to the full viewport.
export const EMAIL_WINDOW_NORMAL_CLASS =
  "flex h-[85vh] max-h-[85vh] w-full max-w-5xl flex-col gap-0 overflow-hidden p-0";
export const EMAIL_WINDOW_MAXIMIZED_CLASS =
  "flex h-[100vh] max-h-[100vh] w-[100vw] max-w-none flex-col gap-0 overflow-hidden p-0 sm:rounded-none";

interface EmailWindowProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

// Two states, nothing more: NORMAL <-> MAXIMIZED, plus Close. "Minimize"
// here means "back down from maximized to the normal size" — there is no
// docked/taskbar state. Switching between the two only swaps the
// DialogContent's size classes, so `children` (the opened email, its
// reply composer, typed text, attachments, ...) stays mounted and keeps
// all of its state.
export function EmailWindow({ open, onClose, title, children }: EmailWindowProps) {
  const [isMaximized, setIsMaximized] = useState(false);
  const [wasOpen, setWasOpen] = useState(open);

  // Every fresh open starts at the normal size: forget "maximized" the
  // moment the window closes, whoever closed it (its own X, or the page
  // closing it to open Compose).
  if (open !== wasOpen) {
    setWasOpen(open);
    if (!open) setIsMaximized(false);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent
        className={isMaximized ? EMAIL_WINDOW_MAXIMIZED_CLASS : EMAIL_WINDOW_NORMAL_CLASS}
        aria-describedby={undefined}
      >
        {/* The Dialog's own X (absolute, right-4) is the Close button;
            Minimize and Maximize/Restore sit immediately to its left. */}
        <div className="relative flex h-12 flex-none items-center border-b border-border bg-card pl-5 pr-28">
          <DialogTitle className="truncate text-sm font-semibold leading-none">{title}</DialogTitle>
          <div className="absolute right-11 top-1/2 flex -translate-y-1/2 items-center gap-0.5">
            <button
              type="button"
              onClick={() => setIsMaximized(false)}
              disabled={!isMaximized}
              aria-label="Minimize"
              title="Minimize — return to normal size"
              className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
            >
              <Minus className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setIsMaximized((prev) => !prev)}
              aria-label={isMaximized ? "Restore" : "Maximize"}
              title={isMaximized ? "Restore" : "Maximize"}
              className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              {isMaximized ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </button>
          </div>
        </div>
        <div className="min-h-0 w-full flex-1 overflow-y-auto">{children}</div>
      </DialogContent>
    </Dialog>
  );
}
