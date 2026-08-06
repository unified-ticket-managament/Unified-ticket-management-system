import { hierarchy as d3Hierarchy, tree as d3Tree } from "d3-hierarchy";

import { HierarchyNode } from "../hierarchy-builder";

// Fixed node card footprint (must match the foreignObject size
// OrgChartNodeCard is rendered at in OrgChartCanvas) plus the gaps
// between siblings and between depth levels — all in SVG user units.
export const NODE_WIDTH = 224;
export const NODE_HEIGHT = 180;
export const SIBLING_GAP = 40;
export const LEVEL_GAP = 88;

export interface OrgLayoutNode {
  id: string;
  data: HierarchyNode;
  x: number;
  y: number;
  depth: number;
  parentId: string | null;
  hasChildren: boolean;
  isCollapsed: boolean;
}

export interface OrgLayoutLink {
  id: string;
  sourceId: string;
  targetId: string;
  source: { x: number; y: number };
  target: { x: number; y: number };
  relationship: HierarchyNode["relationship_to_parent"];
}

export interface OrgLayoutResult {
  nodes: OrgLayoutNode[];
  links: OrgLayoutLink[];
  nodesById: Map<string, OrgLayoutNode>;
  width: number;
  height: number;
}

// A thin wrapper so d3.hierarchy's own `children` accessor can be
// swapped per-node (an empty array for a collapsed node) without ever
// mutating the real HierarchyNode tree that came back from the API —
// collapsing/expanding is purely a layout-time decision, re-derived
// from `collapsedIds` on every render.
//
// `occurrenceId` (NOT the same as the person's user_id — see below)
// identifies this specific rendered POSITION in the tree, built as a
// path from the root. It exists because the org chart is not
// necessarily a strict tree: the same person can legitimately appear
// more than once under the same parent (e.g. once via the real
// manager_id "reports_to" line, once via a category-matched
// "reporting_manager" edge — both real, independent relationships the
// backend intentionally represents as separate entries — see
// OrganizationService's own "three independent concepts" note). Keying
// nodes/links by raw user_id breaks the moment that happens (React
// "duplicate key" — two nodes/links resolving to the identical id);
// keying by a root-to-node path instead (with a sibling index
// disambiguating same-parent duplicates) is always unique, without
// changing anything about the underlying hierarchy data itself.
interface VisibleNode {
  original: HierarchyNode;
  occurrenceId: string;
  children: VisibleNode[];
}

function buildVisibleTree(
  node: HierarchyNode,
  collapsedOccurrenceIds: ReadonlySet<string>,
  occurrenceId: string
): VisibleNode {
  const isCollapsed = collapsedOccurrenceIds.has(occurrenceId);
  return {
    original: node,
    occurrenceId,
    children: isCollapsed
      ? []
      : node.children.map((child, index) =>
          buildVisibleTree(child, collapsedOccurrenceIds, `${occurrenceId}/${child.user_id}#${index}`)
        ),
  };
}

/**
 * Lays out the (possibly collapsed) org tree top-down using d3's own
 * tree layout algorithm — the hierarchy/positions only, no rendering.
 * Every node with children not in `collapsedIds` has its subtree
 * included; anything collapsed is excluded from the layout entirely
 * (not just visually hidden), so a large collapsed branch costs
 * nothing to lay out or render until it's expanded again.
 */
export function computeOrgLayout(
  root: HierarchyNode,
  collapsedIds: ReadonlySet<string>
): OrgLayoutResult {
  const visibleRoot = buildVisibleTree(root, collapsedIds, root.user_id);
  const rootHierarchy = d3Hierarchy<VisibleNode>(visibleRoot, (d) => d.children);

  const treeLayout = d3Tree<VisibleNode>()
    .nodeSize([NODE_WIDTH + SIBLING_GAP, NODE_HEIGHT + LEVEL_GAP])
    .separation((a, b) => (a.parent === b.parent ? 1 : 1.2));

  const laidOut = treeLayout(rootHierarchy);

  const nodes: OrgLayoutNode[] = [];
  const nodesById = new Map<string, OrgLayoutNode>();
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  laidOut.each((n) => {
    const original = n.data.original;
    const layoutNode: OrgLayoutNode = {
      id: n.data.occurrenceId,
      data: original,
      x: n.x,
      y: n.y,
      depth: n.depth,
      parentId: n.parent ? n.parent.data.occurrenceId : null,
      hasChildren: original.children.length > 0,
      isCollapsed: collapsedIds.has(n.data.occurrenceId),
    };
    nodes.push(layoutNode);
    nodesById.set(layoutNode.id, layoutNode);

    minX = Math.min(minX, n.x);
    maxX = Math.max(maxX, n.x);
    minY = Math.min(minY, n.y);
    maxY = Math.max(maxY, n.y);
  });

  // Shift so the leftmost/topmost node sits at a small fixed padding
  // from (0, 0) — d3.tree() centers the layout on x=0, which would
  // otherwise put negative-x nodes off the top-left of the SVG canvas.
  const offsetX = -minX + NODE_WIDTH / 2 + SIBLING_GAP;
  const offsetY = -minY + NODE_HEIGHT / 2 + LEVEL_GAP / 2;

  nodes.forEach((n) => {
    n.x += offsetX;
    n.y += offsetY;
  });

  const links: OrgLayoutLink[] = [];
  nodes.forEach((n) => {
    if (n.parentId === null) return;
    const parent = nodesById.get(n.parentId);
    if (!parent) return;
    links.push({
      id: `${parent.id}->${n.id}`,
      sourceId: parent.id,
      targetId: n.id,
      source: { x: parent.x, y: parent.y },
      target: { x: n.x, y: n.y },
      relationship: n.data.relationship_to_parent,
    });
  });

  const width = maxX - minX + NODE_WIDTH + SIBLING_GAP * 2;
  const height = maxY - minY + NODE_HEIGHT + LEVEL_GAP;

  return { nodes, links, nodesById, width, height };
}

/** Every ancestor id of `nodeId`, plus `nodeId` itself — the "reporting line" highlighted on hover. */
export function getAncestorChain(nodeId: string, nodesById: Map<string, OrgLayoutNode>): Set<string> {
  const chain = new Set<string>();
  let current = nodesById.get(nodeId) ?? null;
  while (current) {
    chain.add(current.id);
    current = current.parentId ? nodesById.get(current.parentId) ?? null : null;
  }
  return chain;
}

/**
 * Every occurrence id in the full (uncollapsed) tree whose node has at
 * least one child — used by "Collapse All". Builds the same
 * root-to-node path scheme as buildVisibleTree/computeOrgLayout above,
 * so the ids this produces are the exact ones computeOrgLayout will
 * later check `collapsedIds` against for the same tree.
 */
export function collectParentIds(
  node: HierarchyNode,
  occurrenceId: string = node.user_id,
  acc: Set<string> = new Set()
): Set<string> {
  if (node.children.length > 0) {
    acc.add(occurrenceId);
    node.children.forEach((child, index) =>
      collectParentIds(child, `${occurrenceId}/${child.user_id}#${index}`, acc)
    );
  }
  return acc;
}
