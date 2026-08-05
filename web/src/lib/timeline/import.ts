import { type ChangeEvent, useCallback, useRef } from "react";
import { addClipCommand } from "./commands";
import { useTimelineStore } from "./store";
import type { Asset, Clip } from "./types";

export const VIDEO_TRACK_ID = "video-1";

// A fully detached <video> (never attached to the DOM) doesn't reliably fire
// loadedmetadata in every browser — attach it off-screen instead.
function readVideoDuration(url: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    video.preload = "metadata";
    video.muted = true;
    video.style.cssText = "position:fixed;width:0;height:0;opacity:0;pointer-events:none;";
    document.body.appendChild(video);

    function cleanup() {
      video.remove();
    }
    video.onloadedmetadata = () => {
      resolve(video.duration);
      cleanup();
    };
    video.onerror = () => {
      cleanup();
      reject(new Error(`Could not read video metadata for ${url}`));
    };
    video.src = url;
    video.load();
  });
}

/**
 * Proxy-transcode on import (ARCHITECTURE.md §6, §11) — never edit against
 * the original upload. Posts to the local dev stand-in for the managed
 * transcode job (`/api/transcode`); falls back to the raw blob URL if that
 * fails (e.g. ffmpeg missing) so import degrades instead of hard-failing —
 * the codec-support banner in TimelineComposition still catches an
 * undecodable fallback.
 */
async function transcodeToProxy(file: File): Promise<string> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch("/api/transcode", { method: "POST", body: formData });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const message =
      body && typeof body === "object" && "error" in body ? String(body.error) : response.statusText;
    throw new Error(`Transcode failed: ${message}`);
  }
  const { url } = (await response.json()) as { url: string };
  return url;
}

async function assetFromFile(file: File): Promise<Asset> {
  const blobUrl = URL.createObjectURL(file);
  let durationSec: number;
  try {
    durationSec = await readVideoDuration(blobUrl);
  } finally {
    URL.revokeObjectURL(blobUrl);
  }

  let url: string;
  try {
    url = await transcodeToProxy(file);
  } catch (err) {
    console.warn("Proxy transcode failed, previewing original upload instead:", err);
    url = URL.createObjectURL(file);
  }

  return { id: crypto.randomUUID(), name: file.name, kind: "video", url, durationSec };
}

function clipForAsset(asset: Asset, start: number): Clip {
  return {
    type: "clip",
    id: crypto.randomUUID(),
    assetId: asset.id,
    start,
    duration: asset.durationSec,
    sourceIn: 0,
    sourceOut: asset.durationSec,
  };
}

/**
 * Imports each video file onto the video track, sequentially — each clip is
 * appended after whatever's already there. Reads fresh state via getState()
 * on every iteration rather than closing over a stale `document`, since this
 * loop awaits (video metadata) between commands.
 */
export async function importVideoFiles(files: Iterable<File>): Promise<void> {
  for (const file of files) {
    if (!file.type.startsWith("video/")) continue;
    const asset = await assetFromFile(file);
    const track = useTimelineStore
      .getState()
      .document.tracks.find((t) => t.id === VIDEO_TRACK_ID);
    const trackEnd =
      track?.items.reduce((max, item) => Math.max(max, item.start + item.duration), 0) ?? 0;
    const clip = clipForAsset(asset, trackEnd);
    useTimelineStore.getState().runCommand(addClipCommand(VIDEO_TRACK_ID, asset, clip));
  }
}

/** Hidden-input file picker, shared by every "import media" entry point. */
export function useFilePicker(onFiles: (files: File[]) => void | Promise<void>) {
  const inputRef = useRef<HTMLInputElement>(null);

  const open = useCallback(() => inputRef.current?.click(), []);

  const onChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      // Copy to a plain array before clearing value — clearing
      // event.target.value also empties the live event.target.files
      // FileList, taking a previously-captured reference to it down too.
      const files = event.target.files ? Array.from(event.target.files) : [];
      event.target.value = ""; // allow re-selecting the same file next time
      if (!files.length) return;
      Promise.resolve(onFiles(files)).catch((err: unknown) => {
        console.error("Import failed:", err);
      });
    },
    [onFiles],
  );

  return { inputRef, open, onChange };
}
