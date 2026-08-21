"use client";

import { MailOpen } from "lucide-react";

// Panel 3's own empty state for the Outlook-style Mail workspace (see
// InboxPage.tsx/MailWorkspaceLayout.tsx) — deliberately distinct from
// MailEmptyState (which means "this folder has zero messages" and
// offers a Compose action). This means "nothing is open in the
// reading pane yet", with no action of its own.
export function MailReadingPaneEmptyState() {
  return (
    <div className="flex h-full min-h-[24rem] flex-col items-center justify-center gap-3 p-8 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted">
        <MailOpen className="h-7 w-7 text-muted-foreground" />
      </div>
      <p className="text-[14px] font-medium text-foreground">Select a message to view its details.</p>
    </div>
  );
}
