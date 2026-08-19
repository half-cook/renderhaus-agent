const LABELS: Record<string, string> = {
  prompt: "Prompt",
  text: "Script",
  lyrics: "Lyrics",
  script: "Script",
  style_prompt: "Delivery",
  aspect_ratio: "Aspect ratio",
  duration_seconds: "Duration",
  resolution: "Resolution",
  size: "Size",
  model: "Model",
  watermark: "Watermark",
  generate_audio: "Generate audio",
  service_tier: "Speed",
  response_format: "Response",
  voice: "Voice",
  output_format: "Format",
  gender: "Vocal",
  n: "Variations",
  image_path_or_url: "Reference",
  seed: "Seed",
};

export const PRIMARY_FIELD_ORDER = [
  "model",
  "prompt",
  "text",
  "lyrics",
  "script",
  "image_path_or_url",
  "aspect_ratio",
  "duration_seconds",
  "resolution",
  "size",
  "voice",
  "seed",
];

export const PROMPT_FIELDS = new Set(["prompt", "text", "lyrics", "script", "style_prompt"]);

export function fieldLabel(name: string): string {
  return LABELS[name] || name.replaceAll("_", " ");
}

export function isPromptField(name: string): boolean {
  return PROMPT_FIELDS.has(name);
}
