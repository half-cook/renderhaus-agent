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

  return [...new Set(blockers)];
}
