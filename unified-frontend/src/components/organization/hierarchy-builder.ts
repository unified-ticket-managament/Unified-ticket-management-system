import { OrganizationNode } from "@/types";

export interface HierarchyNode extends OrganizationNode {
  isMe: boolean;
  children: HierarchyNode[];
}

/**
 * Annotates the raw organization tree returned by the API with
 * client-only view state (currently just `isMe`), without mutating
 * the source data.
 */
export function buildHierarchy(
  node: OrganizationNode,
  currentUserId: string
): HierarchyNode {
  return {
    ...node,
    isMe: node.user_id === currentUserId,
    children: node.children.map((child) =>
      buildHierarchy(child, currentUserId)
    ),
  };
}

/** Finds the `isMe` node anywhere in the tree — used to auto-center the org chart on the viewer when it first opens. */
export function findMeNode(node: HierarchyNode): HierarchyNode | null {
  if (node.isMe) return node;
  for (const child of node.children) {
    const found = findMeNode(child);
    if (found) return found;
  }
  return null;
}
