import { Download } from "lucide-react";
import type { AttachmentMeta } from "@tw/types";
import { formatBytes, iconForFilename, isImageAttachment } from "@tw/lib/attachmentMeta";

interface AttachmentListProps {
  attachments: AttachmentMeta[];
  className?: string;
}

export function AttachmentList({ attachments, className = "" }: AttachmentListProps) {
  if (attachments.length === 0) return null;

  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      {attachments.map((attachment) => {
        const Icon = iconForFilename(attachment.filename);
        const isImage = isImageAttachment(attachment);

        return (
          <a
            key={attachment.id}
            href={isImage ? attachment.preview_url ?? attachment.download_url : attachment.download_url}
            target="_blank"
            rel="noreferrer"
            download={!isImage}
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
                {formatBytes(attachment.size)}
              </span>
            </span>
            <Download size={14} className="flex-none text-muted transition-colors group-hover:text-accent" />
          </a>
        );
      })}
    </div>
  );
}
