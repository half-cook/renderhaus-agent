import type { Clip, TimelineData } from './types';

const COLORS = [
  '#6C8EF5', '#F5A26C', '#6CF5A2', '#F56C8E',
  '#A26CF5', '#F5E36C', '#6CD9F5', '#F5876C',
];

// Deterministic PRNG so clip count changes are reproducible across renderer switches.
function mulberry32(seed: number) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function generateTimeline(clipCount: number, trackCount: number): TimelineData {
  const rand = mulberry32(clipCount * 7919 + trackCount);
  const clips: Clip[] = [];
  const cursors = new Array(trackCount).fill(0);

  for (let i = 0; i < clipCount; i++) {
    const track = i % trackCount;
    const gap = 0.1 + rand() * 0.6;
    const duration = 0.8 + rand() * 3.5;
    const start = cursors[track] + gap;
    clips.push({
      id: `clip-${i}`,
      track,
      start,
      duration,
      color: COLORS[i % COLORS.length],
      label: `Clip ${i}`,
    });
    cursors[track] = start + duration;
  }

  const duration = Math.max(...cursors, 60);
  return { clips, duration, trackCount };
}
