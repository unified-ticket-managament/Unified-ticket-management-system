"use client";

import { forwardRef, useImperativeHandle, useRef, useState } from "react";

import { HierarchyNode } from "./hierarchy-builder";
import { OrgChartCanvas, OrgChartCanvasHandle } from "./org-chart/OrgChartCanvas";
import { OrgChartToolbar } from "./org-chart/OrgChartToolbar";

interface OrganizationChartProps {
  node: HierarchyNode;
  selectedNodeId: string | null;
  onSelectNode: (node: HierarchyNode) => void;
  matchedIds?: Set<string> | null;
}

export type OrganizationChartHandle = OrgChartCanvasHandle;

/**
 * Scalable SVG-based org chart: a d3-hierarchy tree layout rendered as
 * SVG (crisp at any zoom level/DPI), with d3-zoom driving mouse-wheel
 * zoom, pinch zoom, and click-and-drag pan directly, plus a floating
 * toolbar for the same actions as explicit buttons. Replaces the
 * previous plain nested-<div> recursive renderer — same external
 * props contract (`node`/`selectedNodeId`/`onSelectNode`), so
 * OrganizationModal's data-fetching and Details side panel are
 * unchanged. The initial view auto-fits the whole hierarchy (see
 * OrgChartCanvas's own comment) rather than centering on any one
 * node, so this component no longer needs to resolve a "ME" node
 * itself for that purpose.
 *
 * Forwards the underlying canvas's imperative handle (forwardRef +
 * useImperativeHandle) so a parent — OrganizationModal — can trigger
 * e.g. focusFirstMatch() for an explicit "jump to first search match"
 * action without this component needing its own duplicate API.
 */
export const OrganizationChart = forwardRef<OrganizationChartHandle, OrganizationChartProps>(
  function OrganizationChart({ node, selectedNodeId, onSelectNode, matchedIds }, ref) {
    const canvasRef = useRef<OrgChartCanvasHandle>(null);
    const [zoomPercent, setZoomPercent] = useState(100);

    useImperativeHandle(ref, () => ({
      zoomIn: () => canvasRef.current?.zoomIn(),
      zoomOut: () => canvasRef.current?.zoomOut(),
      resetZoom: () => canvasRef.current?.resetZoom(),
      fitToScreen: () => canvasRef.current?.fitToScreen(),
      centerOnRoot: () => canvasRef.current?.centerOnRoot(),
      expandAll: () => canvasRef.current?.expandAll(),
      collapseAll: () => canvasRef.current?.collapseAll(),
      focusFirstMatch: () => canvasRef.current?.focusFirstMatch(),
    }));

    return (
      <div className="relative h-full w-full overflow-hidden">
        <OrgChartCanvas
          ref={canvasRef}
          root={node}
          selectedNodeId={selectedNodeId}
          onSelectNode={onSelectNode}
          onZoomPercentChange={setZoomPercent}
          matchedIds={matchedIds}
        />

        <OrgChartToolbar
          zoomPercent={zoomPercent}
          onZoomIn={() => canvasRef.current?.zoomIn()}
          onZoomOut={() => canvasRef.current?.zoomOut()}
          onReset={() => canvasRef.current?.resetZoom()}
          onFitToScreen={() => canvasRef.current?.fitToScreen()}
          onCenterOnRoot={() => canvasRef.current?.centerOnRoot()}
          onExpandAll={() => canvasRef.current?.expandAll()}
          onCollapseAll={() => canvasRef.current?.collapseAll()}
        />
      </div>
    );
  }
);
