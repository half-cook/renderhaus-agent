import { useEffect, useState } from "react";
import { studioFetch } from "./authenticated-fetch";
import type { StudioAsset } from "./types";

type PlaybackTicket = { url: string; expiresAt: number };

const playbackTickets = new Map<string, PlaybackTicket>();
const playbackRequests = new Map<string, Promise<PlaybackTicket>>();

export async function studioAssetPlaybackUrl(asset: StudioAsset): Promise<string> {
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

export function useStudioAssetPlaybackUrl(asset?: StudioAsset): string | undefined {
  const [url, setUrl] = useState<string>();

  useEffect(() => {
    let active = true;
    if (!asset) {
      setUrl(undefined);
      return () => {
        active = false;
      };
    }
    void studioAssetPlaybackUrl(asset)
      .then((next) => {
        if (active) setUrl(next);
      })
      .catch(() => {
        if (active) setUrl(undefined);
      });
    return () => {
      active = false;
    };
  }, [asset?.versionId]);

  return url;
}

export function studioAssetHandle(asset: StudioAsset): string {
  return `renderhaus-asset://${asset.versionId}`;
}

export function sameStudioAsset(left: StudioAsset, right: StudioAsset): boolean {
  return left.versionId === right.versionId;
}
