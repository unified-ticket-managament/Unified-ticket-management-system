import { HierarchyNode } from "../hierarchy-builder";

/**
 * Case-insensitive substring match against name/email/role/department,
 * returning real person ids (`user_id`), not occurrence ids — so every
 * occurrence of a duplicated match (see layout.ts's occurrence-id
 * scheme) highlights, not just one.
 */
export function findMatchingUserIds(root: HierarchyNode, query: string): Set<string> {
  const matched = new Set<string>();
  const needle = query.trim().toLowerCase();
  if (!needle) return matched;

  const visit = (node: HierarchyNode) => {
    const haystack = [node.name, node.email, node.role, node.department ?? ""].join(" ").toLowerCase();
    if (haystack.includes(needle)) matched.add(node.user_id);
    node.children.forEach(visit);
  };
  visit(root);
  return matched;
}

/**
 * Every occurrence id (see layout.ts) that is a strict ancestor of a
 * matched person — i.e. every collapsedIds entry that must be removed
 * for all matches to be visible. A cheap DFS building the same
 * root-to-node occurrence-id path scheme layout.ts's own
 * buildVisibleTree/collectParentIds use, so the ids line up exactly
 * with what OrgChartCanvas's `collapsedIds` state is keyed on.
 */
export function findAncestorOccurrenceIds(
  root: HierarchyNode,
  matchedUserIds: ReadonlySet<string>
): Set<string> {
  const ancestorIds = new Set<string>();
  if (matchedUserIds.size === 0) return ancestorIds;

  // Returns true if `node` or anything beneath it is a match.
  const visit = (node: HierarchyNode, occurrenceId: string, pathIds: string[]): boolean => {
    const selfMatches = matchedUserIds.has(node.user_id);
    let childMatches = false;
    node.children.forEach((child, index) => {
      const childOccurrenceId = `${occurrenceId}/${child.user_id}#${index}`;
      if (visit(child, childOccurrenceId, [...pathIds, occurrenceId])) childMatches = true;
    });

    if (childMatches) {
      pathIds.forEach((id) => ancestorIds.add(id));
      ancestorIds.add(occurrenceId);
    }
    return selfMatches || childMatches;
  };

  visit(root, root.user_id, []);
  return ancestorIds;
}
