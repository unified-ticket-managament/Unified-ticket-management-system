"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Maximize2, Minimize2, X } from "lucide-react";

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
import { WorkflowLoader } from "@/components/common/WorkflowLoader";
import { cn } from "@/lib/utils";
import { organizationService } from "@/services";
import { useAuthStore } from "@/store/auth-store";

import { OrganizationChart } from "./OrganizationChart";
import { buildHierarchy, HierarchyNode } from "./hierarchy-builder";

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
    }
    onOpenChange(nextOpen);
  };

  const hierarchy =
    chartQuery.data && currentUserId
      ? buildHierarchy(chartQuery.data, currentUserId)
      : null;

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
                node={hierarchy}
                selectedNodeId={selectedNode?.user_id ?? null}
                onSelectNode={(node) =>
                  setSelectedNode((prev) =>
                    prev?.user_id === node.user_id ? null : node
                  )
                }
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
