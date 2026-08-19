"use client";

import {
  Hand,
  Image as ImageIcon,
  LayoutGrid,
  Mic,
  MousePointer2,
  Music,
  Sparkles,
  Type,
  Upload,
  Video,
} from "lucide-react";
import { useRef, type RefObject } from "react";
import { defaultToolForRail } from "@/lib/canvas/tool-registry";
import type { CreativeNodeKind, RailTool } from "@/lib/canvas/types";
import { useCanvasStore } from "@/lib/canvas/store";

type Props = {
  onPlace: (kind: CreativeNodeKind, toolId?: string) => void;
  onUpload: (file: File) => void;
};

type RailItem = { id: RailTool; label: string; icon: typeof Upload };

const GROUPS: Array<{ id: string; label: string; items: RailItem[] }> = [
  {
    id: "canvas",
    label: "Canvas",
    items: [
      { id: "select", label: "Select", icon: MousePointer2 },
      { id: "hand", label: "Pan", icon: Hand },
    ],
  },
  {
    id: "inputs",
    label: "Inputs",
    items: [
      { id: "upload", label: "Upload", icon: Upload },
      { id: "text", label: "Text", icon: Type },
    ],
  },
  {
    id: "generation",
    label: "Generation",
    items: [
      { id: "image", label: "Image", icon: ImageIcon },
      { id: "video", label: "Video", icon: Video },
    ],
  },
  {
    id: "audio",
    label: "Audio",
    items: [
      { id: "audio", label: "Music", icon: Music },
      { id: "voice", label: "Voiceover", icon: Mic },
    ],
  },
  {
    id: "workflow",
    label: "Workflow",
    items: [
      { id: "storyboard", label: "Storyboard", icon: LayoutGrid },
      { id: "agent", label: "Agent", icon: Sparkles },
    ],
  },
];

function handleRailAction(
  id: RailTool,
  onPlace: (kind: CreativeNodeKind, toolId?: string) => void,
  fileRef: RefObject<HTMLInputElement | null>,
): void {
  switch (id) {
    case "select":
    case "hand":
      return;
    case "upload":
      fileRef.current?.click();
      return;
    case "agent":
      document.getElementById("agent-composer")?.querySelector("textarea")?.focus();
      return;
    case "text":
      onPlace("text");
      return;
    case "storyboard":
      onPlace("storyboard");
      return;
    case "image":
    case "video":
    case "audio":
    case "voice": {
      const tool = defaultToolForRail(id);
      onPlace(tool?.category || "generator", tool?.id);
      return;
    }
    default: {
      const exhaustive: never = id;
      return exhaustive;
    }
  }
}

export function ToolRail({ onPlace, onUpload }: Props) {
  const activeTool = useCanvasStore((state) => state.activeTool);
  const setActiveTool = useCanvasStore((state) => state.setActiveTool);
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <nav className="tool-rail" aria-label="Creation tools">
      {GROUPS.map((group) => (
        <div className="rail-group" key={group.id} role="group" aria-label={group.label}>
          <p className="rail-group-label">{group.label}</p>
          {group.items.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                className={activeTool === item.id ? "rail-btn active" : "rail-btn"}
                title={item.label}
                aria-label={item.label}
                aria-pressed={activeTool === item.id}
                onClick={() => {
                  setActiveTool(item.id);
                  handleRailAction(item.id, onPlace, fileRef);
                }}
              >
                <Icon size={18} />
                <span className="rail-btn-label">{item.label}</span>
              </button>
            );
          })}
        </div>
      ))}
      <input
        ref={fileRef}
        type="file"
        hidden
        accept="image/*,video/*,audio/*"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) {
            onUpload(file);
          }
        }}
      />
    </nav>
  );
}
