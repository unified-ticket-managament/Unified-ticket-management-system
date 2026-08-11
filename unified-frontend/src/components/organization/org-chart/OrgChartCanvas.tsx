"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";

import { HierarchyNode } from "../hierarchy-builder";
import {
  collectParentIds,
  computeOrgLayout,
  getAncestorChain,
  NODE_HEIGHT,
  NODE_WIDTH,
  OrgLayoutLink,
} from "./layout";
import { findAncestorOccurrenceIds } from "./search";
import { MAX_SCALE, MIN_SCALE, useZoomPan } from "./useZoomPan";
import { OrgChartNodeCard } from "./OrgChartNodeCard";

const FIT_PADDING = 56;

export interface OrgChartCanvasHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  resetZoom: () => void;
  fitToScreen: () => void;
  centerOnRoot: () => void;
  expandAll: () => void;
  collapseAll: () => void;
  focusFirstMatch: () => void;
}

interface OrgChartCanvasProps {
  root: HierarchyNode;
  selectedNodeId: string | null;
  onSelectNode: (node: HierarchyNode) => void;
  onZoomPercentChange?: (percent: number) => void;
  matchedIds?: Set<string> | null;
}

function elbowPath(source: { x: number; y: number }, target: { x: number; y: number }): string {
  const sourceBottomY = source.y + NODE_HEIGHT / 2;
  const targetTopY = target.y - NODE_HEIGHT / 2;
  const midY = (sourceBottomY + targetTopY) / 2;
  return `M${source.x},${sourceBottomY} V${midY} H${target.x} V${targetTopY}`;
}

function edgeClassName(relationship: OrgLayoutLink["relationship"]): string {
  switch (relationship) {
    case "reporting_manager":
      return "text-muted-foreground/50 [stroke-dasharray:6_4]";
    case "assignable":
      return "text-muted-foreground/30 [stroke-dasharray:1.5_4]";
    default:
      return "text-border";
  }
}

export const OrgChartCanvas = forwardRef<OrgChartCanvasHandle, OrgChartCanvasProps>(
  function OrgChartCanvas(
    { root, selectedNodeId, onSelectNode, onZoomPercentChange, matchedIds },
    ref
  ) {
    const svgRef = useRef<SVGSVGElement>(null);
    const { transform, applyTransform, zoomBy } = useZoomPan(svgRef);

    const [collapsedIds, setCollapsedIds] = useState<Set<string>>(() => new Set());
    const [hoveredId, setHoveredId] = useState<string | null>(null);

    const layout = useMemo(() => computeOrgLayout(root, collapsedIds), [root, collapsedIds]);

    const highlightedIds = useMemo(
      () => (hoveredId ? getAncestorChain(hoveredId, layout.nodesById) : null),
      [hoveredId, layout.nodesById]
    );

    useEffect(() => {
      onZoomPercentChange?.(Math.round(transform.k * 100));
    }, [transform.k, onZoomPercentChange]);

    // Auto-reveal every match: only ever REMOVE ids from collapsedIds
    // when the match set changes, never add — a manual collapse the
    // user makes afterward is respected until the query changes again.
    useEffect(() => {
      if (!matchedIds || matchedIds.size === 0) return;
      const ancestorIds = findAncestorOccurrenceIds(root, matchedIds);
      if (ancestorIds.size === 0) return;
      setCollapsedIds((prev) => {
        let changed = false;
        const next = new Set(prev);
        ancestorIds.forEach((id) => {
          if (next.delete(id)) changed = true;
        });
        return changed ? next : prev;
      });
    }, [matchedIds, root]);

    const centerOn = useCallback(
      (x: number, y: number, k: number, animate = true) => {
        const svgEl = svgRef.current;
        if (!svgEl) return;
        const containerW = svgEl.clientWidth;
        const containerH = svgEl.clientHeight;
        applyTransform({ x: containerW / 2 - x * k, y: containerH / 2 - y * k, k }, animate);
      },
      [applyTransform]
    );

    // Shared by the toolbar's explicit "Fit to screen" button AND the
    // initial auto-view below — fits the ENTIRE laid-out tree (every
    // ancestor above the viewer plus their full descendant subtree,
    // computeOrgLayout already includes both) into the viewport, so
    // opening the chart shows the complete bidirectional hierarchy at
    // once rather than only whatever's near the viewer at 100% zoom.
    const fitToScreen = useCallback(
      (animate = true) => {
        const svgEl = svgRef.current;
        if (!svgEl || layout.nodes.length === 0) return;

        const minX = Math.min(...layout.nodes.map((n) => n.x)) - NODE_WIDTH / 2;
        const maxX = Math.max(...layout.nodes.map((n) => n.x)) + NODE_WIDTH / 2;
        const minY = Math.min(...layout.nodes.map((n) => n.y)) - NODE_HEIGHT / 2;
        const maxY = Math.max(...layout.nodes.map((n) => n.y)) + NODE_HEIGHT / 2;

        const containerW = svgEl.clientWidth;
        const containerH = svgEl.clientHeight;
        const bboxW = Math.max(maxX - minX, 1);
        const bboxH = Math.max(maxY - minY, 1);

        const scale = Math.min(
          (containerW - FIT_PADDING * 2) / bboxW,
          (containerH - FIT_PADDING * 2) / bboxH,
          MAX_SCALE
        );
        const k = Math.max(scale, MIN_SCALE);

        centerOn((minX + maxX) / 2, (minY + maxY) / 2, k, animate);
      },
      [layout.nodes, centerOn]
    );

    useImperativeHandle(
      ref,
      () => ({
        zoomIn: () => zoomBy(1.3),
        zoomOut: () => zoomBy(1 / 1.3),
        resetZoom: () => {
          const rootNode = layout.nodes.find((n) => n.depth === 0);
          if (rootNode) centerOn(rootNode.x, rootNode.y, 1);
          else applyTransform({ x: 0, y: 0, k: 1 });
        },
        fitToScreen: () => fitToScreen(),
        centerOnRoot: () => {
          const rootNode = layout.nodes.find((n) => n.depth === 0);
          if (rootNode) centerOn(rootNode.x, rootNode.y, transform.k);
        },
        expandAll: () => setCollapsedIds(new Set()),
        collapseAll: () => setCollapsedIds(collectParentIds(root)),
        focusFirstMatch: () => {
          if (!matchedIds || matchedIds.size === 0) return;
          const target = layout.nodes.find((n) => matchedIds.has(n.data.user_id));
          if (target) centerOn(target.x, target.y, Math.max(transform.k, 1));
        },
      }),
      [layout.nodes, root, applyTransform, centerOn, zoomBy, transform.k, matchedIds, fitToScreen]
    );

    // Auto-fit the ENTIRE hierarchy (every ancestor above the viewer
    // plus their full descendant subtree — one nested tree already
    // combining both, see OrganizationService.get_chart_for_user) into
    // view the first time this root is laid out. Previously this
    // centered on just the viewer's own node at a fixed 100% zoom,
    // which for anyone with many direct reports made the initial view
    // look descendant-only even though the ancestor chain was already
    // present in the data — a real, if purely visual, bug: the whole
    // point of this chart is "where am I in the organization," which
    // requires seeing both directions at once, not just the crowded
    // side. The viewer's own node stays identifiable via its permanent
    // "ME" badge/border (OrgChartNodeCard), not via camera position.
    const hasAutoFocused = useRef(false);
    useEffect(() => {
      hasAutoFocused.current = false;
    }, [root]);

    useEffect(() => {
      if (hasAutoFocused.current) return;
      if (layout.nodes.length === 0 || !svgRef.current) return;

      hasAutoFocused.current = true;
      const timer = setTimeout(() => fitToScreen(false), 60);
      return () => clearTimeout(timer);
    }, [layout.nodes, fitToScreen]);

    return (
      <svg
        ref={svgRef}
        className="h-full w-full touch-none select-none"
        role="img"
        aria-label="Organization chart"
      >
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          <g>
            {layout.links.map((link) => {
              const isInChain =
                highlightedIds !== null &&
                highlightedIds.has(link.sourceId) &&
                highlightedIds.has(link.targetId);
              return (
                <path
                  key={link.id}
                  d={elbowPath(link.source, link.target)}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={isInChain ? 2.5 : 1.5}
                  className={[
                    edgeClassName(link.relationship),
                    highlightedIds !== null && !isInChain ? "opacity-30" : "opacity-100",
                  ].join(" ")}
                />
              );
            })}
          </g>

          <g>
            {layout.nodes.map((n) => (
              <OrgChartNodeCard
                key={n.id}
                node={n.data}
                x={n.x}
                y={n.y}
                // selectedNodeId (from the Details panel) is the
                // person's real user_id, not an occurrence id — see
                // the focusNodeId resolution above for why the two
                // can't be compared directly. Matching by user_id also
                // means both occurrences of a duplicated person get
                // the selected ring, which is arguably more correct:
                // the Details panel is about the person, not the
                // specific position clicked.
                isSelected={selectedNodeId === n.data.user_id}
                isMatched={!!matchedIds?.has(n.data.user_id)}
                hasChildren={n.hasChildren}
                isCollapsed={n.isCollapsed}
                isDimmed={highlightedIds !== null && !highlightedIds.has(n.id)}
                onSelect={() => onSelectNode(n.data)}
                onDoubleClick={() => centerOn(n.x, n.y, transform.k)}
                onToggleExpand={() =>
                  setCollapsedIds((prev) => {
                    const next = new Set(prev);
                    if (next.has(n.id)) next.delete(n.id);
                    else next.add(n.id);
                    return next;
                  })
                }
                onMouseEnter={() => setHoveredId(n.id)}
                onMouseLeave={() => setHoveredId((current) => (current === n.id ? null : current))}
              />
            ))}
          </g>
        </g>
      </svg>
    );
  }
);
