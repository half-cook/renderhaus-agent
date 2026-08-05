"use client";

import { Pause, Play } from "lucide-react";
import { formatTime } from "@/lib/timeline/format";
import { importVideoFiles, useFilePicker } from "@/lib/timeline/import";
import { getTimelineDuration } from "@/lib/timeline/query";
import { useTimelineStore } from "@/lib/timeline/store";
import { CanvasTimeline } from "./timeline/CanvasTimeline";
import { RULER_HEIGHT, TRACK_GAP, TRACK_HEIGHT } from "./timeline/constants";

export function TimelinePanel() {
  const document = useTimelineStore((s) => s.document);
  const playheadSec = useTimelineStore((s) => s.playheadSec);
  const isPlaying = useTimelineStore((s) => s.isPlaying);
  const setPlayhead = useTimelineStore((s) => s.setPlayhead);
  const togglePlay = useTimelineStore((s) => s.togglePlay);
  const { inputRef, open, onChange } = useFilePicker(importVideoFiles);

  const duration = getTimelineDuration(document);

  return (
    <div className="flex h-56 shrink-0 flex-col border-t border-neutral-800">
      <div className="flex items-center gap-3 border-b border-neutral-800 px-3 py-1.5">
        <button
          onClick={togglePlay}
          title={isPlaying ? "Pause (Space)" : "Play (Space)"}
          className="rounded p-1 text-neutral-300 hover:bg-neutral-800"
        >
          {isPlaying ? <Pause size={14} /> : <Play size={14} />}
        </button>
        <span className="text-xs tabular-nums text-neutral-500">
          {formatTime(playheadSec)} / {formatTime(duration)}
        </span>
        <div className="flex-1" />
        <button
          onClick={open}
          className="rounded-md bg-neutral-800 px-2.5 py-1 text-xs text-neutral-200 hover:bg-neutral-700"
        >
          + Import
        </button>
        <input ref={inputRef} type="file" accept="video/*" multiple hidden onChange={onChange} />
      </div>
      <div className="flex flex-1 overflow-auto">
        <div className="shrink-0 border-r border-neutral-800">
          {/* Spacer so track labels stay aligned with the track rows drawn
              below the time ruler inside CanvasTimeline's canvas. */}
          <div style={{ height: RULER_HEIGHT }} />
          {document.tracks.map((track) => (
            <div
              key={track.id}
              style={{ height: TRACK_HEIGHT + TRACK_GAP }}
              className="flex w-20 items-center px-2 text-xs text-neutral-500"
            >
              {track.name}
            </div>
          ))}
        </div>
        <div className="flex-1">
          <CanvasTimeline document={document} playheadSec={playheadSec} onSeek={setPlayhead} />
        </div>
      </div>
    </div>
  );
}
