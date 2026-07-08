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

type Tone = "accent" | "info" | "warning" | "success" | "default";

const TONE_CLASSES: Record<Tone, string> = {
  accent: "bg-accent/10 text-accent",
  info: "bg-info/10 text-info",
  warning: "bg-warning/10 text-warning",
  success: "bg-success/10 text-success",
  default: "bg-slate-100 text-slate-600",
};

interface AvatarProps {
  name: string;
  size?: keyof typeof SIZE_CLASSES;
  /** Small colored dot in the bottom-right corner, e.g. an online/active indicator. */
  indicator?: "success" | "warning" | "danger";
  /** Background/text color — lets a message thread give each party (e.g. client vs. agent) a distinct, consistent color. Defaults to the accent color used everywhere else this component already appears. */
  tone?: Tone;
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
export function Avatar({ name, size = "md", indicator, tone = "accent", className = "" }: AvatarProps) {
  return (
    <div className={`relative flex-none ${className}`}>
      <div
        className={`flex items-center justify-center rounded-full font-semibold ${TONE_CLASSES[tone]} ${SIZE_CLASSES[size]}`}
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
