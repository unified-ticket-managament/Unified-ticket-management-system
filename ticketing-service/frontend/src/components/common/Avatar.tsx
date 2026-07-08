export function initials(name: string): string {
  return name
    .trim()
    .split(" ")
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

const SIZE_CLASSES = {
  sm: "h-7 w-7 text-[11px]",
  md: "h-9 w-9 text-xs",
  lg: "h-11 w-11 text-sm",
} as const;

interface AvatarProps {
  name: string;
  size?: keyof typeof SIZE_CLASSES;
  /** Small colored dot in the bottom-right corner, e.g. an online/active indicator. */
  indicator?: "success" | "warning" | "danger";
  className?: string;
}

const INDICATOR_CLASSES = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
} as const;

/**
 * Shared initials avatar circle — consolidates what used to be three
 * separate, slightly-divergent `initials()` implementations
 * (Sidebar.tsx, Topbar.tsx, AgentInbox.tsx). Standardized on the
 * two-letter form two of the three already used.
 */
export function Avatar({ name, size = "md", indicator, className = "" }: AvatarProps) {
  return (
    <div className={`relative flex-none ${className}`}>
      <div
        className={`flex items-center justify-center rounded-full bg-accent/10 font-semibold text-accent ${SIZE_CLASSES[size]}`}
      >
        {initials(name) || "?"}
      </div>
      {indicator && (
        <span
          className={`absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-surface ${INDICATOR_CLASSES[indicator]}`}
        />
      )}
    </div>
  );
}
