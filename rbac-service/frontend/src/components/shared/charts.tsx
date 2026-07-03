"use client";

import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/*                              AREA TREND CHART                              */
/* -------------------------------------------------------------------------- */

interface TrendPoint {
  label: string;
  value: number;
}

interface AreaTrendChartProps {
  data: TrendPoint[];
  className?: string;
  valueFormatter?: (value: number) => string;
}

const CHART_WIDTH = 560;
const CHART_HEIGHT = 160;
const PADDING_X = 12;
const PADDING_Y = 16;

export function AreaTrendChart({
  data,
  className,
  valueFormatter = (value) => `${value}`,
}: AreaTrendChartProps) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const { points, linePath, areaPath } = useMemo(() => {
    const max = Math.max(...data.map((d) => d.value), 1);
    const innerWidth = CHART_WIDTH - PADDING_X * 2;
    const innerHeight = CHART_HEIGHT - PADDING_Y * 2;
    const step = data.length > 1 ? innerWidth / (data.length - 1) : 0;

    const points = data.map((d, i) => ({
      x: PADDING_X + step * i,
      y: PADDING_Y + innerHeight * (1 - d.value / max),
      ...d,
    }));

    const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
    const baseline = CHART_HEIGHT - PADDING_Y;
    const areaPath =
      points.length > 0
        ? `${linePath} L${points[points.length - 1].x},${baseline} L${points[0].x},${baseline} Z`
        : "";

    return { points, linePath, areaPath };
  }, [data]);

  const hovered = hoverIndex !== null ? points[hoverIndex] : null;
  const slotWidth = data.length > 0 ? CHART_WIDTH / data.length : CHART_WIDTH;

  return (
    <div className={cn("relative", className)}>
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        preserveAspectRatio="none"
        className="h-40 w-full overflow-visible"
        onMouseLeave={() => setHoverIndex(null)}
        role="img"
        aria-label="Weekly login activity trend"
      >
        <defs>
          <linearGradient id="area-trend-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgb(59 130 246)" stopOpacity={0.22} />
            <stop offset="100%" stopColor="rgb(59 130 246)" stopOpacity={0} />
          </linearGradient>
        </defs>

        <line
          x1={PADDING_X}
          x2={CHART_WIDTH - PADDING_X}
          y1={CHART_HEIGHT - PADDING_Y}
          y2={CHART_HEIGHT - PADDING_Y}
          className="stroke-border"
          strokeWidth={1}
        />

        {areaPath && <path d={areaPath} fill="url(#area-trend-fill)" stroke="none" />}
        <path d={linePath} fill="none" stroke="rgb(59 130 246)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />

        {hovered && (
          <line
            x1={hovered.x}
            x2={hovered.x}
            y1={PADDING_Y}
            y2={CHART_HEIGHT - PADDING_Y}
            className="stroke-border"
            strokeWidth={1}
          />
        )}

        {points.map((p, i) => (
          <g key={p.label}>
            <circle
              cx={p.x}
              cy={p.y}
              r={hoverIndex === i ? 5 : 4}
              className="fill-blue-500 stroke-card"
              strokeWidth={2}
              opacity={hoverIndex === null || hoverIndex === i ? 1 : 0.6}
            />
            <rect
              x={p.x - slotWidth / 2}
              y={0}
              width={slotWidth}
              height={CHART_HEIGHT}
              fill="transparent"
              tabIndex={0}
              aria-label={`${p.label}: ${valueFormatter(p.value)}`}
              onMouseEnter={() => setHoverIndex(i)}
              onFocus={() => setHoverIndex(i)}
              onBlur={() => setHoverIndex(null)}
            />
          </g>
        ))}
      </svg>

      <div className="mt-1 flex justify-between text-[11px] text-muted-foreground">
        {data.map((d) => (
          <span key={d.label}>{d.label}</span>
        ))}
      </div>

      {hovered && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[calc(100%+10px)] whitespace-nowrap rounded-lg border border-border bg-popover px-2.5 py-1.5 text-xs shadow-md"
          style={{
            left: `${(hovered.x / CHART_WIDTH) * 100}%`,
            top: `${(hovered.y / CHART_HEIGHT) * 100}%`,
          }}
        >
          <p className="font-semibold text-foreground">{valueFormatter(hovered.value)}</p>
          <p className="text-muted-foreground">{hovered.label}</p>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*                              CATEGORY BAR LIST                             */
/* -------------------------------------------------------------------------- */

interface CategoryBarListProps {
  data: TrendPoint[];
  className?: string;
}

export function CategoryBarList({ data, className }: CategoryBarListProps) {
  const max = Math.max(...data.map((d) => d.value), 1);

  return (
    <div className={cn("space-y-4", className)}>
      {data.map((d) => {
        const pct = max > 0 ? Math.round((d.value / max) * 100) : 0;

        return (
          <div key={d.label} className="group">
            <div className="mb-1.5 flex items-center justify-between text-sm">
              <span className="font-medium text-foreground">{d.label}</span>
              <span className="tabular-nums text-muted-foreground">{d.value}</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-r-full bg-blue-500 transition-all duration-500 ease-out group-hover:bg-blue-400"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
