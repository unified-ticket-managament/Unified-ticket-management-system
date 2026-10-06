import { Check } from "lucide-react";

import { formatDateTime } from "@tw/lib/format";
import type { ReadReceiptStatus as ReadReceiptStatusData } from "@tw/types";
import { READ_RECEIPT_HELP_TEXT } from "./ReadReceiptCheckbox";

// Per-recipient read-receipt state for one OUTBOUND message.
//
// Wording is deliberate: the only two states are "a receipt arrived"
// and "no receipt arrived". A missing receipt NEVER means the message
// was unread (recipients and organisations can decline or suppress
// receipts), so this component never uses "Unread"/"Not read" and never
// claims a receipt proves a person read the message. The time shown is
// when the receipt was received/generated, not necessarily when it was
// opened.
export function ReadReceiptStatus({
  receipts,
  requested = false,
}: {
  receipts?: ReadReceiptStatusData[] | null;
  // True when the message asked for a receipt but no per-recipient rows
  // exist yet (they are created once the send actually leaves) — shows
  // a neutral "requested" line instead of nothing.
  requested?: boolean;
}) {
  const rows = receipts ?? [];

  if (rows.length === 0) {
    if (!requested) return null;
    return (
      <p className="mt-1 text-[11px] text-muted-foreground" title={READ_RECEIPT_HELP_TEXT}>
        Read receipt requested
      </p>
    );
  }

  return (
    <ul
      className="mt-1 flex flex-col gap-0.5"
      aria-label="Read receipts"
      title={READ_RECEIPT_HELP_TEXT}
    >
      {rows.map((receipt) => {
        const confirmed = receipt.status === "CONFIRMED";
        return (
          <li
            key={receipt.recipient_email}
            className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground"
          >
            <span className="font-medium text-foreground/80">{receipt.recipient_email}</span>
            {confirmed ? (
              <span className="inline-flex items-center gap-1 text-success">
                <Check className="h-3 w-3" aria-hidden="true" />
                Read receipt received
                {receipt.read_at ? ` · ${formatDateTime(receipt.read_at)}` : ""}
              </span>
            ) : (
              <span>No receipt received</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
