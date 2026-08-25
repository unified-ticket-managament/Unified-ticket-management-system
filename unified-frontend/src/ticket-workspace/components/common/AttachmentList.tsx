import { Download, ExternalLink } from "lucide-react";
import type { AttachmentMeta } from "@tw/types";
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

  if (visibleAttachments.length === 0) return null;

  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      {visibleAttachments.map((attachment) => {
        const isExternal = Boolean(attachment.is_external_link);
        const Icon = isExternal ? ExternalLink : iconForFilename(attachment.filename);
        const isImage = !isExternal && isImageAttachment(attachment);

        return (
          <a
            key={attachment.id}
            href={isImage ? attachment.preview_url ?? attachment.download_url : attachment.download_url}
            target="_blank"
            rel="noreferrer"
            download={!isImage && !isExternal}
            title={isExternal ? "Opens the original OneDrive/SharePoint link" : undefined}
            className="group flex items-center gap-3 rounded-md2 border border-border bg-surface px-3 py-2 text-[12px] font-medium text-slate-700 shadow-xs transition-colors hover:border-accent/30 hover:bg-accent/5"
          >
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
            ) : (
              <Download size={14} className="flex-none text-muted transition-colors group-hover:text-accent" />
            )}
          </a>
        );
      })}
    </div>
  );
}
