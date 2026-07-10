"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Minus, Plus, RotateCcw, X } from "lucide-react";

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
import { Skeleton } from "@/components/ui/skeleton";
import { organizationService } from "@/services";
import { useAuthStore } from "@/store/auth-store";

import { OrganizationChart } from "./OrganizationChart";
import { buildHierarchy, HierarchyNode } from "./hierarchy-builder";

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2;
const ZOOM_STEP = 0.1;

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
  const [zoom, setZoom] = useState(1);

  const chartQuery = useQuery({
    queryKey: ["organization-chart"],
    queryFn: organizationService.getMyChart,
    enabled: open,
  });

  useEffect(() => {
    if (!open) {
      setSelectedNode(null);
      setZoom(1);
    }
  }, [open]);

  const zoomIn = () => setZoom((z) => Math.min(MAX_ZOOM, +(z + ZOOM_STEP).toFixed(2)));
  const zoomOut = () => setZoom((z) => Math.max(MIN_ZOOM, +(z - ZOOM_STEP).toFixed(2)));
  const resetZoom = () => setZoom(1);

  const hierarchy =
    chartQuery.data && currentUserId
      ? buildHierarchy(chartQuery.data, currentUserId)
      : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] w-[95vw] max-w-5xl flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle>Organization Chart</DialogTitle>
        </DialogHeader>

        {chartQuery.isLoading && (
          <div className="flex flex-col items-center gap-4 py-10">
            <Skeleton className="h-24 w-56 rounded-xl" />
            <div className="flex gap-4">
              <Skeleton className="h-24 w-56 rounded-xl" />
              <Skeleton className="h-24 w-56 rounded-xl" />
            </div>
          </div>
        )}

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
            {/* Outer wrapper never scrolls — it's purely the positioning
                context for the zoom controls, so they stay fixed in place
                no matter how the chart underneath is panned, scrolled, or
                zoomed. Only the inner div scrolls. */}
            <div className="relative flex-1 overflow-hidden rounded-lg border border-border bg-muted/20">
              <div className="h-full w-full overflow-auto p-8">
                <motion.div
                  animate={{ scale: zoom }}
                  transition={{ type: "spring", stiffness: 300, damping: 30 }}
                  style={{ transformOrigin: "top center" }}
                >
                  <OrganizationChart
                    node={hierarchy}
                    selectedNodeId={selectedNode?.user_id ?? null}
                    onSelectNode={(node) =>
                      setSelectedNode((prev) =>
                        prev?.user_id === node.user_id ? null : node
                      )
                    }
                  />
                </motion.div>
              </div>

              <div className="absolute bottom-4 left-4 flex items-center gap-1 rounded-lg border border-border bg-card/95 p-1 shadow-md backdrop-blur">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={zoomOut}
                  disabled={zoom <= MIN_ZOOM}
                  aria-label="Zoom out"
                >
                  <Minus className="h-4 w-4" />
                </Button>
                <span className="w-12 text-center text-xs font-medium tabular-nums text-muted-foreground">
                  {Math.round(zoom * 100)}%
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={zoomIn}
                  disabled={zoom >= MAX_ZOOM}
                  aria-label="Zoom in"
                >
                  <Plus className="h-4 w-4" />
                </Button>
                <div className="mx-1 h-5 w-px bg-border" />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={resetZoom}
                  aria-label="Reset zoom"
                >
                  <RotateCcw className="h-4 w-4" />
                </Button>
              </div>
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

                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">
                        Direct reports
                      </span>
                      <span>{selectedNode.children.length}</span>
                    </div>
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
