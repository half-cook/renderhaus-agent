export const MODEL_LABELS: Record<string, string> = {
  "seedream-5-0-lite-260128": "Seedream 5 Lite",
  "seedance-1-5-pro-251215": "Seedance 1.5 Pro",
  "s2.1-pro-free": "Fish S2.1 Pro free",
  "s2.1-pro": "Fish S2.1 Pro",
  "s2-pro": "Fish S2 Pro",
  s1: "Fish S1",
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
