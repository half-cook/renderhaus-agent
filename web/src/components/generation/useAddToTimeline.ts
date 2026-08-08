import { useCallback } from "react";
import { addClipCommand } from "@/lib/timeline/commands";
import { useTimelineStore } from "@/lib/timeline/store";
import type { Asset, Clip } from "@/lib/timeline/types";
import type { Job } from "@/lib/api/types";

const VIDEO_TRACK_ID = "video-1";
const AUDIO_TRACK_ID = "audio-1"; // music generations land here -- no dedicated music track exists

// The decision-#1 seam ("Approach A -- Unified Timeline", plan §0/§6.7):
// generated clips don't get a second timeline widget, they land on the
// *existing* CanvasTimeline via the same addClipCommand + getState().
// runCommand(...) dispatch lib/timeline/import.ts already uses for
// drag/drop imports -- mirrored here rather than reused directly, since
// import.ts's clipForAsset is file-local and this is a different Asset
// source (a finished generation job, not a File).
export function useAddToTimeline() {
  return useCallback((job: Job) => {
    if (job.status !== "complete" || !job.media_url || job.media_type === "image") return;

    const trackId = job.media_type === "music" ? AUDIO_TRACK_ID : VIDEO_TRACK_ID;
    const durationSec = job.duration_seconds ?? 0;

    const asset: Asset = {
      id: crypto.randomUUID(),
      name: job.prompt.slice(0, 60) || job.id,
      kind: job.media_type === "music" ? "audio" : job.media_type,
      url: job.media_url,
      durationSec,
    };

    const track = useTimelineStore.getState().document.tracks.find((t) => t.id === trackId);
    const trackEnd =
      track?.items.reduce((max, item) => Math.max(max, item.start + item.duration), 0) ?? 0;

    const clip: Clip = {
      type: "clip",
      id: crypto.randomUUID(),
      assetId: asset.id,
      start: trackEnd,
      duration: durationSec,
      sourceIn: 0,
      sourceOut: durationSec,
    };

    useTimelineStore.getState().runCommand(addClipCommand(trackId, asset, clip));
  }, []);
}
