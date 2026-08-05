export interface Clip {
  id: string;
  track: number;
  start: number; // seconds
  duration: number; // seconds
  color: string;
  label: string;
}

export interface TimelineData {
  clips: Clip[];
  duration: number; // seconds, full timeline length
  trackCount: number;
}

export interface RendererProps {
  data: TimelineData;
  autoScrub: boolean;
  onFps: (fps: number) => void;
  onDrawCalls: (n: number) => void;
}
