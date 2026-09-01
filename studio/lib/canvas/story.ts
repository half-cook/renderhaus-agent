import type { CanvasNodeData, CreativeNodeKind } from "./types";

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

export function isSceneNode(data: CanvasNodeData): boolean {
  return isSceneKind(data.kind);
}

export function sceneBadge(data: CanvasNodeData): string | undefined {
  if (!isSceneNode(data)) {
    return undefined;
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
  const ratioValue = data.config.aspect_ratio;
  const ratio = typeof ratioValue === "string" ? ratioValue.trim() : "";
  const match = /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(ratio);
  const [rw, rh] = match ? [Number(match[1]), Number(match[2])] : [1, 1];

  const resValue = data.config.resolution ?? data.config.size;
  const shortSide = (typeof resValue === "string" && RESOLUTION_SHORT_SIDE[resValue]) || 720;

  const isPortrait = rh > rw;
  const realWidth = isPortrait ? shortSide : (shortSide * rw) / rh;
  const realHeight = isPortrait ? (shortSide * rh) / rw : shortSide;

  let width = realWidth * CANVAS_ZOOM;
  let height = realHeight * CANVAS_ZOOM;

  // Scale the WHOLE box uniformly against whichever bound binds -- clamping
  // each axis independently would distort the ratio instead of preserving it.
  const longest = Math.max(width, height);
  const shortest = Math.min(width, height);
  if (longest > MAX_FRAME_PX) {
    const factor = MAX_FRAME_PX / longest;
    width *= factor;
    height *= factor;
  } else if (shortest < MIN_FRAME_PX) {
    const factor = MIN_FRAME_PX / shortest;
    width *= factor;
    height *= factor;
  }

  return { width: Math.round(width), height: Math.round(height) };
}

export function variantPosition(data: CanvasNodeData): { current: number; total: number } {
  const variants = data.variants || [];
  if (variants.length === 0) {
    return { current: 0, total: 0 };
  }
  const index = variants.findIndex((item) => item.versionId === data.output?.versionId);
  return { current: (index >= 0 ? index : 0) + 1, total: variants.length };
}
