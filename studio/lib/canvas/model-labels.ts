const MODEL_LABELS: Record<string, string> = {
  "mirelo-ai/sfx1.6/video-to-video": "Mirelo SFX 1.6 video foley",
  "mureka-9.5": "Mureka V9.5",
  "act_two": "Runway Act-Two",
  "fal-ai/kling-video/v3/pro/motion-control": "Kling 3 Pro Motion Control",
  "mureka/api/generate/lyrics-video": "Mureka lyrics video",
  "Starlight Precise 2.6": "Topaz Starlight Precise 2.6",
  Apollo: "Topaz Apollo",
  Chronos: "Topaz Chronos",
  "slp-2.6": "Topaz Starlight Precise 2.6",
  "apo-8": "Topaz Apollo",
  "chr-2": "Topaz Chronos",
  avatar_v: "HeyGen Avatar V",
  "sync-3": "sync-3 lip sync",
  "fal-ai/sync-lipsync/v3": "sync-3 lip sync (fal)",
  "gpt-image-2.5-sunburst": "GPT Image 2.5 Sunburst",
  "gpt-image-2.5-sunburst-2026-09-08": "GPT Image 2.5 Sunburst (2026-09-08)",
  "kling-3.0": "Kling 3.0",
  "kling-3.0-turbo": "Kling 3.0 Turbo",
  "kling-3.0-omni": "Kling 3.0 Omni",
  "fal-ai/wan-vace-14b": "Wan 2.1 VACE 14B",
  "fal-ai/wan-22-vace-fun-a14b": "Wan 2.2 VACE Fun A14B",
  "alibaba/wan-3.0/text-to-video": "Wan 3.0 text to video",
  "alibaba/wan-3.0/image-to-video": "Wan 3.0 image to video",
  "alibaba/wan-3.0/reference-to-video": "Wan 3.0 reference to video",
  "wan3.0-video": "Wan 3.0 Model Studio",
  "ray-3.2": "Luma Ray 3.2",
  "seedream-5-0-lite-260128": "Seedream 5 Lite",
  "seedance-1-5-pro-251215": "Seedance 1.5 Pro",
  "dreamina-seedance-2-5-260628": "Seedance 2.5",
  "bytedance/seedance-2.5/text-to-video": "Seedance 2.5 text to video",
  "bytedance/seedance-2.5/image-to-video": "Seedance 2.5 image to video",
  "bytedance/seedance-2.5/reference-to-video": "Seedance 2.5 reference, edit or extend",
  "bytedance/seedance-2.5/us/text-to-video": "Seedance 2.5 US text to video",
  "bytedance/seedance-2.5/us/image-to-video": "Seedance 2.5 US image to video",
  "bytedance/seedance-2.5/us/reference-to-video": "Seedance 2.5 US reference, edit or extend",
  "s2.1-pro-free": "Fish S2.1 Pro free",
  "s2.1-pro": "Fish S2.1 Pro",
  "s2-pro": "Fish S2 Pro",
  s1: "Fish S1",
  "gen4.5": "Runway Gen-4.5",
  aleph2: "Runway Aleph 2.0",
  gen4_image: "Runway Gen-4 Image",
  gen4_image_turbo: "Runway Gen-4 Image Turbo",
  auto: "Auto",
};

const VERSION_SUFFIX = /-(\d{6,})$/;

function humanizeId(value: string): string {
  const stripped = value.replace(VERSION_SUFFIX, "").replaceAll("_", " ").replaceAll("-", " ");
  return stripped.replace(/\b\w/g, (char) => char.toUpperCase());
}

export function choiceLabel(field: string, value: string): string {
  if (field !== "model") {
    return value;
  }
  return MODEL_LABELS[value] || humanizeId(value);
}

// Live provider catalogs can contain distinct model ids that collapse to the
// same humanized label once their version-date suffix is stripped (e.g.
// seedream-4-0-250828 and seedream-4-0-20260415 both become "Seedream 4 0").
// Compute labels for a whole field's choices at once so colliding ones can
// keep their suffix and stay visually distinguishable as separate pills.
export function choiceLabels(field: string, values: string[]): Map<string, string> {
  const labels = new Map(values.map((value) => [value, choiceLabel(field, value)]));
  const counts = new Map<string, number>();
  for (const label of labels.values()) {
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  for (const [value, label] of labels) {
    if ((counts.get(label) ?? 0) > 1 && !MODEL_LABELS[value]) {
      const match = VERSION_SUFFIX.exec(value);
      if (match) {
        labels.set(value, `${label} (${match[1]})`);
      }
    }
  }
  return labels;
}
