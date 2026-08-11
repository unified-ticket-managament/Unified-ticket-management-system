"use client";

import { Crown, Users, UserCog, UserCheck } from "lucide-react";

import { OrgStats } from "./stats";

interface OrgChartStatsBarProps {
  stats: OrgStats;
}

function StatItem({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="h-4 w-4 text-muted-foreground" />
      <span className="text-sm font-semibold text-foreground">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

/** Compact inline headcount summary row — sized for the org-chart modal's header, not the dashboard's full-grid StatCard. */
export function OrgChartStatsBar({ stats }: OrgChartStatsBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
      <StatItem icon={Users} label="Headcount" value={stats.totalHeadcount} />
      <StatItem icon={UserCheck} label="Direct reports" value={stats.directReports} />
      <StatItem icon={Crown} label="Leads/Managers" value={stats.leadsCount} />
      <StatItem icon={UserCog} label="ICs" value={stats.individualContributorCount} />
    </div>
  );
}
