import { Composition, type CalculateMetadataFunction } from "remotion";
import {
  TimelineComposition,
  type TimelineCompositionProps,
} from "../components/editor/remotion/TimelineComposition";
import {
  COMPOSITION_FPS,
  COMPOSITION_HEIGHT,
  COMPOSITION_WIDTH,
} from "../components/editor/remotion/constants";
import { getTimelineDuration } from "../lib/timeline/query";
import type { TimelineDocument } from "../lib/timeline/types";

export const RENDERHAUS_COMPOSITION_ID = "RenderhausTimeline";

export type RenderhausCompositionProps = TimelineCompositionProps & Record<string, unknown> & {
  renderConfig?: {
    fps?: number;
    width?: number;
    height?: number;
  };
};

const EMPTY_DOCUMENT: TimelineDocument = {
  id: "renderhaus-empty",
  name: "Renderhaus timeline",
  assets: [],
  tracks: [
    { id: "video-1", kind: "video", name: "Video", items: [] },
    { id: "audio-1", kind: "audio", name: "Audio", items: [] },
  ],
};

const calculateMetadata: CalculateMetadataFunction<RenderhausCompositionProps> = ({ props }) => {
  const fps = props.renderConfig?.fps ?? COMPOSITION_FPS;
  return {
    durationInFrames: Math.max(1, Math.ceil(getTimelineDuration(props.document) * fps)),
    fps,
    width: props.renderConfig?.width ?? COMPOSITION_WIDTH,
    height: props.renderConfig?.height ?? COMPOSITION_HEIGHT,
  };
};

function RenderhausComposition(props: RenderhausCompositionProps) {
  return <TimelineComposition document={props.document} />;
}

export function RemotionRoot() {
  return (
    <Composition
      id={RENDERHAUS_COMPOSITION_ID}
      component={RenderhausComposition}
      defaultProps={{ document: EMPTY_DOCUMENT }}
      calculateMetadata={calculateMetadata}
      durationInFrames={1}
      fps={COMPOSITION_FPS}
      width={COMPOSITION_WIDTH}
      height={COMPOSITION_HEIGHT}
    />
  );
}
