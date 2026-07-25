interface ShowMoreToggleProps {
  isExpanded: boolean;
  onToggle: () => void;
  className?: string;
}

// Paired with useCollapsibleMessage — only ever rendered by the caller
// when that hook's own `isOverflowing` is true, so a short message
// never gets this control at all. Stops propagation on click since
// this is often nested inside a larger clickable row (e.g. the ticket
// conversation feed's own row-click-to-open behavior) that shouldn't
// also fire just because the user wanted to expand the text.
export function ShowMoreToggle({ isExpanded, onToggle, className }: ShowMoreToggleProps) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      className={`mt-1 text-xs font-semibold text-accent hover:underline ${className ?? ""}`}
    >
      {isExpanded ? "Show Less" : "Show More"}
    </button>
  );
}
