// Canonical connector-line geometry, shared by every surface that draws a
// line between two blocks (currently the landing page's playable demo;
// bring any future non-react-flow diagram here too). The real canvas
// (StudioCanvas.tsx) doesn't call this directly -- react-flow draws its
// own bezier internally -- but it follows the same rule (see
// studio/design/DESIGN_SYSTEM.md): a smooth bezier curve, never a straight
// line or right-angle routing.

export type Point = { x: number; y: number };
export type Rect = { left: number; top: number; right: number; bottom: number };
export type Axis = "x" | "y";
export type Connector = { from: Point; to: Point; axis: Axis };

// Below this many px, a curve's control-point offset would be small
// enough to look like a kink rather than a bend.
const MIN_CURVE_OFFSET = 24;
// How far each control point reaches toward the other endpoint, as a
// fraction of the gap between them -- 0.5 keeps the bend centered.
const CURVE_RATIO = 0.5;

/**
 * Floating-edge anchoring for freeform diagrams: the line leaves a block
 * from the midpoint of whichever side faces the other block -- right when
 * the target sits to the right, bottom when it sits below -- rather than
 * a side hardcoded per block type. Recompute this on every drag (from
 * live getBoundingClientRect rects) so the exit/entry side updates as
 * blocks move. Only use this for diagrams with generic, single-socket
 * blocks; a typed multi-port node (the real canvas) anchors each port to
 * a fixed side instead -- see DESIGN_SYSTEM.md.
 */
export function floatingEdgeConnector(source: Rect, target: Rect): Connector {
  const sourceCenter = { x: (source.left + source.right) / 2, y: (source.top + source.bottom) / 2 };
  const targetCenter = { x: (target.left + target.right) / 2, y: (target.top + target.bottom) / 2 };
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;

  if (Math.abs(dx) >= Math.abs(dy)) {
    const rightward = dx >= 0;
    return {
      from: { x: rightward ? source.right : source.left, y: sourceCenter.y },
      to: { x: rightward ? target.left : target.right, y: targetCenter.y },
      axis: "x",
    };
  }
  const downward = dy >= 0;
  return {
    from: { x: sourceCenter.x, y: downward ? source.bottom : source.top },
    to: { x: targetCenter.x, y: downward ? target.top : target.bottom },
    axis: "y",
  };
}

/**
 * Renders a Connector as an SVG path `d` string: a cubic bezier that
 * leaves each endpoint straight along `axis` before bending toward the
 * other -- an S along x for a sideways connector, an S along y for a
 * top/bottom one. Pair with the `.connector-path` styling described in
 * DESIGN_SYSTEM.md (stroke: var(--muted), 1.5px, round caps, no dash).
 */
export function bezierConnectorPath({ from, to, axis }: Connector): string {
  if (axis === "x") {
    const delta = to.x - from.x;
    const offset = Math.max(Math.abs(delta) * CURVE_RATIO, MIN_CURVE_OFFSET) * Math.sign(delta || 1);
    return `M ${from.x} ${from.y} C ${from.x + offset} ${from.y}, ${to.x - offset} ${to.y}, ${to.x} ${to.y}`;
  }
  const delta = to.y - from.y;
  const offset = Math.max(Math.abs(delta) * CURVE_RATIO, MIN_CURVE_OFFSET) * Math.sign(delta || 1);
  return `M ${from.x} ${from.y} C ${from.x} ${from.y + offset}, ${to.x} ${to.y - offset}, ${to.x} ${to.y}`;
}
