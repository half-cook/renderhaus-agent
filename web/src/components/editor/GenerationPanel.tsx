"use client";

import { useGenerationStore } from "@/lib/generation/store";

// Renders whatever IconRail's active tab calls for, in the new panel slot
// between IconRail and the preview/timeline column (see EditorShell.tsx).
// Generate/Library/Production bodies land in later steps of the plan
// (inherited-wishing-flurry.md §6/§7) -- placeholders here just establish
// the slot. Captions/Text/Settings stay null, same stub status as before.
export function GenerationPanel() {
  const active = useGenerationStore((s) => s.activePanel);

  if (active === "captions" || active === "text" || active === "settings") return null;

  return (
    <div className="flex w-96 shrink-0 flex-col border-r border-neutral-800 p-4 text-sm text-neutral-500">
      {active === "generate" && "Generate panel coming soon."}
      {active === "library" && "Library panel coming soon."}
      {active === "production" && "Production panel coming soon."}
    </div>
  );
}
