"use client";

import { ReactNode } from "react";
import { motion } from "framer-motion";
import { LucideIcon, ShieldAlert, TrendingDown, TrendingUp } from "lucide-react";

import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth-store";

export function AccessDenied({
  message = "You don't have permission to view this page.",
}: {
  message?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-destructive/40 bg-destructive/5 py-20 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-destructive/10 text-destructive">
        <ShieldAlert className="h-7 w-7" />
      </div>
      <h1 className="mt-4 text-2xl font-bold tracking-tight">403 — Access Denied</h1>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">{message}</p>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-16 text-center">
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">{description}</p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-6 text-center text-destructive">
      {message}
    </div>
  );
}

const STAT_CARD_TONE_CLASSES = {
  default: "bg-primary/10 text-primary",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  danger: "bg-destructive/10 text-destructive",
} as const;

export function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  trend,
  tone = "default",
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: LucideIcon;
  trend?: { value: string; direction: "up" | "down" };
  tone?: keyof typeof STAT_CARD_TONE_CLASSES;
}) {
  return (
    <motion.div
      whileHover={{ y: -4 }}
      transition={{ type: "spring", stiffness: 300, damping: 22 }}
      className="rounded-xl border border-border bg-card p-6 shadow-sm transition-shadow hover:shadow-md"
    >
      <div className="flex items-start justify-between">
        <p className="text-sm text-muted-foreground">{title}</p>
        {Icon && (
          <div className={cn("flex h-9 w-9 items-center justify-center rounded-lg", STAT_CARD_TONE_CLASSES[tone])}>
            <Icon className="h-5 w-5" />
          </div>
        )}
      </div>

      <p className="mt-3 text-3xl font-bold tracking-tight">{value}</p>

      <div className="mt-1 flex items-center gap-2">
        {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
        {trend && (
          <span
            className={cn(
              "flex items-center gap-0.5 text-xs font-medium",
              trend.direction === "up" ? "text-emerald-500" : "text-red-500"
            )}
          >
            {trend.direction === "up" ? (
              <TrendingUp className="h-3 w-3" />
            ) : (
              <TrendingDown className="h-3 w-3" />
            )}
            {trend.value}
          </span>
        )}
      </div>
    </motion.div>
  );
}

export function usePermissions() {
  const hasPermission = useAuthStore((s) => s.hasPermission);
  const hasAnyPermission = useAuthStore((s) => s.hasAnyPermission);
  const user = useAuthStore((s) => s.user);
  return { hasPermission, hasAnyPermission, user };
}
