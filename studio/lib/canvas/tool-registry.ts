import type { AgentToolEvent, CreativeNodeKind, PortDataType, ToolDefinition } from "./types";

const CREATIVE_TOOLS: ToolDefinition[] = [
  {
    id: "runway.video.generate",
    displayName: "Runway video",
    category: "video",
    providerId: "runway",
    toolName: "text_to_video",
    inputPorts: [
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "ratio", "duration_seconds"],
    pollTool: "get_runway_task",
    pollIntervalMs: 5000,
    defaults: {"model": "gen4.5", "ratio": "1280:720", "duration_seconds": 5},
  },
  {
    id: "runway.video.fromImage",
    displayName: "Runway image to video",
    category: "video",
    providerId: "runway",
    toolName: "image_to_video",
    inputPorts: [
      { id: "image", label: "Image", dataType: "image", targetField: "image_path_or_url", required: true },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "ratio", "duration_seconds", "image_path_or_url"],
    pollTool: "get_runway_task",
    pollIntervalMs: 5000,
    defaults: {"model": "gen4.5", "ratio": "1280:720", "duration_seconds": 5},
  },
  {
    id: "runway.video.edit",
    displayName: "Runway Aleph edit",
    category: "video",
    providerId: "runway",
    toolName: "video_to_video",
    inputPorts: [
      { id: "video", label: "Video", dataType: "video", targetField: "video_path_or_url", required: true },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
      { id: "reference", label: "Guidance image", dataType: "image", targetField: "reference_image_path_or_url" },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "video_path_or_url", "video_duration_seconds", "reference_image_path_or_url", "reference_seconds"],
    pollTool: "get_runway_task",
    pollIntervalMs: 5000,
    defaults: {"model": "aleph2"},
  },
  {
    id: "runway.image.generate",
    displayName: "Runway image",
    category: "image",
    providerId: "runway",
    toolName: "text_to_image",
    inputPorts: [
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "image", label: "Image", dataType: "image" }],
    primaryFields: ["prompt", "model", "ratio"],
    pollTool: "get_runway_task",
    pollIntervalMs: 5000,
    defaults: {"model": "gen4_image", "ratio": "1280:720"},
  },
  {
    id: "runway.image.edit",
    displayName: "Runway reference image",
    category: "image",
    providerId: "runway",
    toolName: "image_to_image",
    inputPorts: [
      { id: "image", label: "Image", dataType: "image", targetField: "image_path_or_url", required: true },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "image", label: "Image", dataType: "image" }],
    primaryFields: ["prompt", "model", "ratio", "image_path_or_url"],
    pollTool: "get_runway_task",
    pollIntervalMs: 5000,
    defaults: {"model": "gen4_image", "ratio": "1280:720"},
  },
  {
    id: "video.falGenerate",
    displayName: "Wan VACE video",
    description: "Generate a Wan VACE clip from a prompt",
    category: "video",
    providerId: "fal",
    toolName: "text_to_video",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "num_frames", "frames_per_second", "resolution"],
    pollTool: "get_video_task",
  },
  {
    id: "video.luma.generate",
    displayName: "Luma video",
    description: "Generate a Ray 3.2 clip from a prompt",
    category: "video",
    providerId: "luma",
    toolName: "text_to_video",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "duration_seconds", "resolution"],
    pollTool: "get_video_task",
  },
  {
    id: "video.luma.fromImage",
    displayName: "Luma image to video",
    category: "video",
    providerId: "luma",
    toolName: "image_to_video",
    inputPorts: [
      { id: "image", label: "Start image", dataType: "image", targetField: "image_path_or_url" },
      { id: "endImage", label: "End image", dataType: "image", targetField: "last_frame_path_or_url" },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "resolution", "image_path_or_url", "last_frame_path_or_url"],
    pollTool: "get_video_task",
  },
  {
    id: "video.luma.modify",
    displayName: "Modify Luma video",
    category: "video",
    providerId: "luma",
    toolName: "modify_video",
    inputPorts: [
      { id: "video", label: "Source video", dataType: "video", targetField: "video_path_or_url" },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "video_path_or_url", "source_generation_id", "source_duration_seconds", "resolution", "strength"],
    pollTool: "get_video_task",
  },
  {
    id: "video.luma.extend",
    displayName: "Extend Luma video",
    category: "video",
    providerId: "luma",
    toolName: "extend_video",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "generation_id", "direction", "resolution"],
    pollTool: "get_video_task",
  },
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
    providerId: "elevenlabs",
    toolName: "music_compose",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "audio", label: "Audio", dataType: "audio" }],
    primaryFields: ["prompt", "model_id", "music_length_ms", "force_instrumental"],
  },
  {
    id: "voice.generate",
    displayName: "Voiceover",
    description: "Read text as speech",
    category: "audio",
    providerId: "elevenlabs",
    toolName: "text_to_speech_convert",
    inputPorts: [{ id: "text", label: "Script", dataType: "text", targetField: "text", required: true }],
    outputPorts: [{ id: "audio", label: "Audio", dataType: "audio" }],
    primaryFields: ["text", "voice_id", "model_id", "output_format"],
  },
];

export function toolById(id: string | undefined): ToolDefinition | undefined {
  if (!id) {
    return undefined;
  }
  return CREATIVE_TOOLS.find((tool) => tool.id === id);
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

export function toolForAgentArtifact(
  kind: "image" | "video" | "audio",
  event?: Pick<AgentToolEvent, "name" | "provider">,
): ToolDefinition | undefined {
  // Agent artifacts become self-contained text-to-media nodes. Even when the
  // agent used an input asset or a composition tool, placing the result must
  // not create an invisible dependency on another artifact in the run.
  const provider = `${event?.provider || ""} ${event?.name || ""}`.toLowerCase();
  const runway = provider.includes("runway");
  if (kind === "image") return toolById(runway ? "runway.image.generate" : "image.generate");
  if (kind === "video") {
    return toolById(
      runway ? "runway.video.generate"
        : provider.includes("luma") ? "video.luma.generate"
        : provider.includes("fal") ? "video.falGenerate"
        : "video.generate",
    );
  }
  const source = `${event?.provider || ""} ${event?.name || ""}`.toLowerCase();
  return toolById(
    source.includes("fish_audio") || source.includes("speech") || source.includes("voice")
      ? "voice.generate"
      : "music.generate",
  );
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
    case "agentResult":
      return { inputs: [], outputs: [{ id: "text", label: "Result", dataType: "text" }] };
    case "agentRun":
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
