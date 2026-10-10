// Standing product rule (Satya, 2026-10-09): product UI, marketing, toasts and error text
// never show the platform fee and never name underlying providers or models.
// The only allowed mention is the FAQ line below.
export const ALLOWED_FEE_LINE = "Every price you see includes a small platform fee.";

const FEE = /\b30\s?%|\b(platform|service|processing|handling)\s+fee\b|\b\d{1,3}\s?%\s*(platform\s+)?(fee|markup|margin|commission)\b|\bfee\s*[:(]?\s*\d{1,3}\s?%|\b(markup|margin)\b/i;
const MACHINE = /\b[a-z][a-z0-9_-]*___[a-z0-9_]+\b/i;
const VENDORS = /\b(wan\s?\d*(\.\d+)?|gpt[\s-]?(image|\d[\w.-]*)?|chatgpt|openai|eleven\s?labs|seedance|seedream|bytedance|byteplus|sonnet|opus|haiku|claude|anthropic|remotion|fal(\.ai)?|kling|runway|luma|vidu|veo|heygen|topaz|mureka|mirelo|ideogram|recraft|gemini|hyperframes|runpod|dashscope|alibaba|fish\s?audio|pixverse|pixelcut|sync\s?labs|flux|midjourney)\b/i;

/** Returns the offending snippets found in a block of user-visible text. */
export function findCopyLeaks(text) {
  const cleaned = String(text).split(ALLOWED_FEE_LINE).join(" ");
  const leaks = [];
  for (const [kind, pattern] of [["fee", FEE], ["vendor", VENDORS], ["tool_id", MACHINE]]) {
    const re = new RegExp(pattern.source, "gi");
    for (const match of cleaned.matchAll(re)) {
      const start = Math.max(0, match.index - 24);
      leaks.push({ kind, match: match[0], context: cleaned.slice(start, match.index + match[0].length + 24).replace(/\s+/g, " ").trim() });
    }
  }
  return leaks;
}
