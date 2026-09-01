import type { TimelineDocument, TrackKind } from "@/lib/timeline/types";

export interface RenderClip {
  id: string;
  track: number;
  start: number;
  duration: number;
  color: string;
  label: string;
}

const TRACK_COLOR: Record<TrackKind, string> = {
  video: "#6366f1",
  audio: "#10b981",
  caption: "#f59e0b",
  overlay: "#ec4899",
};

const TRANSITION_COLOR = "#a3a3a3";
const MIN_TIMELINE_DURATION_SEC = 10; // floor so an empty timeline still has something to look at

/** Flattens the real timeline document into the flat draw-list the canvas renderer expects. */
export function toRenderClips(document: TimelineDocument): {
  clips: RenderClip[];
  duration: number;
  trackCount: number;
} {
  const clips: RenderClip[] = [];
  let duration = MIN_TIMELINE_DURATION_SEC;

  document.tracks.forEach((track, trackIndex) => {
    for (const item of track.items) {
      duration = Math.max(duration, item.start + item.duration);
      if (item.type === "gap") continue; // nothing to draw

      const label =
        item.type === "clip"
          ? (document.assets.find((a) => a.id === item.assetId)?.name ?? item.assetId)
          : item.type === "text"
            ? item.text
            : item.kind;

      clips.push({
        id: item.id,
        track: trackIndex,
        start: item.start,
        duration: item.duration,
        color: item.type === "transition" ? TRANSITION_COLOR : TRACK_COLOR[track.kind],
        label,
      });
    }
  });

  return { clips, duration, trackCount: document.tracks.length };
}
