/**
 * OTIO-inspired timeline schema (design/ARCHITECTURE.md §13.7): Timeline -> Track[] ->
 * TrackItem[], with Transition modeled as its own item type rather than a
 * clip property. Only Clip is actually produced by a Command tonight; Gap
 * and Transition exist now so later Commands don't need a schema migration.
 */

export type TrackKind = "video" | "audio" | "caption" | "overlay";

export interface Asset {
  id: string;
  name: string;
  kind: "video" | "audio" | "image";
  /** Object URL for local/dev use; becomes a remote proxy URL once upload exists. */
  url: string;
  durationSec: number;
}

interface TrackItemBase {
  id: string;
  /** Position on the track, in seconds. */
  start: number;
  /** Length of this item on the timeline, in seconds. */
  duration: number;
}

export interface Clip extends TrackItemBase {
  type: "clip";
  assetId: string;
  /** In/out points within the source asset, in seconds. */
  sourceIn: number;
  sourceOut: number;
}

export interface Gap extends TrackItemBase {
  type: "gap";
}

export interface Transition extends TrackItemBase {
  type: "transition";
  kind: "cut" | "fade" | "dipToBlack";
}

export type TrackItem = Clip | Gap | Transition;

export interface Track {
  id: string;
  kind: TrackKind;
  name: string;
  items: TrackItem[];
}

export interface TimelineDocument {
  id: string;
  name: string;
  tracks: Track[];
  assets: Asset[];
}
