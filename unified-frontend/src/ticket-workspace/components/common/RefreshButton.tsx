import { RefreshCw } from "lucide-react";
import { Button } from "@tw/components/common/Button";

interface RefreshButtonProps {
  onRefresh: () => void;
  isRefreshing?: boolean;
  label?: string;
}

// One shared Refresh control for pages built on the ticket-workspace's
// own common Button (not shadcn's — see MessageList.tsx/
// SystemMailList.tsx for that variant, already established for Mail).
// Re-fetches only this page's own data via whatever hook/callback the
// caller already uses — never a full browser reload — and preserves
// whatever filters/sorting/pagination/tab state the page already
// holds, since nothing here touches that state at all.
export function RefreshButton({ onRefresh, isRefreshing = false, label = "Refresh" }: RefreshButtonProps) {
  return (
    <Button
      variant="secondary"
      size="sm"
      onClick={onRefresh}
      disabled={isRefreshing}
      aria-label={label}
      title={label}
      className="gap-1.5"
    >
      <RefreshCw className={isRefreshing ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
      {label}
    </Button>
  );
}
