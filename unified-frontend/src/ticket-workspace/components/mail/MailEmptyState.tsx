"use client";

import { Mail, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";

interface MailEmptyStateProps {
  onCompose: () => void;
  title?: string;
  description?: string;
  // Overrides the button's icon/label/click-handler pair together —
  // used by the request-failed variant (button becomes "Refresh"
  // instead of "Compose Message", calling onRefresh instead of
  // onCompose). Omitted everywhere else, so every existing caller's
  // behavior is unchanged.
  action?: { label: string; icon: typeof Plus; onClick: () => void };
  // Swaps the circular icon above the title — defaults to the
  // existing Mail icon; the request-failed variant passes AlertCircle
  // instead so it's visually distinguishable from a genuine empty
  // folder, not just by its text.
  icon?: typeof Mail;
}

// The Mail spec's required empty state: centered (both axes), large
// icon, title/description, and an action button — shown whenever the
// selected folder/view has zero items, or (via the `action`/`icon`
// overrides) whenever loading it failed outright.
export function MailEmptyState({
  onCompose,
  title = "No Messages",
  description = "This folder is empty.",
  action,
  icon: Icon = Mail,
}: MailEmptyStateProps) {
  const ActionIcon = action?.icon ?? Plus;
  return (
    <div className="flex h-full min-h-[24rem] flex-col items-center justify-center gap-4 rounded-xl border border-border bg-card p-8 text-center shadow-card">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted">
        <Icon className="h-8 w-8 text-muted-foreground" />
      </div>
      <div>
        <p className="text-base font-semibold text-foreground">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      <Button onClick={action?.onClick ?? onCompose} className="gap-2">
        <ActionIcon className="h-4 w-4" />
        {action?.label ?? "Compose Message"}
      </Button>
    </div>
  );
}
