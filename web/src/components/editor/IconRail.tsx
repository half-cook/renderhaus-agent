"use client";

import { Captions, Library, Settings, Sparkles, Type, Workflow } from "lucide-react";
import { useGenerationStore, type PanelKey } from "@/lib/generation/store";

// "Media"/"Transitions" (the original two stub tabs) are dropped here:
// Media's import affordance already lives inline in PreviewPanel/
// TimelinePanel (drag-drop, "+ Import"), and Transitions isn't built yet --
// neither needs a dedicated tab. Sparkles (previously Transitions' unused
// icon) moves to Generate.
const ITEMS: { key: PanelKey; label: string; icon: typeof Sparkles }[] = [
  { key: "generate", label: "Generate", icon: Sparkles },
  { key: "library", label: "Library", icon: Library },
  { key: "production", label: "Production", icon: Workflow },
  { key: "captions", label: "Captions", icon: Captions },
  { key: "text", label: "Text", icon: Type },
  { key: "settings", label: "Settings", icon: Settings },
];

// Active-tab state lives in the generation store (not local useState)
// so EditorShell can render panel content next to this rail -- see
// GenerationPanel.tsx and design/ARCHITECTURE.md §6's "chat/prompt panel sits
// alongside the timeline" framing.
export function IconRail() {
  const active = useGenerationStore((s) => s.activePanel);
  const setActive = useGenerationStore((s) => s.setActivePanel);

  return (
    <div className="flex w-16 shrink-0 flex-col items-center gap-1 border-r border-neutral-800 py-3">
      {ITEMS.map(({ key, label, icon: Icon }) => (
        <button
          key={key}
          onClick={() => setActive(key)}
          className={`flex w-14 flex-col items-center gap-1 rounded-md py-2 text-[11px] ${
            active === key
              ? "bg-neutral-800 text-neutral-100"
              : "text-neutral-500 hover:bg-neutral-900 hover:text-neutral-300"
          }`}
        >
          <Icon size={18} />
          {label}
        </button>
      ))}
    </div>
  );
}
