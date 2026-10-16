import type { CanvasNode } from "./connection-validation";
import type { CanvasNodeData, CreativeNodeKind } from "./types";

export const SCENE_CARD_WIDTH = 380;
export const SCENE_CARD_GAP = 40;

export function isSceneKind(kind: CreativeNodeKind): boolean {
  switch (kind) {
    case "image":
    case "video":
    case "storyboard":
      return true;
    case "text":
    case "audio":
    case "generator":
    case "agentResult":
    case "agentRun":
      return false;
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}

function isSceneNode(data: CanvasNodeData): boolean {
  return isSceneKind(data.kind);
}

// The title a scene gets at creation if none is given -- see store.ts's
// addCreativeNode. Kept as its own check (rather than inlined) so the one
// place that needs to know "has this scene ever been renamed" -- the scene
// list's Untitled-N numbering -- has a single source of truth to import.
const DEFAULT_SCENE_TITLE = "Scene";

export function isUntitledSceneTitle(title: string): boolean {
  return title === DEFAULT_SCENE_TITLE;
}

export function approvedSequence(nodes: CanvasNode[]): CanvasNode[] {
  return nodes
    .filter((node) => node.data.approved && isSceneNode(node.data))
    .sort((a, b) => (a.data.storyOrder ?? 0) - (b.data.storyOrder ?? 0));
}

export function sceneBadge(data: CanvasNodeData): string | undefined {
  if (!isSceneNode(data)) {
    return undefined;
  }
  return "Scene";
}

export function durationLabel(data: CanvasNodeData): string {
  const value = sourceDuration(data);
  if (value !== undefined) {
    return `${value}s`;
  }
  if (data.kind === "image") {
    return "Still";
  }
  return "";
}

export function aspectLabel(data: CanvasNodeData): string {
  const metadata = outputMetadata(data);
  if (metadata?.width && metadata.height) {
    const ratio = aspectRatioFromDimensions(metadata.width, metadata.height);
    if (ratio) return ratio;
  }
  const value = data.config.aspect_ratio;
  return typeof value === "string" ? value : "";
}

function outputMetadata(data: CanvasNodeData): CanvasNodeData["outputMetadata"] {
  return data.output && data.outputMetadata?.versionId === data.output.versionId
    ? data.outputMetadata : undefined;
}

export function sourceDuration(data: CanvasNodeData): number | undefined {
  const actual = outputMetadata(data)?.durationSeconds;
  if (typeof actual === "number" && Number.isFinite(actual) && actual > 0) return actual;
  const requested = data.config.duration_seconds;
  return typeof requested === "number" && Number.isFinite(requested) && requested > 0
    ? requested : undefined;
}

export function sourceAspectRatio(data: CanvasNodeData): number | undefined {
  const metadata = outputMetadata(data);
  if (metadata?.width && metadata.height && metadata.width > 0 && metadata.height > 0) {
    const ratio = metadata.width / metadata.height;
    if (Number.isFinite(ratio) && ratio > 0) return ratio;
  }
  return numericAspectRatio(data.config.aspect_ratio);
}

export function numericAspectRatio(value: unknown): number | undefined {
  const match = typeof value === "string"
    ? /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(value.trim()) : null;
  if (!match) return undefined;
  const width = Number(match[1]);
  const height = Number(match[2]);
  const ratio = width / height;
  return width > 0 && height > 0 && Number.isFinite(width) && Number.isFinite(height)
    && ratio > 0 && Number.isFinite(ratio) ? ratio : undefined;
}

// Video's `resolution` and image's `size` are different fields with
// different value shapes, but both name a target output's short side --
// normalize them to one pixel number.
const RESOLUTION_SHORT_SIDE: Record<string, number> = {
  "480p": 480,
  "720p": 720,
  "1080p": 1080,
  "1K": 1024,
  "2K": 2048,
  "3K": 3072,
};

const CANVAS_ZOOM = 0.14; // tuned so a 1080p/2K 16:9 frame reads as "large" without dominating
const MIN_FRAME_PX = 96; // floor so small frames still fit their Generate button/text legibly
const MAX_FRAME_PX = 420; // ceiling so a high-res wide frame doesn't dominate the canvas

export function aspectRatioFromDimensions(width: number, height: number): string | undefined {
  if (!Number.isFinite(width) || !Number.isFinite(height)) return undefined;
  const roundedWidth = Math.round(width);
  const roundedHeight = Math.round(height);
  if (roundedWidth <= 0 || roundedHeight <= 0) return undefined;
  const ratio = roundedWidth / roundedHeight;
  const commonRatios: Array<[number, number]> = [
    [1, 1],
    [16, 9],
    [9, 16],
    [4, 3],
    [3, 4],
    [3, 2],
    [2, 3],
    [21, 9],
  ];
  const nearest = commonRatios.find(
    ([ratioWidth, ratioHeight]) =>
      Math.abs(ratio - ratioWidth / ratioHeight) / (ratioWidth / ratioHeight) < 0.015,
  );
  if (nearest) return `${nearest[0]}:${nearest[1]}`;
  const divisor = (left: number, right: number): number =>
    right === 0 ? left : divisor(right, left % right);
  const common = divisor(roundedWidth, roundedHeight);
  return `${Math.round(roundedWidth / common)}:${Math.round(roundedHeight / common)}`;
}

// Figma-style: size the node to its real target pixel dimensions at a fixed
// canvas zoom, rather than fitting every ratio into one fixed slot. This is
// what makes 16:9 read as genuinely bigger than 9:16 -- the same reason a
// 1920x1080 frame looks bigger than a 428x926 one in Figma, at any given
// zoom level, without needing letterbox padding to fake the comparison.
export function nodeFrameSize(data: CanvasNodeData): { width: number; height: number } {
  const ratio = sourceAspectRatio(data) ?? 1;

  const resValue = data.config.resolution ?? data.config.size;
  const shortSide = (typeof resValue === "string" && RESOLUTION_SHORT_SIDE[resValue]) || 720;

  const metadata = outputMetadata(data);
  // Known media fills the card's 200px minimum width at ordinary ratios.
  const minimum = metadata?.width && metadata.height ? 200 : MIN_FRAME_PX;
  const shortFrame = Math.max(minimum, shortSide * CANVAS_ZOOM);
  // The longest edge wins when an extreme ratio cannot meet both bounds.
  const width = ratio >= 1
    ? Math.min(MAX_FRAME_PX, shortFrame * ratio)
    : Math.min(shortFrame, MAX_FRAME_PX * ratio);
  const height = width / ratio;

  return { width: Math.max(1, Math.round(width)), height: Math.max(1, Math.round(height)) };
}

export function variantPosition(data: CanvasNodeData): { current: number; total: number } {
  const variants = data.variants || [];
  if (variants.length === 0) {
    return { current: 0, total: 0 };
  }
  const index = variants.findIndex((item) => item.versionId === data.output?.versionId);
  return { current: (index >= 0 ? index : 0) + 1, total: variants.length };
}
