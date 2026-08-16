"use client";

import { HierarchyNode } from "../hierarchy-builder";
import { getDepartmentInfo } from "./department-colors";
import { NODE_HEIGHT, NODE_WIDTH } from "./layout";
import { approxTextWidth, layoutPillRow, layoutPill, truncateToWidth } from "./svg-text";

interface OrgChartNodeCardProps {
  node: HierarchyNode;
  x: number;
  y: number;
  isSelected: boolean;
  isMatched: boolean;
  hasChildren: boolean;
  isCollapsed: boolean;
  isDimmed: boolean;
  onToggleExpand: () => void;
  onSelect: () => void;
  onDoubleClick: () => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

const HALF_W = NODE_WIDTH / 2;
const HALF_H = NODE_HEIGHT / 2;
const AVATAR_R = 20;
const AVATAR_CY = -HALF_H + 32;
const NAME_Y = AVATAR_CY + 34;
const EMAIL_Y = NAME_Y + 16;
const BADGE_ROW_Y = EMAIL_Y + 22;
const DEPT_Y = BADGE_ROW_Y + 24;
const RM_ROW_Y = DEPT_Y + 20;
const EXPAND_BUTTON_R = 11;

/**
 * Pure SVG node content (no HTML/foreignObject) — every shape and
 * glyph here is a real SVG primitive (<rect>/<circle>/<text>/<path>),
 * so it stays exactly as sharp at 250% zoom as at 20%: there is no
 * bitmap being stretched, the browser rasterizes the actual vector
 * geometry at whatever the current transform scale resolves to on
 * screen. This replaces an earlier <foreignObject> version, which
 * could blur during a live mouse-wheel zoom in some browsers (they
 * may rasterize foreignObject's embedded HTML to a texture and scale
 * that texture rather than re-laying-out text at each new size).
 */
export function OrgChartNodeCard({
  node,
  x,
  y,
  isSelected,
  isMatched,
  hasChildren,
  isCollapsed,
  isDimmed,
  onToggleExpand,
  onSelect,
  onDoubleClick,
  onMouseEnter,
  onMouseLeave,
}: OrgChartNodeCardProps) {
  const initial = node.name.charAt(0).toUpperCase();
  const name = truncateToWidth(node.name, 13, NODE_WIDTH - 20);
  const email = truncateToWidth(node.email, 10.5, NODE_WIDTH - 20);

  // Every category this node's user belongs to — `departments`
  // (plural, multi-category-aware) if present, else the legacy
  // singular `department` wrapped in a one-element array (back-compat
  // with any stale cached response predating the plural field). A
  // genuinely category-less user (both empty/null) still gets exactly
  // one entry, `null`, so the existing "Leadership" fallback chip
  // keeps rendering exactly as before this change. Capped to 2 entries
  // with no "+N more" indicator, mirroring the `reporting_manager_for`
  // pill row's own existing precedent for a variable-length array in
  // this same card — no new UI idiom.
  const departmentEntries: (string | null)[] = node.departments?.length
    ? node.departments
    : node.department
      ? [node.department]
      : [null];
  const DEPT_DOT_R = 3;
  const DEPT_DOT_GAP = 5;
  // Keyed by display label so the render loop below can look color
  // back up without re-deriving it from the (already-resolved-to-a-
  // label) pill text — `getDepartmentInfo` needs the original,
  // possibly-`null` value to tell "Leadership" apart from an unknown
  // category string, which the resolved label text alone can't do.
  const deptColorByLabel = new Map(
    departmentEntries.slice(0, 2).map((dept) => [
      truncateToWidth(dept ?? getDepartmentInfo(dept).label, 10, NODE_WIDTH - 40),
      getDepartmentInfo(dept),
    ])
  );
  const deptRow = layoutPillRow(
    departmentEntries.slice(0, 2).map((dept) => {
      const label = truncateToWidth(dept ?? getDepartmentInfo(dept).label, 10, NODE_WIDTH - 40);
      return { text: label, width: DEPT_DOT_R * 2 + DEPT_DOT_GAP + approxTextWidth(label, 10) };
    }),
    10
  );

  const badgeRow = layoutPillRow(
    [layoutPill(node.role, 10, 8), layoutPill(node.is_active ? "Active" : "Inactive", 10, 8)],
    6
  );

  const rmForRow = node.reporting_manager_for?.length
    ? layoutPillRow(
        node.reporting_manager_for.slice(0, 2).map((c) => layoutPill(`RM · ${c}`, 9, 6)),
        4
      )
    : [];

  return (
    <g
      transform={`translate(${x},${y})`}
      onClick={onSelect}
      onDoubleClick={onDoubleClick}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      role="button"
      tabIndex={0}
      data-org-me={node.isMe ? "true" : undefined}
      data-org-node-id={node.user_id}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
      className={["cursor-pointer", isDimmed ? "opacity-30" : "opacity-100"].join(" ")}
      style={{ transition: "opacity 150ms ease" }}
    >
      {/* Search-match ring — an independent sibling so it dims/undims
          along with the rest of the node via the parent <g>'s opacity,
          and its 4px outward offset keeps it clear of the card's own
          border (which separately reflects isMe/isSelected). */}
      {isMatched && (
        <rect
          x={-HALF_W - 4}
          y={-HALF_H - 4}
          width={NODE_WIDTH + 8}
          height={NODE_HEIGHT + 8}
          rx={18}
          fill="none"
          className="stroke-warning"
          strokeWidth={2}
          strokeDasharray="6 4"
        />
      )}

      {/* Card background + border */}
      <rect
        x={-HALF_W}
        y={-HALF_H}
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={14}
        className={[
          "fill-card transition-colors",
          node.isMe ? "stroke-primary" : isSelected ? "stroke-accent-foreground/60" : "stroke-border",
        ].join(" ")}
        strokeWidth={node.isMe || isSelected ? 2 : 1}
      />

      {node.isMe && (
        <>
          <rect x={-18} y={-HALF_H - 10} width={36} height={18} rx={9} className="fill-primary" />
          <text
            x={0}
            y={-HALF_H - 10 + 12.5}
            textAnchor="middle"
            className="fill-primary-foreground"
            style={{ fontSize: 9, fontWeight: 700 }}
          >
            ME
          </text>
        </>
      )}

      {/* Avatar */}
      <circle cx={0} cy={AVATAR_CY} r={AVATAR_R} className="fill-muted" />
      <text
        x={0}
        y={AVATAR_CY + 5}
        textAnchor="middle"
        className="fill-muted-foreground"
        style={{ fontSize: 15, fontWeight: 600 }}
      >
        {initial}
      </text>

      {/* Name + email */}
      <text
        x={0}
        y={NAME_Y}
        textAnchor="middle"
        className="fill-card-foreground"
        style={{ fontSize: 13, fontWeight: 600 }}
      >
        {name}
      </text>
      <text x={0} y={EMAIL_Y} textAnchor="middle" className="fill-muted-foreground" style={{ fontSize: 10.5 }}>
        {email}
      </text>

      {/* Role + Active/Inactive pills */}
      {badgeRow.map(({ pill, centerX }) => {
        const isStatus = pill.text === "Active" || pill.text === "Inactive";
        return (
          <g key={pill.text}>
            <rect
              x={centerX - pill.width / 2}
              y={BADGE_ROW_Y - 9}
              width={pill.width}
              height={18}
              rx={9}
              className={
                isStatus
                  ? pill.text === "Active"
                    ? "fill-success/15"
                    : "fill-destructive/15"
                  : "fill-secondary"
              }
            />
            <text
              x={centerX}
              y={BADGE_ROW_Y + 3.5}
              textAnchor="middle"
              className={
                isStatus
                  ? pill.text === "Active"
                    ? "fill-success"
                    : "fill-destructive"
                  : "fill-secondary-foreground"
              }
              style={{ fontSize: 10, fontWeight: 600 }}
            >
              {pill.text}
            </text>
          </g>
        );
      })}

      {/* Department chip(s): colored dot + label, one per category this
          user belongs to (a Team Lead may now belong to more than
          one — see root CLAUDE.md's multi-category-users section) */}
      <g transform={`translate(0,${DEPT_Y})`}>
        {deptRow.map(({ pill, centerX }) => {
          const chipStartX = centerX - pill.width / 2;
          const fillClass = deptColorByLabel.get(pill.text)?.fillClass ?? "fill-dept-other";
          return (
            <g key={pill.text}>
              <circle
                cx={chipStartX + DEPT_DOT_R}
                cy={-3.5}
                r={DEPT_DOT_R}
                className={fillClass}
              />
              <text
                x={chipStartX + DEPT_DOT_R * 2 + DEPT_DOT_GAP}
                y={0}
                textAnchor="start"
                className="fill-muted-foreground"
                style={{ fontSize: 10 }}
              >
                {pill.text}
              </text>
            </g>
          );
        })}
      </g>

      {/* Reporting-Manager-for pills */}
      {rmForRow.map(({ pill, centerX }) => (
        <g key={pill.text}>
          <rect
            x={centerX - pill.width / 2}
            y={RM_ROW_Y - 8}
            width={pill.width}
            height={16}
            rx={8}
            className="fill-transparent stroke-border"
            strokeWidth={1}
          />
          <text
            x={centerX}
            y={RM_ROW_Y + 3}
            textAnchor="middle"
            className="fill-foreground"
            style={{ fontSize: 9, fontWeight: 500 }}
          >
            {pill.text}
          </text>
        </g>
      ))}

      {/* Expand/collapse */}
      {hasChildren && (
        <g
          transform={`translate(0,${HALF_H})`}
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpand();
          }}
          className="cursor-pointer"
        >
          <circle
            r={EXPAND_BUTTON_R}
            className="fill-background stroke-border transition-colors hover:fill-muted"
            strokeWidth={1}
          />
          <path
            d={isCollapsed ? "M-4,-2 L0,3 L4,-2" : "M-4,2 L0,-3 L4,2"}
            fill="none"
            className="stroke-muted-foreground"
            strokeWidth={1.75}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      )}
    </g>
  );
}
