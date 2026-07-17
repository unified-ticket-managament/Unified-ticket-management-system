"use client";

import { ChevronDown } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { HierarchyNode } from "./hierarchy-builder";

interface OrganizationNodeCardProps {
  node: HierarchyNode;
  isSelected: boolean;
  hasChildren: boolean;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onSelect: () => void;
}

export function OrganizationNodeCard({
  node,
  isSelected,
  hasChildren,
  isExpanded,
  onToggleExpand,
  onSelect,
}: OrganizationNodeCardProps) {
  return (
    <div
      onClick={onSelect}
      role="button"
      tabIndex={0}
      data-org-me={node.isMe ? "true" : undefined}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
      className={cn(
        "group relative flex w-56 cursor-pointer flex-col items-center gap-2 rounded-xl border bg-card p-4 text-center shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md",
        node.isMe
          ? "border-primary bg-primary/5 ring-2 ring-primary/40"
          : "border-border",
        isSelected && !node.isMe && "ring-2 ring-accent-foreground/30"
      )}
    >
      {node.isMe && (
        <Badge className="absolute -top-2.5 left-1/2 -translate-x-1/2">
          ME
        </Badge>
      )}

      <Avatar className="h-12 w-12">
        <AvatarFallback className="text-base">
          {node.name.charAt(0).toUpperCase()}
        </AvatarFallback>
      </Avatar>

      <div className="space-y-1">
        <p className="text-sm font-semibold leading-tight">{node.name}</p>
        <p className="truncate text-xs text-muted-foreground">{node.email}</p>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-1.5">
        <Badge variant="secondary">{node.role}</Badge>
        <Badge variant={node.is_active ? "success" : "destructive"}>
          {node.is_active ? "Active" : "Inactive"}
        </Badge>
      </div>

      {node.department && (
        <p className="text-xs text-muted-foreground">{node.department}</p>
      )}

      {node.reporting_manager_for && node.reporting_manager_for.length > 0 && (
        <div className="flex flex-wrap items-center justify-center gap-1">
          {node.reporting_manager_for.map((category) => (
            <Badge key={category} variant="outline" className="text-[10px]">
              RM · {category}
            </Badge>
          ))}
        </div>
      )}

      {hasChildren && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpand();
          }}
          className="mt-1 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-background text-muted-foreground transition-colors hover:bg-muted"
          aria-label={isExpanded ? "Collapse" : "Expand"}
        >
          <ChevronDown
            className={cn(
              "h-4 w-4 transition-transform",
              isExpanded ? "rotate-180" : "rotate-0"
            )}
          />
        </button>
      )}
    </div>
  );
}
