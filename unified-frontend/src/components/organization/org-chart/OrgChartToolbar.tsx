"use client";

import { Crosshair, FoldVertical, Maximize, Minus, Plus, RotateCcw, UnfoldVertical } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface OrgChartToolbarProps {
  zoomPercent: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onReset: () => void;
  onFitToScreen: () => void;
  onCenterOnRoot: () => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
}

function ToolbarButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onClick}
          aria-label={label}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}

/** Floating zoom/pan/expand controls for OrgChartCanvas — occupies the same bottom-left slot the previous zoom-only control bar used. */
export function OrgChartToolbar({
  zoomPercent,
  onZoomIn,
  onZoomOut,
  onReset,
  onFitToScreen,
  onCenterOnRoot,
  onExpandAll,
  onCollapseAll,
}: OrgChartToolbarProps) {
  return (
    <TooltipProvider delayDuration={200}>
      <div className="absolute bottom-4 left-4 flex items-center gap-1 rounded-lg border border-border bg-card/95 p-1 shadow-md backdrop-blur">
        <ToolbarButton label="Zoom out" onClick={onZoomOut}>
          <Minus className="h-4 w-4" />
        </ToolbarButton>

        <span className="w-12 text-center text-xs font-medium tabular-nums text-muted-foreground">
          {zoomPercent}%
        </span>

        <ToolbarButton label="Zoom in" onClick={onZoomIn}>
          <Plus className="h-4 w-4" />
        </ToolbarButton>

        <div className="mx-1 h-5 w-px bg-border" />

        <ToolbarButton label="Reset zoom" onClick={onReset}>
          <RotateCcw className="h-4 w-4" />
        </ToolbarButton>

        <ToolbarButton label="Fit to screen" onClick={onFitToScreen}>
          <Maximize className="h-4 w-4" />
        </ToolbarButton>

        <ToolbarButton label="Center on root" onClick={onCenterOnRoot}>
          <Crosshair className="h-4 w-4" />
        </ToolbarButton>

        <div className="mx-1 h-5 w-px bg-border" />

        <ToolbarButton label="Expand all" onClick={onExpandAll}>
          <UnfoldVertical className="h-4 w-4" />
        </ToolbarButton>

        <ToolbarButton label="Collapse all" onClick={onCollapseAll}>
          <FoldVertical className="h-4 w-4" />
        </ToolbarButton>
      </div>
    </TooltipProvider>
  );
}
