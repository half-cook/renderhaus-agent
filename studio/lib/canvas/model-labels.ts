const MODEL_LABELS: Record<string, string> = {
  "pixelcut/looping-video": "Studio Video · looping clip (named only)",
  "pixverse/music-video/vibemv": "Studio Music · music video (named only)",
  "gemini-3.8-flash": "Studio review model (experimental)",
  "ideogram/v4.5/edit": "Studio Image · text edit",
  "fal-ai/recraft/v4.1/pro/text-to-vector": "Studio Image · vector",
  "mirelo-ai/sfx1.6/video-to-video": "Studio Sound · video foley",
  "mureka-9.5": "Studio Music · Standard",
  "act_two": "Studio Video · performance transfer",
  "fal-ai/kling-video/v3/pro/motion-control": "Studio Video · motion control",
  "mureka/api/generate/lyrics-video": "Studio Music · lyrics video",
  "Starlight Precise 2.6": "Studio Finish · detail upscale",
  Apollo: "Studio Finish · frame interpolation",
  Chronos: "Studio Finish · slow motion",
  "slp-2.6": "Studio Finish · detail upscale",
  "apo-8": "Studio Finish · frame interpolation",
  "chr-2": "Studio Finish · slow motion",
  avatar_v: "Studio Avatar · presenter",
  "heygen-voice-1": "Studio Voice · instant clone (internal candidate)",
  "sync-3": "Studio Lip sync",
  "fal-ai/sync-lipsync/v3": "Studio Lip sync · alternate",
  "gpt-image-2.5-sunburst": "Studio Image · Standard",
  "gpt-image-2.5-sunburst-2026-09-08": "Studio Image · Standard (pinned release)",
  "kling-3.0": "Studio Video · Standard",
  "kling-3.0-turbo": "Studio Video · Fast",
  "kling-3.0-omni": "Studio Video · Reference",
  "fal-ai/wan-vace-14b": "Studio Video · edit (Standard)",
  "fal-ai/wan-22-vace-fun-a14b": "Studio Video · edit (Fast)",
  "alibaba/wan-3.0/text-to-video": "Studio Video · text to video",
  "alibaba/wan-3.0/image-to-video": "Studio Video · image to video",
  "alibaba/wan-3.0/reference-to-video": "Studio Video · reference to video",
  "wan3.0-video": "Studio Video · Standard (hosted)",
  "ray-3.2": "Studio Video · Cinematic",
  "seedream-5-0-lite-260128": "Studio Image · Fast",
  "seedance-1-5-pro-251215": "Studio Video · Standard (previous)",
  "dreamina-seedance-2-5-260628": "Studio Video · Pro",
  "bytedance/seedance-2.5/text-to-video": "Studio Video Pro · text to video",
  "bytedance/seedance-2.5/image-to-video": "Studio Video Pro · image to video",
  "bytedance/seedance-2.5/reference-to-video": "Studio Video Pro · reference, edit or extend",
  "bytedance/seedance-2.5/us/text-to-video": "Studio Video Pro · US text to video",
  "bytedance/seedance-2.5/us/image-to-video": "Studio Video Pro · US image to video",
  "bytedance/seedance-2.5/us/reference-to-video": "Studio Video Pro · US reference, edit or extend",
  "s2.1-pro-free": "Library voice · Pro (free tier)",
  "s2.1-pro": "Library voice · Pro",
  "s2-pro": "Library voice · Standard",
  s1: "Library voice · Basic",
  "gen4.5": "Studio Video · Cinematic Plus",
  aleph2: "Studio Video · edit (Cinematic)",
  gen4_image: "Studio Image · Cinematic",
  gen4_image_turbo: "Studio Image · Cinematic (Fast)",
  auto: "Auto",
};

const VERSION_SUFFIX = /-(\d{6,})$/;

// Unknown catalog ids still get a neutral label: the family is inferred from what the id does,
// never from who makes it. (Patterns are regexes, not rendered strings.)
const FAMILIES: Array<[RegExp, string]> = [
  [/(video|vace|gen4|aleph|ray|motion|animate|i2v|t2v|r2v)/i, "Studio Video"],
  [/(image|img|vector|edit|seedream)/i, "Studio Image"],
  [/(voice|speech|tts|fish|s\d)/i, "Library voice"],
  [/(music|song|lyrics)/i, "Studio Music"],
  [/(sfx|foley|sound)/i, "Studio Sound"],
  [/(upscale|interpol|starlight|apollo|chronos)/i, "Studio Finish"],
  [/(lip|sync|avatar)/i, "Studio Avatar"],
];
function humanizeId(value: string): string {
  const family = FAMILIES.find(([pattern]) => pattern.test(value))?.[1] ?? "Studio model";
  return family;
}

export function choiceLabel(field: string, value: string): string {
  if (field !== "model") {
    return value;
  }
  return MODEL_LABELS[value] || humanizeId(value);
}

// Live provider catalogs can contain distinct model ids that collapse to the
// same humanized label once their version-date suffix is stripped (e.g.
// two dated releases of one model both become the same family label).
// Compute labels for a whole field's choices at once so colliding ones can
// keep their suffix and stay visually distinguishable as separate pills.
export function choiceLabels(field: string, values: string[]): Map<string, string> {
  const labels = new Map(values.map((value) => [value, choiceLabel(field, value)]));
  const groups = new Map<string, string[]>();
  for (const [value, label] of labels) {
    groups.set(label, [...(groups.get(label) ?? []), value]);
  }
  for (const [label, members] of groups) {
    if (members.length < 2) continue;
    members.forEach((value, index) => {
      if (MODEL_LABELS[value]) return;
      const match = VERSION_SUFFIX.exec(value);
      labels.set(value, match ? `${label} (${match[1]})` : `${label} ${String.fromCharCode(65 + index)}`);
    });
  }
  return labels;
}
