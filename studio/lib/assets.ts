import { useEffect, useState } from "react";
import { studioFetch } from "./authenticated-fetch";
import type { StudioAsset } from "./types";

type PlaybackTicket = { url: string; expiresAt: number };

const playbackTickets = new Map<string, PlaybackTicket>();
const playbackRequests = new Map<string, Promise<PlaybackTicket>>();

async function studioAssetPlaybackUrl(asset: StudioAsset, refresh = false): Promise<string> {
  if (refresh) playbackTickets.delete(asset.versionId);
  const cached = playbackTickets.get(asset.versionId);
  if (cached && cached.expiresAt > Date.now() + 30_000) {
    return cached.url;
  }
  const pending = playbackRequests.get(asset.versionId);
  if (pending) {
    return (await pending).url;
  }
  const request = (async () => {
    const response = await studioFetch(
      `/api/studio/assets/${encodeURIComponent(asset.versionId)}/playback`,
      { method: "POST" },
    );
    const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    if (!response.ok || typeof payload.url !== "string") {
      throw new Error(typeof payload.detail === "string" ? payload.detail : "Could not load media preview.");
    }
    const ticket = {
      url: payload.url,
      expiresAt:
        typeof payload.expires_at === "number"
          ? payload.expires_at * 1_000
          : Date.now() + 10 * 60_000,
    };
    playbackTickets.set(asset.versionId, ticket);
    return ticket;
  })();
  playbackRequests.set(asset.versionId, request);
  try {
    return (await request).url;
  } finally {
    playbackRequests.delete(asset.versionId);
  }
}

type AssetPlayback = { status: "loading" } | { status: "ready"; url: string } | { status: "error"; message: string };

export function useStudioAssetPlayback(asset?: StudioAsset, attempt = 0): AssetPlayback {
  const [result, setResult] = useState<{ versionId?: string; attempt: number; playback: AssetPlayback }>({
    attempt, playback: { status: "loading" },
  });

  useEffect(() => {
    let active = true;
    if (!asset) {
      return () => {
        active = false;
      };
    }
    setResult({ versionId: asset.versionId, attempt, playback: { status: "loading" } });
    void studioAssetPlaybackUrl(asset, attempt > 0)
      .then((next) => {
        if (active) setResult({ versionId: asset.versionId, attempt, playback: { status: "ready", url: next } });
      })
      .catch(() => {
        if (active) setResult({ versionId: asset.versionId, attempt, playback: {
          status: "error", message: "A saved preview could not be loaded. Reload it or keep the original.",
        } });
      });
    return () => {
      active = false;
    };
  }, [asset?.versionId, attempt]);

  return asset && result.versionId === asset.versionId && result.attempt === attempt
    ? result.playback : { status: "loading" };
}

export function useStudioAssetPlaybackUrl(asset?: StudioAsset): string | undefined {
  const playback = useStudioAssetPlayback(asset);
  return playback.status === "ready" ? playback.url : undefined;
}

export function studioAssetHandle(asset: StudioAsset): string {
  return `renderhaus-asset://${asset.versionId}`;
}
