import { isCents } from "./money";
import { parseLines, type NodeEstimate } from "./billing";

type ExportFormat = "project_json" | "mp4" | "webm";
type ExportDetails = { format: ExportFormat; resolution: string | null; sizeBytes: number | null; estimate: NodeEstimate | null };
export type ExportModel = ExportDetails & (
  | { state: "disconnected" }
  | { state: "configure" }
  | { state: "done"; downloadPath: string }
);

const disconnected = (): ExportModel => ({ state: "disconnected", format: "project_json", resolution: null, sizeBytes: null, estimate: null });

/** Only server metadata and complete prices may describe a render. Missing prices stay unknown. */
export function exportModel(value: unknown): ExportModel {
  if (!value || typeof value !== "object" || Array.isArray(value)) return disconnected();
  const item = value as Record<string, unknown>;
  if (item.state !== "configure" && item.state !== "done") return disconnected();
  const raw = item.estimate && typeof item.estimate === "object" ? item.estimate as Record<string, unknown> : {};
  const details: ExportDetails = {
    format: item.format === "mp4" || item.format === "webm" ? item.format : "project_json",
    resolution: typeof item.resolution === "string" && /^(720p|1080p|2160p)$/.test(item.resolution) ? item.resolution : null,
    sizeBytes: isCents(item.size_bytes) ? item.size_bytes : null,
    estimate: isCents(raw.estimate_cents) && isCents(raw.cap_cents) ? { estimateCents: raw.estimate_cents, capCents: raw.cap_cents, lines: parseLines(raw.lines) } : null,
  };
  if (item.state === "done") {
    const download = item.download_path;
    if (typeof download !== "string" || !/^\/(api\/studio\/|beta\/)[a-z0-9/_.-]+$/i.test(download) || download.includes("..")) return disconnected();
    return { ...details, state: "done", downloadPath: download };
  }
  return { ...details, state: "configure" };
}
