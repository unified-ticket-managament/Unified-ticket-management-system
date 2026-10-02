import { useCallback } from "react";

import { useToast } from "@tw/context/ToastContext";
import { mergeAttachmentFiles } from "@tw/lib/attachmentIntake";
import { MAX_ATTACHMENT_FILES } from "@tw/lib/attachmentMeta";

// Feeds dropped/pasted files into a composer's existing local File[]
// attachment state with the same dedupe + validation the Browse button
// uses, reporting rejections through the app's existing toast system.
export function useAttachmentListIntake(
  files: File[],
  setFiles: (files: File[]) => void,
  maxFiles: number = MAX_ATTACHMENT_FILES
) {
  const { pushToast } = useToast();

  return useCallback(
    (incoming: File[]) => {
      const { accepted, errors } = mergeAttachmentFiles(files, incoming, maxFiles);
      if (errors.length > 0) pushToast(errors.join(" "), "error");
      setFiles(accepted);
    },
    [files, setFiles, maxFiles, pushToast]
  );
}
