import type { PlanNode } from "@/lib/api/types";

// Groups plan nodes into dependency "waves" -- nodes with no unmet
// depends_on in wave 0, then nodes whose dependencies are all in earlier
// waves, etc. A small deliberate improvement over the old static
// frontend's flat <ol> of nodes (plan §6.9) -- lets the approval view show
// structure, not just a list, which is what a plan-then-approve gate
// (ARCHITECTURE.md §13.4) is supposed to make legible.
export function computePlanLayers(nodes: PlanNode[]): PlanNode[][] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const layerOf = new Map<string, number>();

  function resolve(nodeId: string, seen: Set<string>): number {
    const cached = layerOf.get(nodeId);
    if (cached !== undefined) return cached;
    if (seen.has(nodeId)) return 0; // cycle guard -- shouldn't happen, don't infinite-loop if it does

    const node = byId.get(nodeId);
    const deps = node?.depends_on.filter((depId) => byId.has(depId)) ?? [];
    if (deps.length === 0) {
      layerOf.set(nodeId, 0);
      return 0;
    }

    const nextSeen = new Set(seen).add(nodeId);
    const layer = Math.max(...deps.map((depId) => resolve(depId, nextSeen))) + 1;
    layerOf.set(nodeId, layer);
    return layer;
  }

  for (const node of nodes) resolve(node.id, new Set());

  const maxLayer = nodes.length === 0 ? -1 : Math.max(...nodes.map((n) => layerOf.get(n.id) ?? 0));
  const layers: PlanNode[][] = Array.from({ length: maxLayer + 1 }, () => []);
  for (const node of nodes) {
    layers[layerOf.get(node.id) ?? 0].push(node);
  }
  return layers;
}
