import { HierarchyNode } from "../hierarchy-builder";
import { ALL_DEPARTMENTS, getDepartmentInfo } from "./department-colors";

export interface OrgStats {
  totalHeadcount: number;
  directReports: number;
  leadsCount: number;
  individualContributorCount: number;
}

export interface DepartmentCount {
  key: string;
  label: string;
  count: number;
  bgClass: string;
}

const LEAD_ROLE_NAMES = new Set(["Super Admin", "Site Lead", "Account Manager", "Team Lead"]);

/**
 * Collects every distinct real person (by `user_id`, never by tree-node
 * count) in the tree — a person can legitimately appear at more than
 * one occurrence (once via reports_to, once via reporting_manager/
 * assignable, see layout.ts), and every stat/legend total below must
 * count them exactly once.
 */
function collectDistinctPeople(root: HierarchyNode): Map<string, HierarchyNode> {
  const byId = new Map<string, HierarchyNode>();
  const visit = (node: HierarchyNode) => {
    if (!byId.has(node.user_id)) byId.set(node.user_id, node);
    node.children.forEach(visit);
  };
  visit(root);
  return byId;
}

export function computeOrgStats(root: HierarchyNode): OrgStats {
  const people = [...collectDistinctPeople(root).values()];
  const leadsCount = people.filter((p) => LEAD_ROLE_NAMES.has(p.role)).length;
  return {
    totalHeadcount: people.length,
    directReports: root.children.length,
    leadsCount,
    individualContributorCount: people.length - leadsCount,
  };
}

export function computeDepartmentCounts(root: HierarchyNode): DepartmentCount[] {
  const people = [...collectDistinctPeople(root).values()];
  const counts = new Map<string, number>();
  for (const person of people) {
    const info = getDepartmentInfo(person.department);
    counts.set(info.key, (counts.get(info.key) ?? 0) + 1);
  }

  return ALL_DEPARTMENTS.map((info) => ({
    key: info.key,
    label: info.label,
    count: counts.get(info.key) ?? 0,
    bgClass: info.bgClass,
  }))
    .filter((entry) => entry.count > 0)
    .sort((a, b) => b.count - a.count);
}
