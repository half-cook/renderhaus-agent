import type { CanvasNode } from "./connection-validation";
import { nodeFrameSize, SCENE_CARD_GAP } from "./story";

function bounds(node: CanvasNode, zoom: number) {
  const { data } = node;
  const scene = data.kind === "image" || data.kind === "video";
  const metadata = data.outputMetadata;
  const awaitingMetadata = scene && !(data.output && metadata?.versionId === data.output.versionId
    && Number.isFinite(metadata.width) && Number.isFinite(metadata.height)
    && (metadata.width ?? 0) > 0 && (metadata.height ?? 0) > 0);
  const frame = nodeFrameSize(data);
  // Reserve the existing frame ceiling until a scene's actual output dimensions arrive.
  const width = Math.max(node.measured?.width || node.width || 0,
    scene ? awaitingMetadata ? 420 : Math.max(200, frame.width) : data.kind === "text" ? 320 : 380);
  const height = Math.max(node.measured?.height || node.height || 0,
    scene ? (awaitingMetadata ? 420 : frame.height) + 46 : data.kind === "text" ? 180 : 320);
  // Tags and the top toolbar stay screen-sized while their card zooms.
  return {
    left: node.position.x - Math.max(0, 264 / zoom - width),
    right: node.position.x + Math.max(width, width / zoom),
    top: node.position.y - 82 / zoom - 8,
    bottom: node.position.y + height,
  };
}

/** Find room for one insertion without rearranging any existing creative work. */
export function newNodePosition(node: CanvasNode, nodes: CanvasNode[], zoom = 1): CanvasNode["position"] {
  const scale = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
  const position = { ...node.position };
  let candidate = bounds(node, scale);
  const occupied = nodes.filter((item) => !item.hidden).map((item) => bounds(item, scale))
    .sort((left, right) => left.left - right.left);
  for (const other of occupied) {
    if (candidate.left < other.right + SCENE_CARD_GAP && candidate.right + SCENE_CARD_GAP > other.left
      && candidate.top < other.bottom + SCENE_CARD_GAP && candidate.bottom + SCENE_CARD_GAP > other.top) {
      const shift = other.right + SCENE_CARD_GAP - candidate.left;
      position.x += shift;
      candidate = { ...candidate, left: candidate.left + shift, right: candidate.right + shift };
    }
  }
  return position;
}
