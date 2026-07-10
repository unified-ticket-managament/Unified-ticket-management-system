"use client";

import { Mail, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";

interface MailEmptyStateProps {
  onCompose: () => void;
  title?: string;
  description?: string;
}

// The Mail spec's required empty state: centered (both axes), large
// mail icon, "No Messages" / "This folder is empty.", and a Compose
// button — shown whenever the selected folder/view has zero items.
export function MailEmptyState({
  onCompose,
  title = "No Messages",
  description = "This folder is empty.",
}: MailEmptyStateProps) {
  return (
    <div className="flex h-full min-h-[24rem] flex-col items-center justify-center gap-4 rounded-xl border border-border bg-card p-8 text-center shadow-card">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted">
        <Mail className="h-8 w-8 text-muted-foreground" />
      </div>
      <div>
        <p className="text-base font-semibold text-foreground">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      <Button onClick={onCompose} className="gap-2">
        <Plus className="h-4 w-4" />
        Compose Message
      </Button>
    </div>
  );
}
