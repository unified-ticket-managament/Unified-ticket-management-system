"use client";

import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CategoryBarList } from "@/components/shared/charts";

// Dashboard/Reports-only chart card shell — reuses CategoryBarList
// unchanged for the actual bar rendering/math (no duplicated logic),
// just wraps it in a more spacious, modern header/card treatment and
// an optional colored-dot legend. Scoped to Dashboard/Reports only —
// components/shared/charts.tsx itself is untouched, so the Viewer
// dashboard (which also renders CategoryBarList directly) keeps its
// current look.
export function ModernBarListCard({
  title,
  description,
  icon: Icon,
  data,
  legend,
  className,
}: {
  title: string;
  description?: string;
  icon?: LucideIcon;
  data: { label: string; value: number; color?: string }[];
  legend?: { label: string; dotClassName: string }[];
  className?: string;
}) {
  return (
    <Card className={cn("rounded-md border-border shadow-sm", className)}>
      <CardHeader className="flex-row items-center gap-3 space-y-0">
        {Icon && (
          <div className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-primary/10 text-primary">
            <Icon className="h-4.5 w-4.5" />
          </div>
        )}
        <div className="min-w-0">
          <CardTitle className="text-base">{title}</CardTitle>
          {description && <CardDescription className="mt-0.5">{description}</CardDescription>}
        </div>
      </CardHeader>
      <CardContent>
        <CategoryBarList data={data} />
        {legend && legend.length > 0 && (
          <div className="mt-5 flex flex-wrap gap-x-4 gap-y-2 border-t border-border pt-4">
            {legend.map((item) => (
              <span key={item.label} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span className={cn("h-2 w-2 rounded-full", item.dotClassName)} />
                {item.label}
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
