"use client";

import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Maximize2, Minimize2, Search, X } from "lucide-react";

import { EmptyState, ErrorState } from "@/components/shared/stats";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { WorkflowLoader } from "@/components/common/WorkflowLoader";
import { cn } from "@/lib/utils";
import { organizationService } from "@/services";
import { useAuthStore } from "@/store/auth-store";

import { OrganizationChart, OrganizationChartHandle } from "./OrganizationChart";
import { buildHierarchy, findMeNode, HierarchyNode } from "./hierarchy-builder";
import { OrgChartLegend } from "./org-chart/OrgChartLegend";
import { OrgChartStatsBar } from "./org-chart/OrgChartStatsBar";
import { computeDepartmentCounts, computeOrgStats } from "./org-chart/stats";
import { findMatchingUserIds } from "./org-chart/search";

interface OrganizationModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function OrganizationModal({
  open,
  onOpenChange,
}: OrganizationModalProps) {
  const currentUserId = useAuthStore((s) => s.user?.user_id);
  const [selectedNode, setSelectedNode] = useState<HierarchyNode | null>(null);
  const [isMaximized, setIsMaximized] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const chartRef = useRef<OrganizationChartHandle>(null);

  const chartQuery = useQuery({
    queryKey: ["organization-chart"],
    queryFn: organizationService.getMyChart,
    enabled: open,
  });

  // Reset on close is driven by the Dialog's own open-change event,
  // not a useEffect watching `open` — calling setState synchronously
  // inside an effect body just to react to a prop that already fires
  // its own event is the exact anti-pattern React's
  // react-hooks/set-state-in-effect rule flags.
  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setSelectedNode(null);
      setIsMaximized(false);
      setSearchQuery("");
    }
    onOpenChange(nextOpen);
  };

  const hierarchy =
    chartQuery.data && currentUserId
      ? buildHierarchy(chartQuery.data, currentUserId)
      : null;

  const stats = useMemo(() => (hierarchy ? computeOrgStats(hierarchy) : null), [hierarchy]);
  const departmentCounts = useMemo(
    () => (hierarchy ? computeDepartmentCounts(hierarchy) : []),
    [hierarchy]
  );
  const matchedIds = useMemo(
    () => (hierarchy ? findMatchingUserIds(hierarchy, searchQuery) : new Set<string>()),
    [hierarchy, searchQuery]
  );
  const hasSearch = searchQuery.trim().length > 0;

  // The chart is now rooted at the viewed user's topmost real
  // manager_id/teamlead_id ancestor (see OrganizationService — no more
  // company-wide, role-implied tree) — so "does this user have a
  // reporting manager" is simply "is the tree root someone other than
  // them," and "does this user have direct reports" is just whether
  // their own node in that tree has children. Neither is an error
  // state (a top-of-company user genuinely has no manager; a Staff
  // member genuinely may have no reports).
  const meNode = hierarchy ? findMeNode(hierarchy) : null;
  const hasReportingManager = !!hierarchy && !!currentUserId && hierarchy.user_id !== currentUserId;
  const hasDirectReports = !!meNode && meNode.children.length > 0;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className={cn(
          "flex flex-col overflow-hidden",
          isMaximized
            ? "h-[96vh] w-[98vw] max-w-none"
            : "max-h-[85vh] w-[95vw] max-w-5xl"
        )}
      >
        <button
          type="button"
          onClick={() => setIsMaximized((prev) => !prev)}
          className="absolute right-12 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100"
          aria-label={isMaximized ? "Restore" : "Maximize"}
        >
          {isMaximized ? (
            <Minimize2 className="h-4 w-4" />
          ) : (
            <Maximize2 className="h-4 w-4" />
          )}
        </button>

        <DialogHeader>
          <DialogTitle>Organization Chart</DialogTitle>
        </DialogHeader>

        {hierarchy && meNode && (!hasReportingManager || !hasDirectReports) && (
          <div className="flex flex-wrap gap-x-4 gap-y-1 px-1 text-xs text-muted-foreground">
            {!hasReportingManager && <span>No reporting manager assigned</span>}
            {!hasDirectReports && <span>No direct reports</span>}
          </div>
        )}

        {isMaximized && hierarchy && stats && (
          <div className="flex flex-col gap-3 border-b border-border pb-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <OrgChartStatsBar stats={stats} />

              <div className="flex items-center gap-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") chartRef.current?.focusFirstMatch();
                    }}
                    placeholder="Search name, email, role, department…"
                    className="h-8 w-64 pl-8 text-sm"
                  />
                </div>
                {hasSearch && (
                  <>
                    <span className="whitespace-nowrap text-xs text-muted-foreground">
                      {matchedIds.size} {matchedIds.size === 1 ? "match" : "matches"}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8"
                      disabled={matchedIds.size === 0}
                      onClick={() => chartRef.current?.focusFirstMatch()}
                    >
                      Jump to first
                    </Button>
                  </>
                )}
              </div>
            </div>

            <OrgChartLegend departmentCounts={departmentCounts} />
          </div>
        )}

        {chartQuery.isLoading && <WorkflowLoader loading size={56} className="min-h-[320px]" />}

        {chartQuery.isError && (
          <ErrorState message="Failed to load the organization chart." />
        )}

        {chartQuery.isSuccess && !hierarchy && (
          <EmptyState
            title="No organization data"
            description="We couldn't find your position in the organization chart."
          />
        )}

        {hierarchy && (
          <div className="flex flex-1 flex-col gap-4 overflow-hidden md:flex-row">
            {/* OrganizationChart owns its own zoom/pan (mouse wheel,
                pinch, drag-to-pan) and floating toolbar now — this is
                purely its sizing/border context. */}
            <div className="relative flex-1 overflow-hidden rounded-lg border border-border bg-muted/20">
              <OrganizationChart
                ref={chartRef}
                node={hierarchy}
                selectedNodeId={selectedNode?.user_id ?? null}
                onSelectNode={(node) =>
                  setSelectedNode((prev) =>
                    prev?.user_id === node.user_id ? null : node
                  )
                }
                matchedIds={hasSearch ? matchedIds : null}
              />
            </div>

            {selectedNode && (
              <Card className="w-full shrink-0 md:w-72">
                <CardHeader className="flex-row items-start justify-between space-y-0">
                  <CardTitle className="text-base">Details</CardTitle>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => setSelectedNode(null)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center gap-3">
                    <Avatar className="h-10 w-10">
                      <AvatarFallback>
                        {selectedNode.name.charAt(0).toUpperCase()}
                      </AvatarFallback>
                    </Avatar>
                    <div>
                      <p className="text-sm font-semibold">
                        {selectedNode.name}
                        {selectedNode.isMe && (
                          <Badge className="ml-2 align-middle">ME</Badge>
                        )}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {selectedNode.email}
                      </p>
                    </div>
                  </div>

                  <div className="space-y-2 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Role</span>
                      <Badge variant="secondary">{selectedNode.role}</Badge>
                    </div>

                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Status</span>
                      <Badge
                        variant={
                          selectedNode.is_active ? "success" : "destructive"
                        }
                      >
                        {selectedNode.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </div>

                    {selectedNode.department && (
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">
                          Department
                        </span>
                        <span>{selectedNode.department}</span>
                      </div>
                    )}

                    {selectedNode.relationship_to_parent === "reporting_manager" && (
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">
                          Relationship
                        </span>
                        <Badge variant="outline">Reporting Manager branch</Badge>
                      </div>
                    )}

                    {selectedNode.relationship_to_parent === "assignable" && (
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">
                          Relationship
                        </span>
                        <Badge variant="outline">Ticket-assignment only</Badge>
                      </div>
                    )}

                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">
                        Direct reports
                      </span>
                      <span>{selectedNode.children.length}</span>
                    </div>

                    {selectedNode.reporting_manager_for &&
                      selectedNode.reporting_manager_for.length > 0 && (
                        <div className="space-y-1.5">
                          <span className="text-muted-foreground">
                            Reporting Manager for
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {selectedNode.reporting_manager_for.map((category) => (
                              <Badge key={category} variant="secondary">
                                {category}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
