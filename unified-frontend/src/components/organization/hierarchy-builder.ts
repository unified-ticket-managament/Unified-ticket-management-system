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
