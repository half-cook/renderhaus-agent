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
  /** Linear audio gain. Omitted means full volume. */
  volume?: number;
  fit?: "cover" | "contain";
  positionX?: number;
  positionY?: number;
  scale?: number;
  opacity?: number;
  rotation?: number;
  playbackRate?: number;
  fadeIn?: number;
  fadeOut?: number;
  motion?: "none" | "zoom_in" | "zoom_out" | "pan_left" | "pan_right";
  transition?: "cut" | "fade" | "dip_to_black";
}

export interface Gap extends TrackItemBase {
  type: "gap";
}

export interface Transition extends TrackItemBase {
  type: "transition";
  kind: "cut" | "fade" | "dipToBlack";
}

export interface TextOverlay extends TrackItemBase {
  type: "text";
  text: string;
  position: "top" | "center" | "bottom";
  fontSize?: number;
  color?: string;
  backgroundColor?: string;
  fontWeight?: number;
  fadeIn?: number;
  fadeOut?: number;
}

export type TrackItem = Clip | Gap | Transition | TextOverlay;

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
