"use client";

import { Captions, Film, Settings, Sparkles, Type } from "lucide-react";
import { useState } from "react";

const ITEMS = [
  { key: "media", label: "Media", icon: Film },
  { key: "captions", label: "Captions", icon: Captions },
  { key: "text", label: "Text", icon: Type },
  { key: "transitions", label: "Transitions", icon: Sparkles },
  { key: "settings", label: "Settings", icon: Settings },
] as const;

// Stub tonight — no panel content behind these yet, just the shell (§13.2
// step 1). Import (behind "Media") is tomorrow's step 4.
export function IconRail() {
  const [active, setActive] = useState<(typeof ITEMS)[number]["key"]>("media");

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
