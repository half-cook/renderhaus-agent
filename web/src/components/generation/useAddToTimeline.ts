import { useCallback } from "react";
import { addClipCommand } from "@/lib/timeline/commands";
import { useTimelineStore } from "@/lib/timeline/store";
import type { Asset, Clip } from "@/lib/timeline/types";
import type { Job } from "@/lib/api/types";

const VIDEO_TRACK_ID = "video-1";
const AUDIO_TRACK_ID = "audio-1"; // music generations land here -- no dedicated music track exists

// Video generations always get a real duration_seconds at request time
// (server/app.py: 4-12s, required). Music never does -- it's null at
// creation and, traced through server/app.py's _poll_provider /
// _attach_generation_output, nothing in the completion path ever sets it
// either. Falling back to 0 would create an invisible, zero-length clip on
// the timeline, so probe the real duration client-side instead -- mirrors
// lib/timeline/import.ts's readVideoDuration for the same reason (never
// trust upstream metadata that might not exist).
function readAudioDuration(url: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const audio = document.createElement("audio");
    audio.preload = "metadata";
    audio.style.cssText = "position:fixed;width:0;height:0;opacity:0;pointer-events:none;";
    document.body.appendChild(audio);

    function cleanup() {
      audio.remove();
    }
    audio.onloadedmetadata = () => {
      resolve(audio.duration);
      cleanup();
    };
    audio.onerror = () => {
      cleanup();
      reject(new Error(`Could not read audio metadata for ${url}`));
    };
    audio.src = url;
    audio.load();
  });
}

// The decision-#1 seam ("Approach A -- Unified Timeline", plan §0/§6.7):
// generated clips don't get a second timeline widget, they land on the
// *existing* CanvasTimeline via the same addClipCommand + getState().
// runCommand(...) dispatch lib/timeline/import.ts already uses for
// drag/drop imports -- mirrored here rather than reused directly, since
// import.ts's clipForAsset is file-local and this is a different Asset
// source (a finished generation job, not a File).
export function useAddToTimeline() {
  return useCallback(async (job: Job) => {
    if (job.status !== "complete" || !job.media_url || job.media_type === "image") return;

    const trackId = job.media_type === "music" ? AUDIO_TRACK_ID : VIDEO_TRACK_ID;
    let durationSec = job.duration_seconds ?? 0;
    if (job.media_type === "music" && !durationSec) {
      try {
        durationSec = await readAudioDuration(job.media_url);
      } catch {
        return; // don't place an unusable zero-length clip
      }
    }

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
