import { useCallback, useEffect, useRef, useState } from "react";
import { select } from "d3-selection";
import { D3ZoomEvent, zoom as d3zoom, zoomIdentity, ZoomBehavior } from "d3-zoom";
// Side-effect import: mixes `.transition()` onto d3-selection's
// Selection.prototype at runtime (and provides the matching type
// augmentation) — without this, the `.transition()` calls below
// would throw, not just fail to type-check.
import "d3-transition";

export const MIN_SCALE = 0.2;
export const MAX_SCALE = 2.5;

export interface Transform {
  x: number;
  y: number;
  k: number;
}

const IDENTITY: Transform = { x: 0, y: 0, k: 1 };

/**
 * Binds d3-zoom to `svgRef` for the actual gesture handling (mouse
 * wheel zoom, touch pinch zoom, click-and-drag pan all come for free
 * from d3-zoom itself — this hook doesn't reimplement any of them),
 * and exposes the current transform plus a few imperative helpers for
 * the toolbar buttons, which drive the same zoom behavior
 * programmatically rather than through a second, parallel mechanism.
 *
 * Double-click-to-zoom is disabled (see the `filter`) since
 * double-click is repurposed by OrgChartCanvas to "center on this
 * node" instead.
 */
export function useZoomPan(svgRef: React.RefObject<SVGSVGElement>) {
  const [transform, setTransform] = useState<Transform>(IDENTITY);
  const behaviorRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;

    const selection = select(svgEl);

    const behavior = d3zoom<SVGSVGElement, unknown>()
      .scaleExtent([MIN_SCALE, MAX_SCALE])
      .filter((event: Event) => {
        if (event.type === "dblclick") return false;
        const mouseEvent = event as MouseEvent;
        return (!mouseEvent.ctrlKey || event.type === "wheel") && !mouseEvent.button;
      })
      .on("zoom", (event: D3ZoomEvent<SVGSVGElement, unknown>) => {
        setTransform({ x: event.transform.x, y: event.transform.y, k: event.transform.k });
      });

    selection.call(behavior);
    behaviorRef.current = behavior;

    return () => {
      selection.on(".zoom", null);
      behaviorRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyTransform = useCallback(
    (next: Transform, animate = true) => {
      const svgEl = svgRef.current;
      const behavior = behaviorRef.current;
      if (!svgEl || !behavior) return;

      const target = zoomIdentity.translate(next.x, next.y).scale(next.k);
      const selection = select(svgEl);

      if (animate) {
        selection.transition().duration(350).call(behavior.transform, target);
      } else {
        behavior.transform(selection, target);
      }
    },
    [svgRef]
  );

  const zoomBy = useCallback(
    (factor: number) => {
      const svgEl = svgRef.current;
      const behavior = behaviorRef.current;
      if (!svgEl || !behavior) return;

      select(svgEl).transition().duration(200).call(behavior.scaleBy, factor);
    },
    [svgRef]
  );

  return { transform, applyTransform, zoomBy };
}
