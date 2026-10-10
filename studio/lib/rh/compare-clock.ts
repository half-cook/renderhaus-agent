import type { TimelineClip } from "./timeline";

export type CompareAlignment = "shot" | "time";
export type CompareClockClip = Pick<TimelineClip, "id" | "trimIn" | "trimOut">;
export type CompareFrame = {
  clipId: string;
  sourceSeconds: number;
  localSeconds: number;
  cutSeconds: number;
  held: boolean;
};

function frameAt(clip: CompareClockClip, localSeconds: number, startSeconds: number, fps: number): CompareFrame {
  const duration = Math.max(0, clip.trimOut - clip.trimIn);
  const lastFrame = Math.max(0, Math.ceil(duration * fps) - 1);
  const requestedFrame = Math.round(Math.max(0, localSeconds) * fps);
  const frame = Math.min(requestedFrame, lastFrame);
  const local = frame / fps;
  return {
    clipId: clip.id,
    sourceSeconds: clip.trimIn + local,
    localSeconds: local,
    cutSeconds: startSeconds + local,
    held: localSeconds < 0 || requestedFrame > lastFrame,
  };
}

function sampleCut(clips: readonly CompareClockClip[], seconds: number, fps: number): CompareFrame | null {
  let start = 0;
  for (const [index, clip] of clips.entries()) {
    const duration = Math.max(0, clip.trimOut - clip.trimIn);
    if (seconds < start + duration || index === clips.length - 1) return frameAt(clip, seconds - start, start, fps);
    start += duration;
  }
  return null;
}

export function compareFrames({ before, after, seconds, alignment, fps = 24 }: {
  before: readonly CompareClockClip[];
  after: readonly CompareClockClip[];
  seconds: number;
  alignment: CompareAlignment;
  fps?: number;
}): { before: CompareFrame | null; after: CompareFrame | null } {
  const beforeFrame = sampleCut(before, Math.max(0, seconds), fps);
  if (alignment === "time") return { before: beforeFrame, after: sampleCut(after, Math.max(0, seconds), fps) };
  if (!beforeFrame) return { before: null, after: null };
  let start = 0;
  for (const clip of after) {
    if (clip.id === beforeFrame.clipId) return { before: beforeFrame, after: frameAt(clip, beforeFrame.localSeconds, start, fps) };
    start += Math.max(0, clip.trimOut - clip.trimIn);
  }
  return { before: beforeFrame, after: null };
}

export function stepCompareFrame({ seconds, direction, durationSeconds, fps = 24 }: {
  seconds: number;
  direction: -1 | 1;
  durationSeconds: number;
  fps?: number;
}): number {
  const lastFrame = Math.max(0, Math.ceil(durationSeconds * fps) - 1);
  return Math.max(0, Math.min(lastFrame, Math.round(seconds * fps) + direction)) / fps;
}

export function compareTimecode(seconds: number, fps = 24): string {
  const frame = Math.round(Math.max(0, seconds) * fps);
  const minutes = Math.floor(frame / (fps * 60));
  const wholeSeconds = Math.floor(frame / fps) % 60;
  return [minutes, wholeSeconds, frame % fps].map((value) => String(value).padStart(2, "0")).join(":");
}
