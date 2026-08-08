import type { Asset, Clip, TimelineDocument } from "./types";

/**
 * Every timeline mutation is one of these (design/ARCHITECTURE.md §6). The manual
 * UI and the future agent orchestrator both produce Command objects — there
 * is no other way to mutate a TimelineDocument.
 */
export interface Command {
  label: string;
  do(doc: TimelineDocument): TimelineDocument;
  undo(doc: TimelineDocument): TimelineDocument;
}

function mapTrack(
  doc: TimelineDocument,
  trackId: string,
  fn: (items: TimelineDocument["tracks"][number]["items"]) => TimelineDocument["tracks"][number]["items"],
): TimelineDocument {
  return {
    ...doc,
    tracks: doc.tracks.map((track) =>
      track.id === trackId ? { ...track, items: fn(track.items) } : track,
    ),
  };
}

/** Registers an Asset on the document and places a Clip for it on a track. */
export function addClipCommand(trackId: string, asset: Asset, clip: Clip): Command {
  return {
    label: `Add "${asset.name}"`,
    do(doc) {
      const withAsset: TimelineDocument = {
        ...doc,
        assets: doc.assets.some((a) => a.id === asset.id) ? doc.assets : [...doc.assets, asset],
      };
      return mapTrack(withAsset, trackId, (items) => [...items, clip]);
    },
    undo(doc) {
      // Leaves the Asset registered even though the Clip is gone — undoing a
      // placement isn't the same as undoing an import. Fine for tonight,
      // since nothing else references assets yet.
      return mapTrack(doc, trackId, (items) => items.filter((item) => item.id !== clip.id));
    },
  };
}
