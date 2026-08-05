import { useEffect, useRef } from "react";
import { AbsoluteFill, Sequence, Video, useVideoConfig } from "remotion";
import type { Asset, Clip, TimelineDocument } from "@/lib/timeline/types";

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

function TimelineClip({ clip, asset, onStatusChange }: TimelineClipProps) {
  const { fps } = useVideoConfig();
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
      style={{ width: "100%", height: "100%", objectFit: "contain" }}
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

export interface TimelineCompositionProps {
  document: TimelineDocument;
  onClipStatusChange?: (assetId: string, status: ClipDecodeStatus) => void;
}

/**
 * Maps the OTIO-inspired timeline document (ARCHITECTURE.md §13.7) straight
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
        .filter((track) => track.kind === "video")
        .flatMap((track) => track.items)
        .filter((item): item is Clip => item.type === "clip")
        .map((clip) => {
          const asset = document.assets.find((a) => a.id === clip.assetId);
          if (!asset || asset.kind !== "video") return null;
          const from = Math.round(clip.start * fps);
          const durationInFrames = Math.max(1, Math.round(clip.duration * fps));
          return (
            <Sequence key={clip.id} from={from} durationInFrames={durationInFrames}>
              <TimelineClip clip={clip} asset={asset} onStatusChange={onClipStatusChange} />
            </Sequence>
          );
        })}
    </AbsoluteFill>
  );
}
