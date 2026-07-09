"use client";

import { useState } from "react";
import { Send, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AttachmentUploader } from "@tw/components/mail/AttachmentUploader";
import { RichTextEditor, isRichTextEmpty } from "@tw/components/mail/RichTextEditor";
import { escapeHtml, htmlToPlainText } from "@tw/lib/richText";

function parseEmails(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

interface ReplyComposerProps {
  mode: "reply" | "replyAll";
  toEmail: string | null;
  subject: string;
  initialCc?: string[];
  initialMessage?: string;
  canAttach: boolean;
  canSaveDraft: boolean;
  isSending: boolean;
  isSavingDraft: boolean;
  onCancel: () => void;
  onSend: (payload: { message: string; cc: string[]; bcc: string[]; files: File[] }) => void;
  onSaveDraft: (message: string) => void;
}

// The inline Reply / Reply All composer — expands directly below the
// opened message (never a modal/new panel/navigation). Attachments
// only actually persist once this thread is ticketed (the only
// existing endpoint that can store a file against an interaction is
// ticket-scoped) — shown either way for a consistent composer, just
// disabled with an explanation pre-ticket.
export function ReplyComposer({
  mode,
  toEmail,
  subject,
  initialCc = [],
  initialMessage = "",
  canAttach,
  canSaveDraft,
  isSending,
  isSavingDraft,
  onCancel,
  onSend,
  onSaveDraft,
}: ReplyComposerProps) {
  const [bodyHtml, setBodyHtml] = useState(() =>
    initialMessage ? `<p>${escapeHtml(initialMessage).replace(/\n/g, "<br/>")}</p>` : ""
  );
  const [cc, setCc] = useState(initialCc.join(", "));
  const [bcc, setBcc] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [showCcBcc, setShowCcBcc] = useState(mode === "replyAll" || initialCc.length > 0);

  const isEmpty = isRichTextEmpty(bodyHtml);

  return (
    <div className="border-t border-border bg-muted/20 p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {mode === "replyAll" ? "Reply All" : "Reply"}
        </p>
        <Button variant="ghost" size="sm" onClick={onCancel} className="h-7 gap-1 text-xs">
          <X className="h-3.5 w-3.5" />
          Cancel
        </Button>
      </div>

      <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
        <div className="flex items-center gap-2 text-xs">
          <span className="w-10 flex-none text-muted-foreground">To</span>
          <span className="truncate font-medium text-foreground">{toEmail ?? "—"}</span>
          {!showCcBcc && (
            <button
              type="button"
              onClick={() => setShowCcBcc(true)}
              className="ml-auto flex-none text-[11px] font-medium text-primary hover:underline"
            >
              Add Cc/Bcc
            </button>
          )}
        </div>
        {showCcBcc && (
          <>
            <div className="flex items-center gap-2 text-xs">
              <span className="w-10 flex-none text-muted-foreground">Cc</span>
              <Input
                value={cc}
                onChange={(e) => setCc(e.target.value)}
                placeholder="cc@example.com, ..."
                className="h-8 flex-1 text-xs"
              />
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="w-10 flex-none text-muted-foreground">Bcc</span>
              <Input
                value={bcc}
                onChange={(e) => setBcc(e.target.value)}
                placeholder="bcc@example.com, ..."
                className="h-8 flex-1 text-xs"
              />
            </div>
          </>
        )}
        <div className="flex items-center gap-2 text-xs">
          <span className="w-10 flex-none text-muted-foreground">Subject</span>
          <span className="truncate text-foreground/80">{subject}</span>
        </div>
      </div>

      <div className="mt-3">
        <RichTextEditor
          value={bodyHtml}
          onChange={setBodyHtml}
          placeholder="Write a reply to the client..."
          minHeight="7rem"
        />
      </div>

      <div className="mt-3" title={canAttach ? undefined : "Attachments are only available once this thread has become a ticket."}>
        <AttachmentUploader files={files} onFilesChange={setFiles} disabled={!canAttach} />
      </div>

      <div className="mt-3 flex items-center justify-end gap-2">
        {canSaveDraft && (
          <Button
            variant="outline"
            size="sm"
            disabled={isEmpty || isSavingDraft}
            onClick={() => onSaveDraft(htmlToPlainText(bodyHtml))}
          >
            Save Draft
          </Button>
        )}
        <Button
          size="sm"
          className="gap-1.5"
          disabled={isEmpty || isSending}
          onClick={() =>
            onSend({
              message: htmlToPlainText(bodyHtml),
              cc: parseEmails(cc),
              bcc: parseEmails(bcc),
              files,
            })
          }
        >
          <Send className="h-3.5 w-3.5" />
          Send Reply
        </Button>
      </div>
    </div>
  );
}
