import type { ModuleLayout } from "./types";

// Static-layout math for the shared surface (DESIGN-sharing §4g). The owner's
// canvas coordinates are absolute and can be negative; the read-only view renders
// them into a plain scroll area, so we normalize every module by subtracting the
// minimum x/y across the set (nothing lands at a negative offset the viewer can't
// scroll to) and size the container to the bounding box. Heights are content-sized
// (layout.height is often 0), so the box height is a floor — absolutely-positioned
// tiles extend the scroll area past it naturally.

export interface PositionedBox {
  id: string;
  x: number;
  y: number;
  width: number;
}

export interface NormalizedLayout {
  width: number;
  height: number;
  boxes: PositionedBox[];
}

export function normalizeLayout(items: { id: string; layout: ModuleLayout }[]): NormalizedLayout {
  if (items.length === 0) return { width: 0, height: 0, boxes: [] };
  const minX = Math.min(...items.map((m) => m.layout.x));
  const minY = Math.min(...items.map((m) => m.layout.y));
  const maxX = Math.max(...items.map((m) => m.layout.x + m.layout.width));
  const maxY = Math.max(...items.map((m) => m.layout.y + m.layout.height));
  return {
    width: maxX - minX,
    height: maxY - minY,
    boxes: items.map((m) => ({
      id: m.id,
      x: m.layout.x - minX,
      y: m.layout.y - minY,
      width: m.layout.width,
    })),
  };
}
