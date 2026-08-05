import { create } from "zustand";
import type { Command } from "./commands";
import type { TimelineDocument } from "./types";

const initialDocument: TimelineDocument = {
  id: "project-1",
  name: "Untitled Project",
  assets: [],
  tracks: [
    { id: "video-1", kind: "video", name: "Video", items: [] },
    { id: "audio-1", kind: "audio", name: "Audio", items: [] },
    { id: "caption-1", kind: "caption", name: "Captions", items: [] },
  ],
};

interface TimelineState {
  document: TimelineDocument;
  /** Applied commands, most recent last. */
  past: Command[];
  /** Undone commands, most recently undone first. */
  future: Command[];
  runCommand: (command: Command) => void;
  undo: () => void;
  redo: () => void;

  // Playback transport state — deliberately NOT part of `document`/the
  // Command history. Scrubbing or playing isn't an edit, so it shouldn't be
  // undoable or show up in past/future.
  playheadSec: number;
  isPlaying: boolean;
  setPlayhead: (sec: number) => void;
  play: () => void;
  pause: () => void;
  togglePlay: () => void;
}

export const useTimelineStore = create<TimelineState>((set, get) => ({
  document: initialDocument,
  past: [],
  future: [],

  playheadSec: 0,
  isPlaying: false,
  setPlayhead: (sec) => set({ playheadSec: Math.max(0, sec) }),
  play: () => set({ isPlaying: true }),
  pause: () => set({ isPlaying: false }),
  togglePlay: () => set((state) => ({ isPlaying: !state.isPlaying })),

  runCommand: (command) => {
    set((state) => ({
      document: command.do(state.document),
      past: [...state.past, command],
      future: [],
    }));
  },

  undo: () => {
    const { past, document } = get();
    const command = past.at(-1);
    if (!command) return;
    set({
      document: command.undo(document),
      past: past.slice(0, -1),
      future: [command, ...get().future],
    });
  },

  redo: () => {
    const { future, document } = get();
    const [command, ...rest] = future;
    if (!command) return;
    set({
      document: command.do(document),
      past: [...get().past, command],
      future: rest,
    });
  },
}));
