import { useEffect, useRef } from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  Video,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { Asset, Clip, TextOverlay, TimelineDocument } from "@/lib/timeline/types";

// How long to wait for a real decoded frame before concluding the codec
// isn't renderable (e.g. ProRes — plenty of .mov exports from pro NLEs use
// it, and Chrome has no ProRes video decoder at all, though it'll happily
// play a PCM/AAC audio track from the same container). Same signal as before
// (requestVideoFrameCallback on a raw <video>), now sourced from Remotion's
// own onVideoFrame callback on <Video>.
const FRAME_SUPPORT_TIMEOUT_MS = 1500;

export type ClipDecodeStatus = "checking" | "ok" | "unsupported";

interface TimelineClipProps {
  clip: Clip;
  asset: Asset;
  onStatusChange?: (assetId: string, status: ClipDecodeStatus) => void;
}

function visualStyle(clip: Clip, frame: number, fps: number) {
  const durationFrames = Math.max(1, Math.round(clip.duration * fps));
  const fadeInFrames = Math.max(0, Math.round((clip.fadeIn ?? 0) * fps));
  const fadeOutFrames = Math.max(0, Math.round((clip.fadeOut ?? 0) * fps));
  const fadeIn = fadeInFrames
    ? interpolate(frame, [0, fadeInFrames], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 1;
  const fadeOut = fadeOutFrames
    ? interpolate(frame, [durationFrames - fadeOutFrames, durationFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 1;
  const progress = Math.max(0, Math.min(1, frame / durationFrames));
  const baseScale = clip.scale ?? 1;
  const motionScale = clip.motion === "zoom_in"
    ? 1 + progress * 0.08
    : clip.motion === "zoom_out"
      ? 1.08 - progress * 0.08
      : 1;
  const pan = clip.motion === "pan_left"
    ? 4 - progress * 8
    : clip.motion === "pan_right"
      ? -4 + progress * 8
      : 0;
  return {
    width: "100%",
    height: "100%",
    objectFit: clip.fit ?? "cover",
    objectPosition: `${(clip.positionX ?? 0.5) * 100}% ${(clip.positionY ?? 0.5) * 100}%`,
    opacity: (clip.opacity ?? 1) * Math.min(fadeIn, fadeOut),
    transform: `translateX(${pan}%) scale(${baseScale * motionScale}) rotate(${clip.rotation ?? 0}deg)`,
  } as const;
}

function TimelineClip({ clip, asset, onStatusChange }: TimelineClipProps) {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const firedRef = useRef(false);

  useEffect(() => {
    firedRef.current = false;
    onStatusChange?.(asset.id, "checking");
    const timeout = window.setTimeout(() => {
      if (!firedRef.current) onStatusChange?.(asset.id, "unsupported");
    }, FRAME_SUPPORT_TIMEOUT_MS);
    return () => window.clearTimeout(timeout);
  }, [asset.id, onStatusChange]);

  return (
    <Video
      src={asset.url}
      trimBefore={Math.round(clip.sourceIn * fps)}
      trimAfter={Math.round(clip.sourceOut * fps)}
      playbackRate={clip.playbackRate ?? 1}
      style={visualStyle(clip, frame, fps)}
      onVideoFrame={(_frame, _now, metadata) => {
        // Remotion's <Video> calls onVideoFrame once eagerly on mount, before
        // it has decoded anything (remotion/dist/.../emit-video-frame.js) —
        // only calls driven by a real requestVideoFrameCallback firing carry
        // `metadata`. Trusting the eager call marked undecodable codecs (e.g.
        // ProRes/HEVC .mov from a phone) "ok" immediately, so the
        // codec-unsupported banner never showed and the preview just stayed
        // silently black.
        if (!metadata) return;
        if (firedRef.current) return;
        firedRef.current = true;
        onStatusChange?.(asset.id, "ok");
      }}
      onError={() => onStatusChange?.(asset.id, "unsupported")}
    />
  );
}

function TimelineImage({ clip, asset }: { clip: Clip; asset: Asset }) {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  return <Img src={asset.url} style={visualStyle(clip, frame, fps)} />;
}

function TimelineAudio({ clip, asset }: { clip: Clip; asset: Asset }) {
  const { fps } = useVideoConfig();
  const durationFrames = Math.max(1, Math.round(clip.duration * fps));
  const fadeInFrames = Math.max(0, Math.round((clip.fadeIn ?? 0) * fps));
  const fadeOutFrames = Math.max(0, Math.round((clip.fadeOut ?? 0) * fps));
  return (
    <Audio
      src={asset.url}
      trimBefore={Math.round(clip.sourceIn * fps)}
      trimAfter={Math.round(clip.sourceOut * fps)}
      volume={(frame) => {
        const fadeIn = fadeInFrames
          ? interpolate(frame, [0, fadeInFrames], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
          : 1;
        const fadeOut = fadeOutFrames
          ? interpolate(frame, [durationFrames - fadeOutFrames, durationFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
          : 1;
        return (clip.volume ?? 1) * Math.min(fadeIn, fadeOut);
      }}
    />
  );
}

function TimelineText({ overlay }: { overlay: TextOverlay }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const durationFrames = Math.max(1, Math.round(overlay.duration * fps));
  const fadeInFrames = Math.max(0, Math.round((overlay.fadeIn ?? 0) * fps));
  const fadeOutFrames = Math.max(0, Math.round((overlay.fadeOut ?? 0) * fps));
  const fadeIn = fadeInFrames
    ? interpolate(frame, [0, fadeInFrames], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 1;
  const fadeOut = fadeOutFrames
    ? interpolate(frame, [durationFrames - fadeOutFrames, durationFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 1;
  const justifyContent = overlay.position === "top"
    ? "flex-start"
    : overlay.position === "bottom"
      ? "flex-end"
      : "center";
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent, padding: "8%", opacity: Math.min(fadeIn, fadeOut) }}>
      <div style={{
        maxWidth: "90%",
        padding: "0.18em 0.35em",
        borderRadius: "0.18em",
        backgroundColor: overlay.backgroundColor ?? "transparent",
        color: overlay.color ?? "#ffffff",
        fontFamily: "Inter, Arial, sans-serif",
        fontSize: overlay.fontSize ?? 64,
        fontWeight: overlay.fontWeight ?? 700,
        lineHeight: 1.05,
        textAlign: "center",
        textShadow: "0 2px 18px rgba(0,0,0,0.65)",
        whiteSpace: "pre-wrap",
      }}>
        {overlay.text}
      </div>
    </AbsoluteFill>
  );
}

export interface TimelineCompositionProps {
  document: TimelineDocument;
  onClipStatusChange?: (assetId: string, status: ClipDecodeStatus) => void;
}

/**
 * Maps the OTIO-inspired timeline document (design/ARCHITECTURE.md §13.7) straight
 * to Remotion composition props — this component is the shared render
 * target for both the interactive Player (here) and, later, the headless
 * Node renderer/Lambda export (§13.6), so it deliberately holds no
 * Player-only or export-only logic.
 */
export function TimelineComposition({ document, onClipStatusChange }: TimelineCompositionProps) {
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {document.tracks
        .filter((track) => track.kind === "video" || track.kind === "overlay")
        .flatMap((track) => track.items)
        .filter((item): item is Clip => item.type === "clip")
        .map((clip) => {
          const asset = document.assets.find((a) => a.id === clip.assetId);
          if (!asset || !["video", "image"].includes(asset.kind)) return null;
          const from = Math.round(clip.start * fps);
          const durationInFrames = Math.max(1, Math.round(clip.duration * fps));
          return (
            <Sequence key={clip.id} from={from} durationInFrames={durationInFrames}>
              {asset.kind === "video" ? (
                <TimelineClip clip={clip} asset={asset} onStatusChange={onClipStatusChange} />
              ) : (
                <TimelineImage clip={clip} asset={asset} />
              )}
            </Sequence>
          );
        })}
      {document.tracks
        .filter((track) => track.kind === "audio")
        .flatMap((track) => track.items)
        .filter((item): item is Clip => item.type === "clip")
        .map((clip) => {
          const asset = document.assets.find((item) => item.id === clip.assetId);
          if (!asset || asset.kind !== "audio") return null;
          const from = Math.round(clip.start * fps);
          const durationInFrames = Math.max(1, Math.round(clip.duration * fps));
          return (
            <Sequence key={clip.id} from={from} durationInFrames={durationInFrames}>
              <TimelineAudio clip={clip} asset={asset} />
            </Sequence>
          );
        })}
      {document.tracks
        .filter((track) => track.kind === "caption")
        .flatMap((track) => track.items)
        .filter((item): item is TextOverlay => item.type === "text")
        .map((overlay) => (
          <Sequence
            key={overlay.id}
            from={Math.round(overlay.start * fps)}
            durationInFrames={Math.max(1, Math.round(overlay.duration * fps))}
          >
            <TimelineText overlay={overlay} />
          </Sequence>
        ))}
    </AbsoluteFill>
  );
}
