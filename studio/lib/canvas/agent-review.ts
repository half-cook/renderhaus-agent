import type { StudioExecution } from "@/lib/api";
import type { StudioAsset } from "@/lib/types";
import type { CanvasNode } from "./connection-validation";
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
    return asset ? `${asset.filename} [${version.slice(0, 8)}]` : version;
  }
  // External source queries can contain credentials. Only a filename belongs in the review UI.
  try { return new URL(value).pathname.split("/").filter(Boolean).at(-1) || "External media"; }
  catch { return "External media"; }
}

/** Shows the recorded edit instructions, not inferred pixel changes in a rendered video. */
export function timelineReviewLines(args: Record<string, unknown>, assets: StudioAsset[]): ReviewLine[] {
  const result: ReviewLine[] = [];
  for (const field of ["title", "aspect_ratio", "fps"] as const) {
    if (args[field] !== undefined) result.push({ id: field, text: `${field.replaceAll("_", " ")}: ${String(args[field])}` });
  }
  for (const [field, label] of [["visuals", "Video"], ["audio_tracks", "Audio"], ["text_overlays", "Title"]]) {
    rows(args[field]).forEach((clip, index) => {
      const name = field === "text_overlays" ? String(clip.text || "Untitled") : sourceName(clip.url, assets);
      const properties = Object.entries(clip)
        .filter(([key, value]) => key !== "url" && key !== "text" && value !== undefined && value !== null)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, value]) => `${key.replaceAll("_", " ")}: ${String(value)}`);
      result.push({ id: `${field}-${index}`, text: `${label} ${index + 1}  ${name}  ·  ${properties.join(" · ")}` });
    });
  }
  return result;
}

export function latestTimelineReview(executions: StudioExecution[], assets: StudioAsset[]) {
  const plans = [...executions]
    .sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0) || (a.turnIndex || 0) - (b.turnIndex || 0))
    .flatMap((execution) => execution.toolEvents
      .filter((event) => event.name.endsWith("render_timeline") && rows(event.arguments.visuals).length > 0)
      .map((event) => ({ event, execution })));
  const latest = plans.at(-1);
  if (!latest) return undefined;
  const previous = plans.at(-2);
  return {
    title: String(latest.event.arguments.title || "Video edit plan"),
    outputFilename: latest.execution.primaryAsset?.kind === "video" ? latest.execution.primaryAsset.filename : undefined,
    status: latest.execution.status,
    requestStatus: latest.event.status,
    hasPrevious: Boolean(previous),
    lines: diffReviewLines(
      previous ? timelineReviewLines(previous.event.arguments, assets) : undefined,
      timelineReviewLines(latest.event.arguments, assets),
    ),
  };
}
