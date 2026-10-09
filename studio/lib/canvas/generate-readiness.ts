import { fieldLabel } from "./field-labels";
import { toolById } from "./tool-registry";
import type { CanvasNodeData } from "./types";
import type { ToolSchema } from "@/lib/types";

const PROMPT_KEYS = ["prompt", "text", "script", "lyrics"] as const;

export function generateBlockers(
  data: CanvasNodeData,
  schema: ToolSchema | undefined,
  connectedFields: string[],
): string[] {
  const blockers: string[] = [];
  const required = new Set(schema?.inputSchema.required || []);
  const properties = schema?.inputSchema.properties || {};
  const tool = toolById(data.toolId);

  for (const key of PROMPT_KEYS) {
    if (connectedFields.includes(key)) {
      continue;
    }
    const listed = required.has(key) || Boolean(tool?.primaryFields.includes(key));
    if (!listed && !(data.kind === "text" && key === "prompt")) {
      continue;
    }
    const value = data.config[key];
    if (typeof value !== "string" || !value.trim()) {
      blockers.push(`Add a ${fieldLabel(key).toLowerCase()} first.`);
    }
  }

  if (
    properties.model &&
    !connectedFields.includes("model") &&
    (required.has("model") || tool?.primaryFields.includes("model"))
  ) {
    const value = data.config.model;
    if (value === undefined || value === null || value === "") {
      blockers.push("Choose a model first.");
    }
  }

  if (required.has("image_path_or_url") && !connectedFields.includes("image_path_or_url")) {
    const value = data.config.image_path_or_url;
    if (value === undefined || value === null || value === "") {
      blockers.push("Connect or add a reference image first.");
    }
  }

  for (const key of ["video_path_or_url", "video_duration_seconds", "video_url", "source_duration_seconds", "source_fps"]) {
    if (required.has(key) && !connectedFields.includes(key)) {
      const value = data.config[key];
      if (value === undefined || value === null || value === "") {
        blockers.push(`Add the ${fieldLabel(key).toLowerCase()} first.`);
      }
    }
  }
  if (data.providerId === "luma") {
    const hasSource = (field: string) => connectedFields.includes(field) || Boolean(data.config[field]);
    if (data.toolName === "image_to_video" && !hasSource("image_path_or_url") && !hasSource("last_frame_path_or_url")) {
      blockers.push("Connect or add a start or end image first.");
    }
    if (data.toolName === "modify_video") {
      if (Number(hasSource("video_path_or_url")) + Number(hasSource("source_generation_id")) !== 1) {
        blockers.push("Choose one source video or Luma generation.");
      }
      if (![5, 10].includes(Number(data.config.source_duration_seconds))) {
        blockers.push("Enter the measured source duration of 5 or 10 seconds.");
      }
    }
    if (data.toolName === "extend_video" && !hasSource("generation_id")) {
      blockers.push("Add the completed Luma generation ID first.");
    }
  }

  return [...new Set(blockers)];
}
