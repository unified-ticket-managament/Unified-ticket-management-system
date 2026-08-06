// Small helpers for laying out plain SVG <text>/<rect> "pill" badges
// without a canvas measureText call — SVG has no native text-overflow
// ellipsis or auto-sized badge, so both are approximated here with a
// simple average-character-width heuristic. The overestimate bias
// (0.62 * fontSize) is deliberate: a pill slightly wider than its text
// looks fine, a pill that clips its own label doesn't.

export function approxTextWidth(text: string, fontSize: number): number {
  return text.length * fontSize * 0.62;
}

export function truncateToWidth(text: string, fontSize: number, maxWidth: number): string {
  if (approxTextWidth(text, fontSize) <= maxWidth) return text;

  const ellipsis = "…";
  let end = text.length;
  while (end > 0 && approxTextWidth(text.slice(0, end) + ellipsis, fontSize) > maxWidth) {
    end -= 1;
  }
  return end <= 0 ? ellipsis : text.slice(0, end) + ellipsis;
}

export interface PillLayout {
  text: string;
  width: number;
}

export function layoutPill(text: string, fontSize: number, paddingX: number): PillLayout {
  return { text, width: approxTextWidth(text, fontSize) + paddingX * 2 };
}

/** Lays out a centered horizontal row of pills, returning each one's x-offset (its own center) relative to the row's overall center. */
export function layoutPillRow(pills: PillLayout[], gap: number): { pill: PillLayout; centerX: number }[] {
  const totalWidth = pills.reduce((sum, p) => sum + p.width, 0) + gap * Math.max(0, pills.length - 1);
  let cursor = -totalWidth / 2;
  return pills.map((pill) => {
    const centerX = cursor + pill.width / 2;
    cursor += pill.width + gap;
    return { pill, centerX };
  });
}
