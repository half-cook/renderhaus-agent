"use client";

import { Redo2, Undo2 } from "lucide-react";
import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";
import { useTimelineStore } from "@/lib/timeline/store";

export function TopBar() {
  // @clerk/nextjs 7.x has no SignedIn/SignedOut components (replaced by
  // <Show>, an unfamiliar API) -- plain useAuth() + conditional matches this
  // file's existing style better than reaching for a wrapper component.
  const { isLoaded, isSignedIn } = useAuth();
  const projectName = useTimelineStore((s) => s.document.name);
  const canUndo = useTimelineStore((s) => s.past.length > 0);
  const canRedo = useTimelineStore((s) => s.future.length > 0);
  const undo = useTimelineStore((s) => s.undo);
  const redo = useTimelineStore((s) => s.redo);

  return (
    <div className="flex h-12 shrink-0 items-center gap-3 border-b border-neutral-800 px-4">
      <span className="font-semibold tracking-tight">Renderhaus</span>
      <span className="text-neutral-700">/</span>
      <span className="text-sm text-neutral-300">{projectName}</span>

      <div className="ml-3 flex items-center gap-1">
        <button
          onClick={undo}
          disabled={!canUndo}
          title="Undo (Cmd+Z)"
          className="rounded p-1.5 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100 disabled:opacity-30 disabled:hover:bg-transparent"
        >
          <Undo2 size={16} />
        </button>
        <button
          onClick={redo}
          disabled={!canRedo}
          title="Redo (Cmd+Shift+Z)"
          className="rounded p-1.5 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100 disabled:opacity-30 disabled:hover:bg-transparent"
        >
          <Redo2 size={16} />
        </button>
      </div>

      <div className="flex-1" />

      {isLoaded && (isSignedIn ? (
        <UserButton />
      ) : (
        <SignInButton mode="modal">
          <button className="rounded-md px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800 hover:text-neutral-100">
            Sign in
          </button>
        </SignInButton>
      ))}

      <button
        disabled
        title="Not built yet"
        className="rounded-md bg-neutral-800 px-3 py-1.5 text-sm text-neutral-500"
      >
        Export
      </button>
    </div>
  );
}
