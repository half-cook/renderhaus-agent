import type { CanvasNode } from "./connection-validation";
import type { CanvasNodeData, CreativeNodeKind } from "./types";

export const SCENE_CARD_WIDTH = 380;
export const SCENE_CARD_GAP = 40;
export const SEQUENCE_STRIP_HEIGHT = 64;

export function isSceneKind(kind: CreativeNodeKind): boolean {
  switch (kind) {
    case "image":
    case "video":
    case "storyboard":
      return true;
    case "text":
    case "audio":
    case "generator":
      return false;
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}

export function isSceneNode(data: CanvasNodeData): boolean {
  return isSceneKind(data.kind);
}

export function approvedSequence(nodes: CanvasNode[]): CanvasNode[] {
  return nodes
    .filter((node) => node.data.approved && isSceneNode(node.data))
    .sort((a, b) => (a.data.storyOrder ?? 0) - (b.data.storyOrder ?? 0));
}

export function nextStoryOrder(nodes: CanvasNode[]): number {
  const sequence = approvedSequence(nodes);
  if (sequence.length === 0) {
    return 1;
  }
  return Math.max(...sequence.map((node) => node.data.storyOrder ?? 0)) + 1;
}

export function compactStoryOrders(nodes: CanvasNode[]): CanvasNode[] {
  const order = new Map(approvedSequence(nodes).map((node, index) => [node.id, index + 1]));
  return nodes.map((node) => {
    const storyOrder = order.get(node.id);
    if (storyOrder === undefined) {
      if (!node.data.approved && node.data.storyOrder === undefined) {
        return node;
      }
      if (!node.data.approved) {
        return { ...node, data: { ...node.data, storyOrder: undefined } };
      }
      return node;
    }
    if (node.data.storyOrder === storyOrder) {
      return node;
    }
    return { ...node, data: { ...node.data, storyOrder } };
  });
}

export function sceneBadge(data: CanvasNodeData): string | undefined {
  if (!isSceneNode(data)) {
    return undefined;
  }
  if (data.approved && data.storyOrder) {
    return `Sc ${String(data.storyOrder).padStart(2, "0")}`;
  }
  return "Scene";
}

export function durationLabel(data: CanvasNodeData): string {
  const value = data.config.duration_seconds;
  if (typeof value === "number" && Number.isFinite(value)) {
    return `${value}s`;
  }
  if (data.kind === "image") {
    return "Still";
  }
  return "";
}

export function aspectLabel(data: CanvasNodeData): string {
  const value = data.config.aspect_ratio;
  return typeof value === "string" ? value : "";
}

export function variantPosition(data: CanvasNodeData): { current: number; total: number } {
  const variants = data.variants || [];
  if (variants.length === 0) {
    return { current: 0, total: 0 };
  }
  const index = variants.findIndex((item) => item.url === data.output?.url);
  return { current: (index >= 0 ? index : 0) + 1, total: variants.length };
}
