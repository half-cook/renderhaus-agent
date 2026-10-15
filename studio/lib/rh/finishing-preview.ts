import type { StudioAsset } from "@/lib/types";

export type FinishingComparison = {
  before: StudioAsset;
  after: StudioAsset;
  duration: number;
  sourceStart: number;
  fullEstimateCents: number | null;
  sourceWidth: number;
  sourceHeight: number;
  outputWidth: number;
  outputHeight: number;
  sourceFps: number;
  outputFps: number;
  coversFullSource: boolean;
};

function number(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= minimum && value <= maximum;
}

function version(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,200}$/.test(value);
}

export function finishingComparison(args: Record<string, unknown>): FinishingComparison | null {
  const raw = args.comparison;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const data: Record<string, unknown> = Object.fromEntries(Object.entries(raw));
  const { before_version_id: before, after_version_id: after, duration_seconds: duration,
    source_start_seconds: sourceStart, full_estimated_cost_cents: fullEstimateCents,
    source_width: sourceWidth, source_height: sourceHeight, output_width: outputWidth,
    output_height: outputHeight, source_fps: sourceFps, output_fps: outputFps } = data;
  if (!version(before) || !version(after) || before === after || !number(duration, Number.MIN_VALUE, 3)
    || !number(sourceStart, 0, 300) || !number(sourceFps, Number.MIN_VALUE, 240)
    || !number(outputFps, Number.MIN_VALUE, 120) || duration * sourceFps < 1 - .0001 || duration * outputFps < 1 - .0001
    || !number(sourceWidth, 1, 16384) || !Number.isInteger(sourceWidth)
    || !number(sourceHeight, 1, 16384) || !Number.isInteger(sourceHeight)
    || !number(outputWidth, 1, 3840) || !Number.isInteger(outputWidth)
    || !number(outputHeight, 1, 3840) || !Number.isInteger(outputHeight)
    || (fullEstimateCents !== null && (!number(fullEstimateCents, 0, Number.MAX_SAFE_INTEGER)
      || !Number.isInteger(fullEstimateCents)))) return null;
  const asset = (id: string, filename: string): StudioAsset => ({
    assetId: id, versionId: id, kind: "video", filename, mimeType: "video/mp4",
  });
  return { before: asset(before, "Original preview.mp4"), after: asset(after, "Enhanced preview.mp4"),
    duration, sourceStart, fullEstimateCents, sourceWidth, sourceHeight, outputWidth, outputHeight,
    sourceFps, outputFps, coversFullSource: data.covers_full_source === true };
}
