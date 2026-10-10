/**
 * Single-track timeline model (v1: trim and reorder only). Pure functions over plain clip values so they are
 * unit-testable; the canvas store owns persistence. Time is seconds; trims snap to a quarter second by default.
 */
import type { CanvasNode } from "@/lib/canvas/connection-validation";
import { approvedSequence } from "@/lib/canvas/story";

export const PX_PER_SECOND = 124;
export const SNAP_SECONDS = 0.25;
export const FRAME_SECONDS = 1 / 24;
export const MIN_CLIP_SECONDS = 0.5;

export type TimelineClip = {
  id: string;
  /** 1-based position on the track. */
  order: number;
  title: string;
  /** Length of the source media. */
  sourceSeconds: number;
  trimIn: number;
  trimOut: number;
  thumbUrl?: string;
};

export const clipLength = (clip: Pick<TimelineClip, "trimIn" | "trimOut">): number => Math.max(0, round3(clip.trimOut - clip.trimIn));
export const round3 = (value: number): number => Math.round(value * 1000) / 1000;

function numberConfig(node: CanvasNode, key: string): number | undefined {
  const value = node.data.config[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

/** Clips on the track: the approved sequence in story order; before anything is approved, video shots left to right. */
export function clipsFromNodes(nodes: CanvasNode[]): TimelineClip[] {
  const approved = approvedSequence(nodes).filter((node) => node.data.kind === "video");
  const source = approved.length
    ? approved
    : nodes.filter((node) => node.data.kind === "video" && (node.data.output || typeof node.data.config.thumbnail_url === "string")).sort((a, b) => a.position.x - b.position.x);
  return source.flatMap((node, index): TimelineClip[] => {
    const sourceSeconds = numberConfig(node, "duration_seconds");
    if (!sourceSeconds || sourceSeconds <= 0) return [];
    const trimIn = clamp(numberConfig(node, "trim_in_seconds") ?? 0, 0, sourceSeconds - MIN_CLIP_SECONDS);
    const trimOut = clamp(numberConfig(node, "trim_out_seconds") ?? sourceSeconds, trimIn + MIN_CLIP_SECONDS, sourceSeconds);
    const thumb = node.data.config.thumbnail_url;
    return [{
      id: node.id,
      order: index + 1,
      title: node.data.title || `Shot ${index + 1}`,
      sourceSeconds, trimIn, trimOut,
      thumbUrl: typeof thumb === "string" && (thumb.startsWith("/") || thumb.startsWith("https://")) ? thumb : undefined,
    }];
  }).map((clip, index) => ({ ...clip, order: index + 1 }));
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function snap(value: number, step = SNAP_SECONDS): number {
  return step > 0 ? Math.round(value / step) * step : value;
}

/** Move one trim edge by `deltaSeconds`. The clip never gets shorter than MIN_CLIP_SECONDS and stays inside its source. */
export function trimEdge(clip: TimelineClip, edge: "in" | "out", deltaSeconds: number, snapStep: number = SNAP_SECONDS): Pick<TimelineClip, "trimIn" | "trimOut"> {
  if (edge === "in") {
    const next = clamp(snap(clip.trimIn + deltaSeconds, snapStep), 0, clip.trimOut - MIN_CLIP_SECONDS);
    return { trimIn: round3(next), trimOut: clip.trimOut };
  }
  const next = clamp(snap(clip.trimOut + deltaSeconds, snapStep), clip.trimIn + MIN_CLIP_SECONDS, clip.sourceSeconds);
  return { trimIn: clip.trimIn, trimOut: round3(next) };
}

/** Set an exact In / Out / Length value (inspector fields). Length edits move the Out point. */
export function setTrimField(clip: TimelineClip, field: "in" | "out" | "length", seconds: number): Pick<TimelineClip, "trimIn" | "trimOut"> {
  if (!Number.isFinite(seconds)) return { trimIn: clip.trimIn, trimOut: clip.trimOut };
  if (field === "in") return trimEdge({ ...clip }, "in", seconds - clip.trimIn, 0);
  if (field === "out") return trimEdge({ ...clip }, "out", seconds - clip.trimOut, 0);
  return trimEdge({ ...clip }, "out", clip.trimIn + seconds - clip.trimOut, 0);
}

/** New order of ids after moving `id` by `offset` places (negative = earlier). Out-of-range moves are clamped. */
export function moveClip(ids: string[], id: string, offset: number): string[] {
  const from = ids.indexOf(id);
  if (from < 0) return ids;
  const to = clamp(from + offset, 0, ids.length - 1);
  if (to === from) return ids;
  const next = ids.slice();
  next.splice(from, 1);
  next.splice(to, 0, id);
  return next;
}

/** Insertion index when a clip is dropped at horizontal position `x` (px from the track start). */
export function dropIndex(clips: Pick<TimelineClip, "id" | "trimIn" | "trimOut">[], draggedId: string, x: number, pxPerSecond = PX_PER_SECOND): number {
  const others = clips.filter((clip) => clip.id !== draggedId);
  let cursor = 0;
  for (let index = 0; index < others.length; index += 1) {
    const width = clipLength(others[index]!) * pxPerSecond;
    if (x < cursor + width / 2) return index;
    cursor += width;
  }
  return others.length;
}

export function totalSeconds(clips: Pick<TimelineClip, "trimIn" | "trimOut">[]): number {
  return round3(clips.reduce((sum, clip) => sum + clipLength(clip), 0));
}

/** 0:03:06 style: minutes:seconds:frames at 24 fps. */
export function timecode(seconds: number): string {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const wholeSeconds = Math.floor(safe % 60);
  const frames = Math.round((safe - Math.floor(safe)) * 24) % 24;
  return `${String(minutes).padStart(2, "0")}:${String(wholeSeconds).padStart(2, "0")}:${String(frames).padStart(2, "0")}`;
}

export function secondsLabel(seconds: number): string {
  return `${round3(seconds).toFixed(2)}s`;
}

/** "4.2", "0:04.2" and "4,2" all mean 4.2 seconds. Anything else is rejected, not guessed. */
export function parseSeconds(value: string): number | null {
  const text = value.trim().replace(",", ".");
  const match = /^(?:(\d+):)?(\d+(?:\.\d+)?)$/.exec(text);
  if (!match) return null;
  const seconds = Number(match[1] ?? 0) * 60 + Number(match[2]);
  return Number.isFinite(seconds) ? seconds : null;
}
