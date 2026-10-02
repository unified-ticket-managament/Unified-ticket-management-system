import type { HTMLAttributes } from "react";
import { UploadCloud } from "lucide-react";

import { cn } from "@/lib/utils";
import { useAttachmentIntake } from "@tw/hooks/useAttachmentIntake";

interface AttachmentDropAreaProps extends HTMLAttributes<HTMLDivElement> {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}

// Wraps one attachment-enabled composer so files can be dropped onto it
// or pasted into it, Outlook-style. It never uploads or validates
// anything itself — `onFiles` is the composer's own existing add-files
// path, the same one its Attach button uses. The Attach button and the
// composer's own dropzone box stay exactly as they were; this is only an
// additional way in.
export function AttachmentDropArea({ onFiles, disabled = false, className, children, ...rest }: AttachmentDropAreaProps) {
  const { isDragging, containerProps } = useAttachmentIntake({ onFiles, disabled });

  return (
    <div {...rest} {...containerProps} className={cn("relative", className)}>
      {children}
      {isDragging && (
        <div
          aria-hidden="true"
          data-testid="attachment-drop-overlay"
          className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-primary bg-primary/10 text-center"
        >
          <UploadCloud className="h-6 w-6 text-primary" />
          <p className="text-sm font-semibold text-foreground">Drop files here</p>
          <p className="text-xs text-muted-foreground">Release to attach</p>
        </div>
      )}
    </div>
  );
}
