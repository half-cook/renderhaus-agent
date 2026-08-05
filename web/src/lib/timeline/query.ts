import type { Clip, TimelineDocument } from "./types";

/** Exact end of the last item on any track — no cosmetic flooring, unlike the canvas renderer's draw-list. */
export function getTimelineDuration(document: TimelineDocument): number {
  let duration = 0;
  for (const track of document.tracks) {
    for (const item of track.items) {
      duration = Math.max(duration, item.start + item.duration);
    }
  }
  return duration;
}

export function findClipAtTime(
  document: TimelineDocument,
  trackId: string,
  timeSec: number,
): Clip | null {
  const track = document.tracks.find((t) => t.id === trackId);
  if (!track) return null;
  for (const item of track.items) {
    if (item.type === "clip" && timeSec >= item.start && timeSec < item.start + item.duration) {
      return item;
    }
  }
  return null;
}

export function nextClip(document: TimelineDocument, trackId: string, afterStart: number): Clip | null {
  const track = document.tracks.find((t) => t.id === trackId);
  if (!track) return null;
  const clips = track.items.filter((item): item is Clip => item.type === "clip" && item.start > afterStart);
  clips.sort((a, b) => a.start - b.start);
  return clips[0] ?? null;
}
