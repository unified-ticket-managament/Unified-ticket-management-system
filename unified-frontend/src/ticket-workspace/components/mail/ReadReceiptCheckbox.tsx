import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

// Shown next to the checkbox and reused as the status tooltip. A read
// receipt is an optional acknowledgement sent by the recipient's own
// mail system: it can be declined, suppressed or never sent, so its
// absence says nothing about whether the message was read.
export const READ_RECEIPT_HELP_TEXT =
  "Read receipts are optional and depend on the recipient's mail system.";

// "Request read receipt" — rendered by ReplyComposer and ComposeView
// only when the backend's read_receipts_enabled setting is on (see
// useMailFeatures). Controlled and presentational: the composers own
// the state, persist it with the draft, and send it with the message.
export function ReadReceiptCheckbox({
  checked,
  onCheckedChange,
  disabled = false,
  className,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <label
      className={cn("flex items-center gap-2 text-xs text-foreground/80", className)}
      title={READ_RECEIPT_HELP_TEXT}
    >
      <Checkbox
        checked={checked}
        disabled={disabled}
        onCheckedChange={(value) => onCheckedChange(value === true)}
        aria-label="Request read receipt"
      />
      <span>Request read receipt</span>
      <span className="text-[11px] text-muted-foreground">
        Optional — depends on the recipient&apos;s mail system.
      </span>
    </label>
  );
}
