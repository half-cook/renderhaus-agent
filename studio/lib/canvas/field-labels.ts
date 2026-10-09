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
  mask_path_or_url: "Edit mask",
  reference_image_urls: "Additional image references",
  quality: "Quality",
  background: "Background",
  moderation: "Moderation",
  output_compression: "Output compression",
  last_frame_path_or_url: "End image",
  source_generation_id: "Source generation",
  source_duration_seconds: "Source duration",
  generation_id: "Generation",
  direction: "Extend direction",
  strength: "Edit strength",
  seed: "Seed",
  ratio: "Output dimensions",
  video_path_or_url: "Source clip",
  video_duration_seconds: "Source duration in seconds",
  reference_image_path_or_url: "Guidance image",
  reference_seconds: "Guidance timestamp in seconds",
  reference_images: "Additional image references",
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

const PROMPT_FIELDS = new Set(["prompt", "text", "lyrics", "script", "style_prompt"]);

export function fieldLabel(name: string): string {
  return LABELS[name] || name.replaceAll("_", " ");
}

export function isPromptField(name: string): boolean {
  return PROMPT_FIELDS.has(name);
}
