export const MODEL_LABELS: Record<string, string> = {
  "seedream-5-0-lite-260128": "Seedream 5 Lite",
  "seedance-1-5-pro-251215": "Seedance 1.5 Pro",
  "s2.1-pro-free": "Fish S2.1 Pro free",
  "s2.1-pro": "Fish S2.1 Pro",
  "s2-pro": "Fish S2 Pro",
  s1: "Fish S1",
  auto: "Auto",
};

function humanizeId(value: string): string {
  const stripped = value.replace(/-\d{6,}$/, "").replaceAll("_", " ").replaceAll("-", " ");
  return stripped.replace(/\b\w/g, (char) => char.toUpperCase());
}

export function choiceLabel(field: string, value: string): string {
  if (field !== "model") {
    return value;
  }
  return MODEL_LABELS[value] || humanizeId(value);
}
