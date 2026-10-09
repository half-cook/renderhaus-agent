import type { StudioExecution } from "@/lib/api";
import type { StudioAsset } from "@/lib/types";
import type { CanvasNode } from "./connection-validation";
import type { AgentToolEvent } from "./types";
import { approvedSequence } from "./story";

export type ReviewFile = {
  asset: StudioAsset;
  origin: "Uploaded" | "Generated";
  currentTask: boolean;
  nodeId?: string;
  title?: string;
};

export type ReviewLine = { id: string; text: string };
export type DiffLine = ReviewLine & {
  change: "added" | "removed" | "context";
  before?: number;
  after?: number;
};

export type TimelineSegment = {
  id: string;
  identity: string;
  kind: "video" | "image" | "audio" | "text";
  track: string;
  ordinal: number;
  start?: number;
  end?: number;
  duration?: number;
  sourceStart?: number;
  asset?: StudioAsset;
  /** Display filename; transport identity is kept separately for comparisons. */
  source: string;
  sourceKey: string;
  label: string;
  properties: Record<string, string>;
};

export type TimelineDiffRow = {
  id: string;
  change: "added" | "removed" | "context";
  segment: TimelineSegment;
  before?: TimelineSegment;
  after?: TimelineSegment;
  changedFields: string[];
};

export function reviewFiles(nodes: CanvasNode[], executions: StudioExecution[]): ReviewFile[] {
  const files = new Map<string, ReviewFile>();
  for (const node of nodes) {
    const { output, variants = [], toolId, agentRunId, title } = node.data;
    for (const asset of [...variants, ...(output ? [output] : [])]) {
      files.set(asset.versionId, {
        asset, nodeId: node.id, title,
        origin: toolId || agentRunId ? "Generated" : "Uploaded",
        currentTask: false,
      });
    }
  }
  for (const execution of executions) {
    const assets = [...execution.assets, ...execution.toolEvents.flatMap((event) => event.assets)];
    if (execution.primaryAsset) assets.push(execution.primaryAsset);
    for (const asset of assets) {
      const existing = files.get(asset.versionId);
      files.set(asset.versionId, { ...existing, asset, origin: "Generated", currentTask: true });
    }
  }
  return [...files.values()].sort((a, b) => Number(b.currentTask) - Number(a.currentTask));
}

/** No baseline means context, not a claim that existing content was just added. */
export function diffReviewLines(before: ReviewLine[] | undefined, after: ReviewLine[]): DiffLine[] {
  if (!before) return after.map((line, index) => ({ ...line, change: "context", after: index + 1 }));
  const old = new Map(before.map((line, index) => [line.id, { ...line, number: index + 1 }]));
  const nextIds = new Set(after.map((line) => line.id));
  const result: DiffLine[] = before.flatMap((line, index) => nextIds.has(line.id)
    ? [] : [{ ...line, change: "removed" as const, before: index + 1 }]);
  after.forEach((line, index) => {
    const previous = old.get(line.id);
    if (previous?.text === line.text) {
      result.push({ ...line, change: "context", before: previous.number, after: index + 1 });
    } else {
      if (previous) result.push({ id: line.id, text: previous.text, change: "removed", before: previous.number });
      result.push({ ...line, change: "added", after: index + 1 });
    }
  });
  return result;
}

export function sequenceReviewLines(nodes: CanvasNode[]): ReviewLine[] {
  return approvedSequence(nodes).map((node, index) => {
    const duration = node.data.config.duration_seconds;
    const durationText = typeof duration === "number" && Number.isFinite(duration)
      ? `${duration}s` : node.data.kind === "image" ? "still" : "duration unset";
    return {
      id: node.id,
      text: `${String(index + 1).padStart(2, "0")}  ${node.data.title}  ·  ${durationText}  ·  ${node.data.output?.filename || "No media"}  ·  ${node.data.output ? `version ${node.data.output.versionId.slice(0, 8)}` : "unrendered"}`,
    };
  });
}

function rows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> =>
    Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function sourceName(value: unknown, assets: StudioAsset[]): string {
  if (typeof value !== "string") return "Source unspecified";
  const version = value.startsWith("renderhaus-asset://") ? value.slice("renderhaus-asset://".length) : undefined;
  if (version) {
    const asset = assets.find((candidate) => candidate.versionId === version);
    return `${asset?.filename || "Media"} [${version.slice(0, 8)}]`;
  }
  // External source queries can contain credentials. Only a filename belongs in the review UI.
  try { return new URL(value).pathname.split("/").filter(Boolean).at(-1) || "External media"; }
  catch { return "External media"; }
}

function finite(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function nonnegative(value: unknown, fallback?: number): number | undefined {
  if (value === undefined || value === null) return fallback;
  const number = finite(value);
  return number !== undefined && number >= 0 ? number : undefined;
}

function safeSource(value: unknown): string {
  if (typeof value !== "string") return "";
  if (value.startsWith("renderhaus-asset://")) return value.split(/[?#]/, 1)[0];
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? `${url.origin}${url.pathname}` : "";
  } catch { return ""; }
}

/** Normalizes only documented render defaults; invalid/missing required timing stays unknown. */
export function timelineSegments(args: Record<string, unknown>, assets: StudioAsset[]): TimelineSegment[] {
  const result: TimelineSegment[] = [];
  const occurrences = new Map<string, number>();
  const trackEnds = new Map<string, number | undefined>();
  let visualEnd: number | undefined = 0;
  for (const field of ["visuals", "audio_tracks", "text_overlays", "subtitles"] as const) {
    rows(args[field]).forEach((clip, index) => {
      const kind = field === "text_overlays" || field === "subtitles" ? "text" : field === "audio_tracks" ? "audio" : clip.kind === "video" ? "video" : "image";
      const track = field === "visuals" ? `V${Math.max(0, Math.min(Math.trunc(finite(clip.track) ?? 0), 8)) + 1}` : field === "audio_tracks" ? `A${index + 1}` : field === "subtitles" ? "S1" : "T1";
      const sourceKey = safeSource(clip.url);
      const source = kind === "text" ? "" : sourceName(sourceKey, assets);
      const versionId = sourceKey.startsWith("renderhaus-asset://") ? sourceKey.slice("renderhaus-asset://".length) : undefined;
      const asset = versionId ? assets.find((candidate) => candidate.versionId === versionId) : undefined;
      const label = kind === "text" ? String(clip.text || "Untitled text").trim().slice(0, 500) : asset?.filename || source;
      const stableId = typeof clip.id === "string" ? clip.id : typeof clip.clip_id === "string" ? clip.clip_id : undefined;
      const identity = stableId ? `clip:${stableId}` : `${kind}:${asset?.assetId || sourceKey || (kind === "text" ? label : "unknown")}`;
      const occurrence = (occurrences.get(identity) || 0) + 1;
      occurrences.set(identity, occurrence);
      let duration = nonnegative(clip.duration_seconds);
      if (duration === 0) duration = undefined;
      const requestedDuration = duration;
      const defaultStart = field === "visuals" ? trackEnds.has(track) ? trackEnds.get(track) : 0 : 0;
      const start = nonnegative(clip.start_seconds, defaultStart);
      // The renderer trims audio/titles to the visual sequence, never extends the movie for them.
      if (field !== "visuals" && visualEnd !== undefined && start !== undefined && duration !== undefined) {
        duration = Math.max(0, Math.min(duration, visualEnd - start));
      }
      const end = start !== undefined && duration !== undefined ? start + duration : undefined;
      if (field === "visuals") {
        const previousEnd = trackEnds.has(track) ? trackEnds.get(track) : 0;
        trackEnds.set(track, end !== undefined && previousEnd !== undefined ? Math.max(previousEnd, end) : undefined);
        visualEnd = visualEnd !== undefined && end !== undefined ? Math.max(visualEnd, end) : undefined;
      }
      const sourceStart = kind === "text" ? undefined : nonnegative(clip.source_in_seconds, 0);
      const properties: Record<string, string> = {};
      const numberProperty = (key: string, fallback: number | undefined, min: number, max: number, zeroUsesDefault = false) => {
        const value = clip[key] === undefined || clip[key] === null || (zeroUsesDefault && clip[key] === 0) ? fallback : finite(clip[key]);
        properties[key] = value === undefined ? "Unknown" : String(Math.max(min, Math.min(value, max)));
      };
      const textProperty = (key: string, fallback: string) => {
        properties[key] = typeof clip[key] === "string" && clip[key] ? clip[key] : fallback;
      };
      if (kind !== "text") {
        properties.source_in_seconds = sourceStart === undefined ? "Unknown" : String(sourceStart);
        numberProperty("volume", 1, kind === "audio" ? -Infinity : 0, kind === "audio" ? Infinity : 1);
      }
      if (field === "visuals") {
        numberProperty("playback_rate", 1, 0.25, 4);
        numberProperty("scale", 1, 0.1, 4);
        numberProperty("opacity", 1, 0, 1);
        numberProperty("position_x", 0.5, 0, 1);
        numberProperty("position_y", 0.5, 0, 1);
        numberProperty("rotation_degrees", 0, -360, 360);
        textProperty("transition", "cut");
        textProperty("fit", "cover");
        textProperty("motion", "none");
        textProperty("grade", "none");
      }
      if (kind === "text") {
        textProperty("position", "center");
        textProperty("color", "#ffffff");
        textProperty("background_color", "transparent");
        numberProperty("font_size", 64, 16, 180, true);
        numberProperty("font_weight", 700, 100, 900, true);
        for (const key of ["font_size", "font_weight"]) {
          if (properties[key] !== "Unknown") properties[key] = String(Math.trunc(Number(properties[key])));
        }
        properties.color = properties.color.slice(0, 32);
        properties.background_color = properties.background_color.slice(0, 32);
      }
      const visualFade = properties.transition && properties.transition !== "cut" ? duration !== undefined ? Math.min(0.35, duration / 3) : undefined : 0;
      // Text fades are normalized before the renderer clips the visible title at the movie end.
      const fadeLimit = kind === "text" ? requestedDuration : duration;
      numberProperty("fade_in_seconds", field === "subtitles" ? 0 : kind === "text" ? 0.2 : field === "visuals" ? visualFade : 0, 0, fadeLimit ?? Infinity, field === "text_overlays");
      numberProperty("fade_out_seconds", field === "subtitles" ? 0 : kind === "text" ? 0.2 : field === "visuals" ? visualFade : 0.75, 0, fadeLimit ?? Infinity, field === "text_overlays");
      if (field === "visuals") {
        numberProperty("audio_fade_in_seconds", properties.fade_in_seconds === "Unknown" ? undefined : Number(properties.fade_in_seconds), 0, duration ?? Infinity);
        numberProperty("audio_fade_out_seconds", properties.fade_out_seconds === "Unknown" ? undefined : Number(properties.fade_out_seconds), 0, duration ?? Infinity);
      }
      result.push({ id: `${identity}:${occurrence}`, identity, kind, track, ordinal: result.length + 1, start, end, duration, sourceStart, asset, source, sourceKey, label, properties });
    });
  }
  return result;
}

function segmentChanges(before: TimelineSegment, after: TimelineSegment, ripple = 0): string[] {
  // Audio track numbers are assigned by array position by the renderer, not editable track identities.
  const changed = (["kind", "track", "source", "label", "duration"] as const).filter((key) => {
    if (key === "track" && before.kind === "audio" && after.kind === "audio") return false;
    if (key === "label" && before.kind !== "text" && after.kind !== "text") return false;
    return key === "source" ? before.sourceKey !== after.sourceKey : before[key] !== after[key];
  }) as string[];
  if (before.start !== after.start && !(before.start !== undefined && after.start !== undefined && Math.abs(after.start - before.start - ripple) < 0.000001)) changed.push("start");
  for (const key of new Set([...Object.keys(before.properties), ...Object.keys(after.properties)])) {
    if (before.properties[key] !== after.properties[key]) changed.push(key);
  }
  return changed;
}

/** Align source identities, not array positions. Repeated uses remain separate occurrences. */
export function diffTimelineSegments(before: TimelineSegment[] | undefined, after: TimelineSegment[]): TimelineDiffRow[] {
  if (!before) return after.map((segment) => ({ id: `context:${segment.id}`, change: "context", segment, after: segment, changedFields: [] }));
  // ponytail: quadratic LCS fits short agent edit plans; use a linear-space diff for feature-length timelines.
  const score = Array.from({ length: before.length + 1 }, () => new Float64Array(after.length + 1));
  const matchWeight = before.length + after.length + 1;
  for (let i = before.length - 1; i >= 0; i--) {
    for (let j = after.length - 1; j >= 0; j--) {
      const sameIdentity = before[i].identity === after[j].identity;
      const exact = sameIdentity && segmentChanges(before[i], after[j], (after[j].start ?? 0) - (before[i].start ?? 0)).length === 0;
      score[i][j] = sameIdentity
        ? Math.max(score[i + 1][j + 1] + matchWeight + Number(exact), score[i + 1][j], score[i][j + 1])
        : Math.max(score[i + 1][j], score[i][j + 1]);
    }
  }
  const anchors: Array<[number, number]> = [];
  let i = 0;
  let j = 0;
  while (i < before.length && j < after.length) {
    const exact = segmentChanges(before[i], after[j], (after[j].start ?? 0) - (before[i].start ?? 0)).length === 0;
    if (before[i].identity === after[j].identity && score[i][j] === score[i + 1][j + 1] + matchWeight + Number(exact)) {
      anchors.push([i++, j++]);
    } else if (score[i + 1][j] >= score[i][j + 1]) i++;
    else j++;
  }
  anchors.push([before.length, after.length]);
  const result: TimelineDiffRow[] = [];
  const ripple = new Map<string, number>();
  const offset = (segment: TimelineSegment, direction: 1 | -1) => {
    if (segment.duration !== undefined) ripple.set(segment.track, (ripple.get(segment.track) || 0) + direction * segment.duration);
  };
  const append = (old?: TimelineSegment, next?: TimelineSegment) => {
    const changedFields = old && next ? segmentChanges(old, next, ripple.get(next.track) || 0) : [];
    if (old && next && old.start !== undefined && next.start !== undefined) ripple.set(next.track, next.start - old.start);
    const key = `${old?.id || "new"}/${next?.id || "deleted"}`;
    if (old && next && !changedFields.length) result.push({ id: `context:${key}`, change: "context", segment: next, before: old, after: next, changedFields });
    else {
      if (old) result.push({ id: `removed:${key}`, change: "removed", segment: old, before: old, after: next, changedFields });
      if (next) result.push({ id: `added:${key}`, change: "added", segment: next, before: old, after: next, changedFields });
    }
    if (old) offset(old, -1);
    if (next) offset(next, 1);
  };
  i = 0; j = 0;
  for (const [oldIndex, nextIndex] of anchors) {
    // Pair only within a media lane: a removed shot cannot become an audio clip or title.
    // Visual image/video replacements share their explicit track; audio indices are positional.
    const lane = (segment: TimelineSegment) => segment.kind === "audio" || segment.kind === "text" ? segment.kind : segment.track;
    const available = new Map<string, TimelineSegment[]>();
    const paired = new Set<TimelineSegment>();
    for (let next = j; next < nextIndex; next++) {
      const key = lane(after[next]);
      if (!available.has(key)) available.set(key, []);
      available.get(key)!.push(after[next]);
    }
    while (i < oldIndex) {
      const old = before[i++];
      const next = available.get(lane(old))?.shift();
      if (next) paired.add(next);
      append(old, next);
    }
    while (j < nextIndex) {
      const next = after[j++];
      if (!paired.has(next)) append(undefined, next);
    }
    if (oldIndex < before.length && nextIndex < after.length) append(before[i++], after[j++]);
  }
  return result;
}

function planMetadata(args: Record<string, unknown>): ReviewLine[] {
  return ["title", "aspect_ratio", "fps"].map((key) => ({ id: key, text: `${key.replaceAll("_", " ")}: ${String(args[key] ?? (key === "fps" ? 30 : key === "aspect_ratio" ? "9:16" : "Untitled"))}` }));
}

function planOutput(execution: StudioExecution, event: AgentToolEvent, singlePlan: boolean): StudioAsset | undefined {
  const linked = [...event.assets, ...execution.toolEvents
    .filter((candidate) => event.providerJobId && candidate.providerJobId === event.providerJobId && candidate.name.endsWith("get_render_progress"))
    .flatMap((candidate) => candidate.assets)].filter((asset) => asset.kind === "video");
  if (linked.length) return linked.find((asset) => asset.versionId === execution.primaryAsset?.versionId) || linked.at(-1);
  const primary = execution.primaryAsset;
  const failed = ["failed", "error", "rejected", "cancelled", "canceled"].includes(event.status.toLowerCase());
  const otherSource = execution.toolEvents.some((candidate) => !candidate.name.endsWith("get_render_progress") && !candidate.name.endsWith("render_timeline") && candidate.assets.some((asset) => asset.versionId === primary?.versionId));
  return singlePlan && execution.status === "completed" && !failed && !otherSource && primary?.kind === "video" ? primary : undefined;
}

export function latestTimelineReview(executions: StudioExecution[], assets: StudioAsset[], previousPlanId?: string | null) {
  const plans = [...executions]
    .sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0) || (a.turnIndex || 0) - (b.turnIndex || 0))
    .flatMap((execution) => {
      const events = execution.toolEvents.filter((event) => event.name.endsWith("render_timeline") && rows(event.arguments.visuals).length > 0);
      return events.map((event, index) => ({ id: `${execution.jobId || execution.createdAt || "run"}:${event.id || index}`, event, execution, output: planOutput(execution, event, events.length === 1) }));
    });
  const latest = plans.at(-1);
  if (!latest) return undefined;
  const title = String(latest.event.arguments.title || "").trim();
  const earlier = plans.slice(0, -1).reverse();
  const candidates = earlier.filter((plan) => !["failed", "error", "rejected", "cancelled", "canceled", "awaiting_approval"].includes(plan.event.status.toLowerCase()));
  const sameOutput = latest.output ? candidates.find((plan) => plan.output?.assetId === latest.output?.assetId) : undefined;
  const previous = previousPlanId === null ? undefined : previousPlanId !== undefined ? earlier.find((plan) => plan.id === previousPlanId)
    : sameOutput || (title ? candidates.find((plan) => String(plan.event.arguments.title || "").trim() === title) : undefined);
  const label = (plan: typeof latest) => {
    const request = plan.event.status.toLowerCase();
    const status = ["failed", "error", "rejected", "cancelled", "canceled", "awaiting_approval"].includes(request)
      ? `request ${request.replaceAll("_", " ")}` : `run ${plan.execution.status.replaceAll("_", " ")}`;
    return `Saved plan ${plans.indexOf(plan) + 1} · ${String(plan.event.arguments.title || "Untitled")} · ${status}`;
  };
  return {
    title: String(latest.event.arguments.title || "Video edit plan"),
    outputFilename: latest.output?.filename,
    outputAsset: latest.output,
    previousOutputAsset: previous?.output,
    previousLabel: previous ? label(previous) : undefined,
    currentLabel: label(latest),
    previousPlanId: previous?.id,
    comparisons: earlier.map((plan) => ({ id: plan.id, label: label(plan) })),
    comparisonBasis: previous ? previousPlanId !== undefined ? "selected" as const : sameOutput ? "same-output" as const : "same-title" as const : undefined,
    status: latest.execution.status,
    requestStatus: latest.event.status,
    hasPrevious: Boolean(previous),
    rows: diffTimelineSegments(previous ? timelineSegments(previous.event.arguments, assets) : undefined, timelineSegments(latest.event.arguments, assets)),
    metadata: diffReviewLines(previous ? planMetadata(previous.event.arguments) : undefined, planMetadata(latest.event.arguments)),
  };
}
