"use client";

import {
  Hand,
  Image as ImageIcon,
  LayoutGrid,
  Mic,
  MousePointer2,
  Move,
  Music,
  PanelBottom,
  PanelLeft,
  PanelRight,
  PanelTop,
  Sparkles,
  Type,
  Upload,
  Video,
} from "lucide-react";
import { useEffect, useRef, useState, type RefObject } from "react";
import { defaultToolForRail } from "@/lib/canvas/tool-registry";
import type { CreativeNodeKind, DockPosition, RailTool } from "@/lib/canvas/types";
import { useCanvasStore } from "@/lib/canvas/store";

type Props = {
  dock: DockPosition;
  freeX: number;
  freeY: number;
  onDockChange: (dock: DockPosition) => void;
  onFreeMove: (x: number, y: number) => void;
  onPlace: (kind: CreativeNodeKind, toolId?: string) => void;
  onUpload: (file: File) => void;
};

const DRAG_THRESHOLD_PX = 4;
const EDGE_SNAP_PX = 48;

const DOCK_OPTIONS: Array<{ id: DockPosition; label: string; icon: typeof PanelTop }> = [
  { id: "top", label: "Dock to top", icon: PanelTop },
  { id: "bottom", label: "Dock to bottom", icon: PanelBottom },
  { id: "left", label: "Dock to left", icon: PanelLeft },
  { id: "right", label: "Dock to right", icon: PanelRight },
];

type RailItem = { id: RailTool; label: string; icon: typeof Upload; shortcut?: string };

const GROUPS: Array<{ id: string; label: string; items: RailItem[] }> = [
  {
    id: "canvas",
    label: "Canvas",
    items: [
      { id: "select", label: "Select", icon: MousePointer2, shortcut: "V" },
      { id: "hand", label: "Pan", icon: Hand, shortcut: "H" },
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

export function ToolRail({ dock, freeX, freeY, onDockChange, onFreeMove, onPlace, onUpload }: Props) {
  const activeTool = useCanvasStore((state) => state.activeTool);
  const setActiveTool = useCanvasStore((state) => state.setActiveTool);
  const fileRef = useRef<HTMLInputElement>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const railRef = useRef<HTMLElement>(null);
  const [dragPos, setDragPos] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (!pickerOpen) {
      return;
    }
    const onPointerDown = (event: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        setPickerOpen(false);
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [pickerOpen]);

  const startDrag = (downEvent: React.PointerEvent<HTMLButtonElement>) => {
    const rail = railRef.current;
    const workspaceEl = rail?.closest(".workspace");
    if (!rail || !workspaceEl) {
      return;
    }
    const railStart = rail.getBoundingClientRect();
    const workspaceStart = workspaceEl.getBoundingClientRect();
    const originLeft = railStart.left - workspaceStart.left;
    const originTop = railStart.top - workspaceStart.top;
    const startX = downEvent.clientX;
    const startY = downEvent.clientY;
    // Keep free placement confined to the actual canvas -- not draggable
    // on top of .scene-rail, .inspector, or under the header -- by
    // clamping to the same --safe-* values the canvas itself is inset by,
    // rather than the raw 0..workspace-width/height bounds.
    const workspaceStyle = getComputedStyle(workspaceEl);
    const safeLeft = Number.parseFloat(workspaceStyle.getPropertyValue("--safe-left")) || 0;
    const safeRight = Number.parseFloat(workspaceStyle.getPropertyValue("--safe-right")) || 0;
    const safeTop = Number.parseFloat(workspaceStyle.getPropertyValue("--safe-top")) || 0;
    const minLeft = safeLeft;
    const minTop = safeTop;
    const maxLeft = Math.max(workspaceStart.width - safeRight - railStart.width, minLeft);
    const maxTop = Math.max(workspaceStart.height - railStart.height, minTop);
    let dragging = false;
    // Plain closure vars, not React state -- read synchronously in onUp
    // with no risk of a stale-state or DOM-remeasurement race.
    let liveLeft = originLeft;
    let liveTop = originTop;

    const onMove = (moveEvent: PointerEvent) => {
      const dx = moveEvent.clientX - startX;
      const dy = moveEvent.clientY - startY;
      if (!dragging) {
        if (Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) {
          return;
        }
        dragging = true;
        setPickerOpen(false);
      }
      liveLeft = Math.min(Math.max(originLeft + dx, minLeft), maxLeft);
      liveTop = Math.min(Math.max(originTop + dy, minTop), maxTop);
      setDragPos({ x: liveLeft, y: liveTop });
    };

    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      if (!dragging) {
        // A plain click, not a drag -- toggle the dock-position popover.
        setPickerOpen((open) => !open);
        return;
      }
      setDragPos(null);
      // Measured from the clamped bounds, not the raw workspace edges --
      // liveLeft/liveTop can never actually reach 0 once clamped away
      // from the sidebars, so "distance to the edge" has to mean
      // "distance to as far as it's allowed to go" for the snap to ever
      // trigger from a drag.
      const distances: Array<[DockPosition, number]> = [
        ["left", liveLeft - minLeft],
        ["right", maxLeft - liveLeft],
        ["top", liveTop - minTop],
        ["bottom", maxTop - liveTop],
      ];
      const [closest, closestDistance] = distances.reduce((min, next) => (next[1] < min[1] ? next : min));
      if (closestDistance < EDGE_SNAP_PX) {
        onDockChange(closest);
      } else {
        onFreeMove(liveLeft, liveTop);
      }
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  // Neutralize whichever positioning properties the current [data-dock]
  // CSS rule set (right/bottom/margin/transform) so a literal left/top
  // wins outright, whether that's a live drag position (any starting
  // dock) or the committed "free" resting position.
  const pos = dragPos ?? (dock === "free" ? { x: freeX, y: freeY } : null);
  const freeStyle = pos
    ? { left: pos.x, top: pos.y, right: "auto", bottom: "auto", margin: 0, transform: "none" }
    : undefined;

  return (
    <nav className="tool-rail" data-dock={dock} style={freeStyle} ref={railRef} aria-label="Creation tools">
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
                aria-label={item.label}
                aria-pressed={activeTool === item.id}
                onClick={() => {
                  setActiveTool(item.id);
                  handleRailAction(item.id, onPlace, fileRef);
                }}
              >
                <Icon size={18} />
                <span className="rail-btn-label">
                  {item.label}
                  {item.shortcut ? <kbd className="rail-btn-shortcut">{item.shortcut}</kbd> : null}
                </span>
              </button>
            );
          })}
        </div>
      ))}
      <div className="rail-group" ref={wrapRef}>
        <button
          type="button"
          className="rail-btn rail-drag-handle"
          aria-label="Move tool bar"
          aria-expanded={pickerOpen}
          onPointerDown={startDrag}
        >
          <Move size={18} />
          <span className="rail-btn-label">Drag to move, click for options</span>
        </button>
        {pickerOpen ? (
          <div className="dock-picker" role="menu" aria-label="Tool bar position">
            {DOCK_OPTIONS.map((option) => {
              const Icon = option.icon;
              return (
                <button
                  key={option.id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={dock === option.id}
                  className={dock === option.id ? "dock-picker-btn active" : "dock-picker-btn"}
                  title={option.label}
                  onClick={() => {
                    onDockChange(option.id);
                    setPickerOpen(false);
                  }}
                >
                  <Icon size={16} />
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
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
