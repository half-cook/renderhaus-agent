import type { CreativeNodeKind, PortDataType, ToolDefinition } from "./types";

export const CREATIVE_TOOLS: ToolDefinition[] = [
  {
    id: "image.generate",
    displayName: "Image",
    description: "Generate a still from a prompt",
    category: "image",
    providerId: "seedream",
    toolName: "text_to_image",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "image", label: "Image", dataType: "image" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "size"],
  },
  {
    id: "image.edit",
    displayName: "Edit image",
    description: "Restyle an image from a prompt",
    category: "image",
    providerId: "seedream",
    toolName: "image_to_image",
    inputPorts: [
      { id: "image", label: "Image", dataType: "image", targetField: "image_path_or_url", required: true },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "image", label: "Image", dataType: "image" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "size", "image_path_or_url"],
  },
  {
    id: "video.generate",
    displayName: "Video",
    description: "Generate a clip from a prompt",
    category: "video",
    providerId: "seedance",
    toolName: "text_to_video",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "duration_seconds", "resolution"],
    pollTool: "get_video_task",
  },
  {
    id: "video.fromImage",
    displayName: "Image to video",
    description: "Animate a still into a clip",
    category: "video",
    providerId: "seedance",
    toolName: "image_to_video",
    inputPorts: [
      { id: "image", label: "Image", dataType: "image", targetField: "image_path_or_url", required: true },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "duration_seconds", "resolution", "image_path_or_url"],
    pollTool: "get_video_task",
  },
  {
    id: "music.generate",
    displayName: "Music",
    description: "Generate a song from a prompt",
    category: "audio",
    providerId: "mureka",
    toolName: "create_song_from_prompt",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "audio", label: "Audio", dataType: "audio" }],
    primaryFields: ["prompt", "model", "gender"],
    pollTool: "query_music_task",
  },
  {
    id: "voice.generate",
    displayName: "Voiceover",
    description: "Read text as speech",
    category: "audio",
    providerId: "fish_audio",
    toolName: "generate_speech",
    inputPorts: [{ id: "text", label: "Script", dataType: "text", targetField: "text", required: true }],
    outputPorts: [{ id: "audio", label: "Audio", dataType: "audio" }],
    primaryFields: ["text", "voice", "model", "output_format"],
  },
];

export function toolById(id: string | undefined): ToolDefinition | undefined {
  if (!id) {
    return undefined;
  }
  return CREATIVE_TOOLS.find((tool) => tool.id === id);
}

export function toolsForKind(kind: CreativeNodeKind): ToolDefinition[] {
  return CREATIVE_TOOLS.filter((tool) => tool.category === kind);
}

export function defaultToolForRail(
  rail: "image" | "video" | "audio" | "voice",
): ToolDefinition | undefined {
  switch (rail) {
    case "image":
      return toolById("image.generate");
    case "video":
      return toolById("video.generate");
    case "audio":
      return toolById("music.generate");
    case "voice":
      return toolById("voice.generate");
    default: {
      const exhaustive: never = rail;
      return exhaustive;
    }
  }
}

export function portsForNode(toolId: string | undefined, kind: CreativeNodeKind): {
  inputs: ToolDefinition["inputPorts"];
  outputs: ToolDefinition["outputPorts"];
} {
  const tool = toolById(toolId);
  if (tool) {
    return { inputs: tool.inputPorts, outputs: tool.outputPorts };
  }
  switch (kind) {
    case "text":
      return { inputs: [], outputs: [{ id: "text", label: "Text", dataType: "text" }] };
    case "image":
      return { inputs: [], outputs: [{ id: "image", label: "Image", dataType: "image" }] };
    case "video":
      return { inputs: [], outputs: [{ id: "video", label: "Video", dataType: "video" }] };
    case "audio":
      return { inputs: [], outputs: [{ id: "audio", label: "Audio", dataType: "audio" }] };
    case "storyboard":
      return {
        inputs: [
          { id: "image", label: "Shot", dataType: "image", targetField: "shot" },
          { id: "video", label: "Clip", dataType: "video", targetField: "clip" },
        ],
        outputs: [],
      };
    case "generator":
      return { inputs: [], outputs: [] };
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}

export function portDataTypeLabel(dataType: PortDataType): string {
  switch (dataType) {
    case "text":
      return "text";
    case "image":
      return "image";
    case "video":
      return "video";
    case "audio":
      return "audio";
    default: {
      const exhaustive: never = dataType;
      return exhaustive;
    }
  }
}
