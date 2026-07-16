"use client";

import { LucideIcon, TrendingDown, TrendingUp } from "lucide-react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";

// Dashboard/Reports-only KPI tile — a visual-only redesign of
// components/shared/stats.tsx's StatCard, which is reused by ~15 other
// pages (Users, Roles, Audit Logs, Settings, Permission Requests, ...)
// that are explicitly out of scope for this redesign. Deliberately NOT
// a change to StatCard itself, so every other page keeps its current
// look. Same theme tokens as StatCard (bg-card, border-border,
// text-muted-foreground, the existing success/warning/danger tones) —
// only spacing, radius, and typography differ.
const TONE_CLASSES = {
  default: "bg-primary/10 text-primary",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  danger: "bg-destructive/10 text-destructive",
} as const;

export function ModernStatCard({
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
  tone?: keyof typeof TONE_CLASSES;
}) {
  return (
    <motion.div
      whileHover={{ y: -3 }}
      transition={{ type: "spring", stiffness: 300, damping: 22 }}
      className="rounded-md border border-border bg-card p-5 shadow-sm transition-shadow hover:shadow-md"
    >
      {Icon && (
        <div className={cn("flex h-10 w-10 items-center justify-center rounded-full", TONE_CLASSES[tone])}>
          <Icon className="h-5 w-5" />
        </div>
      )}

      <p className={cn("text-sm font-semibold text-foreground", Icon ? "mt-3" : "")}>{title}</p>
      <p className="mt-1.5 text-3xl font-bold leading-none tracking-tight">{value}</p>

      {(subtitle || trend) && (
        <div className="mt-2 flex items-center gap-2">
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
      )}
    </motion.div>
  );
}
