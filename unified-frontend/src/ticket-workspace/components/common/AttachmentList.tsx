import { useState } from "react";
import { Download, ExternalLink, Loader2 } from "lucide-react";
import type { AttachmentMeta } from "@tw/types";
import { downloadAttachmentFile } from "@tw/api/interaction";
import { formatBytes, iconForFilename, isImageAttachment } from "@tw/lib/attachmentMeta";

interface AttachmentListProps {
  attachments: AttachmentMeta[];
  className?: string;
}

export function AttachmentList({ attachments, className = "" }: AttachmentListProps) {
  // Inline/embedded images (e.g. a signature logo referenced via
  // cid:) already render inside the message body itself — listing
  // them here too would show the same image twice.
  const visibleAttachments = attachments.filter((attachment) => !attachment.is_inline);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  if (visibleAttachments.length === 0) return null;

  async function handleDownload(attachment: AttachmentMeta) {
    setDownloadingId(attachment.id);
    try {
      await downloadAttachmentFile(attachment.id, attachment.filename);
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      {visibleAttachments.map((attachment) => {
        const isExternal = Boolean(attachment.is_external_link);
        const Icon = isExternal ? ExternalLink : iconForFilename(attachment.filename);
        const isImage = !isExternal && isImageAttachment(attachment);
        const isDownloading = downloadingId === attachment.id;

        const content = (
          <>
            {isImage && attachment.preview_url ? (
              <img
                src={attachment.preview_url}
                alt={attachment.filename}
                className="h-10 w-10 flex-none rounded-md2 border border-border object-cover"
              />
            ) : (
              <span className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-canvas text-muted">
                <Icon size={16} />
              </span>
            )}
            <span className="min-w-0 flex-1">
              <span className="block truncate text-slate-800">{attachment.filename}</span>
              <span className="block text-[11px] font-normal text-muted">
                {isExternal ? "Linked file — opens in OneDrive/SharePoint" : formatBytes(attachment.size)}
              </span>
            </span>
            {isExternal ? (
              <ExternalLink size={14} className="flex-none text-muted transition-colors group-hover:text-accent" />
            ) : isDownloading ? (
              <Loader2 size={14} className="flex-none animate-spin text-muted" />
            ) : (
              <Download size={14} className="flex-none text-muted transition-colors group-hover:text-accent" />
            )}
          </>
        );

        const rowClassName =
          "group flex items-center gap-3 rounded-md2 border border-border bg-surface px-3 py-2 text-[12px] font-medium text-slate-700 shadow-xs transition-colors hover:border-accent/30 hover:bg-accent/5";

        // External links and image previews are plain navigations (a
        // preview_url load isn't a "download" at all, and an external
        // link opens Microsoft's own host) — only a real, non-image
        // stored-file download needs to go through the authenticated
        // fetch-then-blob path below.
        if (isExternal) {
          return (
            <a
              key={attachment.id}
              href={attachment.download_url}
              target="_blank"
              rel="noreferrer"
              title="Opens the original OneDrive/SharePoint link"
              className={rowClassName}
            >
              {content}
            </a>
          );
        }

        if (isImage && attachment.preview_url) {
          return (
            <a
              key={attachment.id}
              href={attachment.preview_url}
              target="_blank"
              rel="noreferrer"
              className={rowClassName}
            >
              {content}
            </a>
          );
        }

        return (
          <button
            key={attachment.id}
            type="button"
            onClick={() => handleDownload(attachment)}
            disabled={isDownloading}
            className={`${rowClassName} w-full text-left disabled:cursor-not-allowed disabled:opacity-60`}
          >
            {content}
          </button>
        );
      })}
    </div>
  );
}
