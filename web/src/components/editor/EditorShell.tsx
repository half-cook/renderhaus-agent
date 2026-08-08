"use client";

import { useEffect } from "react";
import { useTimelineStore } from "@/lib/timeline/store";
import { GenerationPanel } from "./GenerationPanel";
import { IconRail } from "./IconRail";
import { PreviewPanel } from "./PreviewPanel";
import { TimelinePanel } from "./TimelinePanel";
import { TopBar } from "./TopBar";

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
}

export function EditorShell() {
  const undo = useTimelineStore((s) => s.undo);
  const redo = useTimelineStore((s) => s.redo);
  const togglePlay = useTimelineStore((s) => s.togglePlay);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const isModified = event.metaKey || event.ctrlKey;
      if (isModified && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
        return;
      }
      if (event.code === "Space" && !isTypingTarget(event.target)) {
        event.preventDefault();
        togglePlay();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [undo, redo, togglePlay]);

  return (
    <div className="flex h-screen flex-col bg-neutral-950 text-neutral-200">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <IconRail />
        <GenerationPanel />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <PreviewPanel />
          <TimelinePanel />
        </div>
      </div>
    </div>
  );
}
