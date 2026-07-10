"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { cn } from "@/lib/utils";

import { HierarchyNode } from "./hierarchy-builder";
import { OrganizationNodeCard } from "./OrganizationNode";

interface OrganizationChartProps {
  node: HierarchyNode;
  selectedNodeId: string | null;
  onSelectNode: (node: HierarchyNode) => void;
}

export function OrganizationChart({
  node,
  selectedNodeId,
  onSelectNode,
}: OrganizationChartProps) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;

  return (
    <div className="flex flex-col items-center">
      <OrganizationNodeCard
        node={node}
        isSelected={selectedNodeId === node.user_id}
        hasChildren={hasChildren}
        isExpanded={expanded}
        onToggleExpand={() => setExpanded((prev) => !prev)}
        onSelect={() => onSelectNode(node)}
      />

      <AnimatePresence initial={false}>
        {hasChildren && expanded && (
          <motion.div
            key="children"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            {/* Stem connecting the parent card down to the sibling row */}
            <div className="mx-auto h-6 w-px bg-border" />

            <ul className="flex">
              {node.children.map((child) => (
                <li
                  key={child.user_id}
                  className={cn(
                    "relative flex flex-col items-center px-6",
                    "before:absolute before:right-1/2 before:top-0 before:h-px before:w-1/2 before:bg-border",
                    "after:absolute after:left-1/2 after:top-0 after:h-px after:w-1/2 after:bg-border",
                    "first:before:bg-transparent last:after:bg-transparent"
                  )}
                >
                  {/* Stem connecting the sibling row down to this child */}
                  <div className="h-6 w-px bg-border" />

                  <OrganizationChart
                    node={child}
                    selectedNodeId={selectedNodeId}
                    onSelectNode={onSelectNode}
                  />
                </li>
              ))}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
