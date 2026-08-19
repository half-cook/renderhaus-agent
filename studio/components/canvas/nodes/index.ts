import type { NodeTypes } from "@xyflow/react";
import { AudioNode } from "./AudioNode";
import { GeneratorNode } from "./GeneratorNode";
import { ImageNode } from "./ImageNode";
import { StoryboardNode } from "./StoryboardNode";
import { TextNode } from "./TextNode";
import { VideoNode } from "./VideoNode";

export const nodeTypes: NodeTypes = {
  text: TextNode,
  image: ImageNode,
  video: VideoNode,
  audio: AudioNode,
  generator: GeneratorNode,
  storyboard: StoryboardNode,
};
