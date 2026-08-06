"use client";

import { useRef, useState } from "react";

import { findMeNode, HierarchyNode } from "./hierarchy-builder";
import { OrgChartCanvas, OrgChartCanvasHandle } from "./org-chart/OrgChartCanvas";
import { OrgChartToolbar } from "./org-chart/OrgChartToolbar";

interface OrganizationChartProps {
  node: HierarchyNode;
  selectedNodeId: string | null;
  onSelectNode: (node: HierarchyNode) => void;
}

/**
 * Scalable SVG-based org chart: a d3-hierarchy tree layout rendered as
 * SVG (crisp at any zoom level/DPI), with d3-zoom driving mouse-wheel
 * zoom, pinch zoom, and click-and-drag pan directly, plus a floating
 * toolbar for the same actions as explicit buttons. Replaces the
 * previous plain nested-<div> recursive renderer — same external
 * props contract (`node`/`selectedNodeId`/`onSelectNode`), so
 * OrganizationModal's data-fetching, "ME" auto-focus, and Details side
 * panel are unchanged.
 */
export function OrganizationChart({
  node,
  selectedNodeId,
  onSelectNode,
}: OrganizationChartProps) {
  const canvasRef = useRef<OrgChartCanvasHandle>(null);
  const [zoomPercent, setZoomPercent] = useState(100);

  const meNode = findMeNode(node);

  return (
    <div className="relative h-full w-full overflow-hidden">
      <OrgChartCanvas
        ref={canvasRef}
        root={node}
        selectedNodeId={selectedNodeId}
        onSelectNode={onSelectNode}
        focusNodeId={meNode?.user_id ?? node.user_id}
        onZoomPercentChange={setZoomPercent}
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
