import type { ReactNode } from "react";

type Tone = "default" | "success" | "warning" | "danger" | "info" | "accent";

interface BadgeProps {
  children: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  dot?: boolean;
}

const toneClasses: Record<Tone, string> = {
  default: "bg-slate-100 text-slate-600 border-slate-200/80",
  success: "bg-success/10 text-success border-success/15",
  warning: "bg-warning/10 text-warning border-warning/15",
  danger: "bg-danger/10 text-danger border-danger/15",
  info: "bg-info/10 text-info border-info/15",
  accent: "bg-accent/10 text-accent border-accent/15",
};

const dotClasses: Record<Tone, string> = {
  default: "bg-slate-400",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
  accent: "bg-accent",
};

export function Badge({ children, tone = "default", icon, dot }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold leading-none tracking-wide ${toneClasses[tone]}`}
    >
      {dot && <span className={`h-1.5 w-1.5 flex-none rounded-full ${dotClasses[tone]}`} />}
      {icon}
      {children}
    </span>
  );
}
