"use client";

import { Badge } from "@/components/ui/badge";

import { DepartmentCount } from "./stats";

interface OrgChartLegendProps {
  departmentCounts: DepartmentCount[];
}

/** Wrapped row of department pills (colored dot + label + count) — omits any department with zero people in the current chart. */
export function OrgChartLegend({ departmentCounts }: OrgChartLegendProps) {
  if (departmentCounts.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {departmentCounts.map((dept) => (
        <Badge key={dept.key} variant="outline" className="gap-1.5 font-normal">
          <span className={`h-2 w-2 rounded-full ${dept.bgClass}`} aria-hidden />
          {dept.label}
          <span className="text-muted-foreground">{dept.count}</span>
        </Badge>
      ))}
    </div>
  );
}
