"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, Paperclip, Send, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AttachmentUploader } from "@tw/components/mail/AttachmentUploader";
import { RichTextEditor, isRichTextEmpty } from "@tw/components/mail/RichTextEditor";
import {
  ATTACHMENT_ACCEPT_ATTR,
  MAX_ATTACHMENT_FILES,
  formatBytes,
  iconForFilename,
  validateFiles,
} from "@tw/lib/attachmentMeta";
import { escapeHtml, htmlToPlainText } from "@tw/lib/richText";
import type { AttachmentMeta } from "@tw/types";

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
  initialBcc?: string[];
  initialMessage?: string;
  isSending: boolean;
  onCancel: () => void;
  // Ticketed-thread send — files are local (`File[]`) and only
  // actually upload once the reply is sent, via the existing
  // ticket-scoped attachment endpoint (unchanged from before).
  onSend: (payload: { message: string; cc: string[]; bcc: string[]; files: File[] }) => void;
  // Pre-ticket path: every field is continuously auto-saved as a
  // real server-side Draft (interaction-scoped, so it works with no
  // ticket at all — see the backend's AttachmentService), which is
  // also what makes attachments actually work before a ticket exists.
  isTicketed: boolean;
  draftAttachments: AttachmentMeta[];
  onSaveDraft: (message: string, cc: string[], bcc: string[]) => Promise<unknown>;
  onSendDraft: () => Promise<unknown>;
  onDiscardDraft: () => Promise<unknown>;
  onUploadDraftAttachment: (files: File[]) => Promise<AttachmentMeta[] | null>;
  onRemoveDraftAttachment: (attachmentId: string) => Promise<boolean>;
}

type DraftSaveStatus = "idle" | "saving" | "saved";

// The inline Reply / Reply All composer — expands directly below the
// opened message (never a modal/new panel/navigation). Two distinct
// backends power it depending on whether the thread is already a
// ticket:
//  - Ticketed: unchanged from before — local files, uploaded only at
//    Send, since that's the only attachment endpoint a ticketed
//    thread ever needed.
//  - Pre-ticket: every edit (Cc/Bcc/body) auto-saves as a real Draft
//    (debounced), and attachments upload immediately against that
//    draft's own interaction — this is what makes "Attach Files"
//    actually work before a ticket exists, and what makes Save
//    Draft/Discard Draft real, persisted actions instead of only
//    living in local component state.
export function ReplyComposer({
  mode,
  toEmail,
  subject,
  initialCc = [],
  initialBcc = [],
  initialMessage = "",
  isSending,
  onCancel,
  onSend,
  isTicketed,
  draftAttachments,
  onSaveDraft,
  onSendDraft,
  onDiscardDraft,
  onUploadDraftAttachment,
  onRemoveDraftAttachment,
}: ReplyComposerProps) {
  const [bodyHtml, setBodyHtml] = useState(() =>
    initialMessage ? `<p>${escapeHtml(initialMessage).replace(/\n/g, "<br/>")}</p>` : ""
  );
  const [cc, setCc] = useState(initialCc.join(", "));
  const [bcc, setBcc] = useState(initialBcc.join(", "));
  const [showBcc, setShowBcc] = useState(initialBcc.length > 0);
  const [files, setFiles] = useState<File[]>([]);
  const [showAttachments, setShowAttachments] = useState(false);

  const [draftStatus, setDraftStatus] = useState<DraftSaveStatus>("idle");
  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const [isSendingDraft, setIsSendingDraft] = useState(false);
  const [isDiscarding, setIsDiscarding] = useState(false);
  const [attachErrors, setAttachErrors] = useState<string[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const skipNextAutoSave = useRef(true);
  const savedIndicatorTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isEmpty = isRichTextEmpty(bodyHtml);
  const displaySubject = /^re:/i.test(subject.trim()) ? subject : `Re: ${subject}`;

  async function persistDraft() {
    setDraftStatus("saving");
    const result = await onSaveDraft(htmlToPlainText(bodyHtml), parseEmails(cc), parseEmails(bcc));
    setDraftStatus(result ? "saved" : "idle");
    if (result) {
      if (savedIndicatorTimer.current) clearTimeout(savedIndicatorTimer.current);
      savedIndicatorTimer.current = setTimeout(() => setDraftStatus("idle"), 2500);
    }
    return result;
  }

  // Continuous auto-save — debounced, pre-ticket only (a ticketed
  // thread has no draft row to save onto). Skips the very first
  // render so opening the composer doesn't immediately re-save
  // whatever it was just prefilled with.
  useEffect(() => {
    if (isTicketed) return;
    if (skipNextAutoSave.current) {
      skipNextAutoSave.current = false;
      return;
    }
    if (isEmpty) return;

    const timer = setTimeout(() => {
      persistDraft();
    }, 1200);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bodyHtml, cc, bcc, isTicketed]);

  useEffect(() => {
    return () => {
      if (savedIndicatorTimer.current) clearTimeout(savedIndicatorTimer.current);
    };
  }, []);

  async function handleSend() {
    if (isTicketed) {
      onSend({
        message: htmlToPlainText(bodyHtml),
        cc: parseEmails(cc),
        bcc: parseEmails(bcc),
        files,
      });
      return;
    }

    // Make sure the latest keystrokes are saved before converting the
    // draft into a real reply — the debounce above may not have fired
    // yet if the user clicks Send quickly after typing.
    setIsSendingDraft(true);
    await persistDraft();
    await onSendDraft();
    setIsSendingDraft(false);
  }

  async function handleDiscard() {
    if (isTicketed) {
      onCancel();
      return;
    }
    setIsDiscarding(true);
    await onDiscardDraft();
    setIsDiscarding(false);
    onCancel();
  }

  async function handleAddDraftFiles(incoming: FileList) {
    const { accepted, errors } = validateFiles(Array.from(incoming));
    setAttachErrors(errors);
    if (accepted.length === 0) return;

    setIsUploadingFile(true);
    await onUploadDraftAttachment(accepted);
    setIsUploadingFile(false);
  }

  const draftAttachmentCount = draftAttachments.length;

  return (
    <div className="border-t border-border bg-muted/20 p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {mode === "replyAll" ? "Reply All" : "Reply"}
        </p>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleDiscard}
          disabled={isDiscarding}
          className="h-7 gap-1 text-xs"
        >
          {isDiscarding ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : isTicketed ? (
            <X className="h-3.5 w-3.5" />
          ) : (
            <Trash2 className="h-3.5 w-3.5" />
          )}
          {isTicketed ? "Cancel" : "Discard Draft"}
        </Button>
      </div>

      <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
        <div className="flex items-center gap-2 text-xs">
          <span className="w-10 flex-none text-muted-foreground">To</span>
          <Input value={toEmail ?? ""} readOnly className="h-8 flex-1 bg-muted/30 text-xs" />
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="w-10 flex-none text-muted-foreground">Cc</span>
          <Input
            value={cc}
            onChange={(e) => setCc(e.target.value)}
            placeholder="cc@example.com, ..."
            className="h-8 flex-1 text-xs"
          />
          {!showBcc && (
            <button
              type="button"
              onClick={() => setShowBcc(true)}
              className="flex-none text-[11px] font-medium text-primary hover:underline"
            >
              Bcc
            </button>
          )}
        </div>
        {showBcc && (
          <div className="flex items-center gap-2 text-xs">
            <span className="w-10 flex-none text-muted-foreground">Bcc</span>
            <Input
              value={bcc}
              onChange={(e) => setBcc(e.target.value)}
              placeholder="bcc@example.com, ..."
              className="h-8 flex-1 text-xs"
            />
          </div>
        )}
        <div className="flex items-center gap-2 text-xs">
          <span className="w-10 flex-none text-muted-foreground">Subject</span>
          <span className="truncate text-foreground/80">{displaySubject}</span>
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

      {isTicketed ? (
        <>
          {showAttachments && (
            <div className="mt-3">
              <AttachmentUploader files={files} onFilesChange={setFiles} />
            </div>
          )}

          <div className="mt-3 flex items-center justify-between gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => setShowAttachments((prev) => !prev)}
            >
              <Paperclip className="h-3.5 w-3.5" />
              Attach Files{files.length > 0 ? ` (${files.length})` : ""}
            </Button>

            <Button size="sm" className="gap-1.5" disabled={isEmpty || isSending} onClick={handleSend}>
              <Send className="h-3.5 w-3.5" />
              Send Reply
            </Button>
          </div>
        </>
      ) : (
        <>
          <div className="mt-3 flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Attachments
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 gap-1.5 text-xs"
                disabled={isUploadingFile || draftAttachmentCount >= MAX_ATTACHMENT_FILES}
                onClick={() => fileInputRef.current?.click()}
              >
                {isUploadingFile ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Paperclip className="h-3 w-3" />
                )}
                Attach Files
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={ATTACHMENT_ACCEPT_ATTR}
                className="hidden"
                onChange={(e) => {
                  if (e.target.files?.length) handleAddDraftFiles(e.target.files);
                  e.target.value = "";
                }}
              />
            </div>

            {attachErrors.length > 0 && (
              <div className="flex flex-col gap-1 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2">
                {attachErrors.map((error) => (
                  <p key={error} className="text-[11px] text-destructive">
                    {error}
                  </p>
                ))}
              </div>
            )}

            {draftAttachmentCount > 0 && (
              <ul className="flex flex-col gap-1.5">
                {draftAttachments.map((attachment) => {
                  const Icon = iconForFilename(attachment.filename);
                  return (
                    <li
                      key={attachment.id}
                      className="flex items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-1.5"
                    >
                      <Icon className="h-3.5 w-3.5 flex-none text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate text-xs font-medium text-foreground">
                        {attachment.filename}
                      </span>
                      <span className="flex-none text-[11px] text-muted-foreground">
                        {formatBytes(attachment.size)}
                      </span>
                      <button
                        type="button"
                        onClick={() => onRemoveDraftAttachment(attachment.id)}
                        aria-label={`Remove ${attachment.filename}`}
                        className="flex-none rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="mt-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              {draftStatus === "saving" && (
                <>
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Saving...
                </>
              )}
              {draftStatus === "saved" && (
                <>
                  <Check className="h-3 w-3 text-success" />
                  Draft Saved
                </>
              )}
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={isEmpty || draftStatus === "saving"}
                onClick={persistDraft}
              >
                Save Draft
              </Button>
              <Button
                size="sm"
                className="gap-1.5"
                disabled={isEmpty || isSending || isSendingDraft}
                onClick={handleSend}
              >
                {isSendingDraft ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Send className="h-3.5 w-3.5" />
                )}
                Send
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
