// Wire types for server/app.py's REST API. Hand-written from reading the
// actual FastAPI route/model definitions, not generated -- there is no
// OpenAPI client in this repo yet. Keep in sync with server/app.py,
// server/projects.py, server/productions.py, agent/director.py if any of
// those Pydantic models change shape.

export type MediaType = "video" | "image" | "music";
export type AspectRatio = "16:9" | "9:16" | "1:1";

export interface Config {
  live_generation: boolean;
  live_image_generation: boolean;
  live_music_generation: boolean;
  agent_ready: boolean;
  langfuse_ready: boolean;
  clerk_enabled: boolean;
  clerk_publishable_key: string;
  video_model: string;
  image_model: string;
  music_model: string;
  max_upload_mb: number;
}

export interface MeResponse {
  authenticated: boolean;
  user_id: string | null;
  session_id?: string;
}

export interface UploadResponse {
  asset_id: string;
  name: string;
}

// --- Generations -------------------------------------------------------

export interface GenerationRequest {
  prompt: string;
  media_type: MediaType;
  vibe?: string;
  aspect_ratio?: AspectRatio;
  duration_seconds?: number;
  reference_asset_id?: string | null;
  project_id?: string | null;
}

export interface RefinementRequest {
  instruction: string;
}

export type JobStatus = "queued" | "planning" | "generating" | "complete" | "planned" | "failed";

// Statuses a poller should stop on -- everything else keeps polling.
export const TERMINAL_JOB_STATES: ReadonlySet<JobStatus> = new Set([
  "complete",
  "planned",
  "failed",
]);

export interface JobError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface Trace {
  id: string;
  kind: "status" | "tool";
  title: string;
  detail: string;
  status: "running" | "done" | "error";
  at: number;
}

export interface Job {
  id: string;
  schema_version: number;
  status: JobStatus;
  phase: string;
  media_type: MediaType;
  prompt: string;
  vibe: string;
  aspect_ratio: AspectRatio;
  duration_seconds: number | null;
  reference_asset_id: string | null;
  output_asset_id: string | null;
  parent_id: string | null;
  project_id: string | null;
  created_at: number;
  updated_at: number;
  message: string;
  // Same-origin signed URL, ~15min TTL from when this job object was
  // rendered server-side -- don't cache across reloads, refetch the job
  // instead of reusing a stale media_url.
  media_url: string | null;
  error: JobError | null;
  traces: Trace[];
  progress: number;
}

// --- Projects ------------------------------------------------------------

export interface ProjectCreateRequest {
  title: string;
  description?: string;
}

export interface ProjectUpdateRequest {
  title?: string;
  description?: string;
}

export interface TimelineItemModel {
  id?: string;
  job_id: string;
  asset_id?: string | null;
  media_type?: MediaType;
  label?: string;
  duration_seconds?: number | null;
}

export interface Project {
  id: string;
  schema_version: number;
  title: string;
  description: string;
  user_id: string;
  created_at: number;
  updated_at: number;
  artifact_ids: string[];
  artifact_count: number;
  timeline: { items: TimelineItemModel[] };
  timeline_count: number;
}

// --- Productions -----------------------------------------------------------

export interface ProductionCreateRequest {
  brief: string;
  title?: string;
  plan_now?: boolean;
}

export interface ProductionApproveRequest {
  execute?: boolean;
}

export type ProductionStatus =
  | "draft"
  | "planning"
  | "plan_ready"
  | "approved"
  | "running"
  | "completed"
  | "failed";

export const TERMINAL_PLAN_STATES: ReadonlySet<ProductionStatus> = new Set(["plan_ready", "failed"]);
export const TERMINAL_RUN_STATES: ReadonlySet<ProductionStatus> = new Set(["completed", "failed"]);

export type NodeKind = "video" | "image" | "music" | "speech";

export interface PlanNode {
  id: string;
  kind: NodeKind;
  prompt: string;
  depends_on: string[];
  lyrics?: string | null;
  notes?: string | null;
}

export interface ProductionPlan {
  title: string;
  summary: string;
  nodes: PlanNode[];
  rationale: string;
}

export interface NodeResult {
  node_id: string;
  kind: NodeKind;
  status?: string;
  artifacts?: unknown[];
  poll?: { status?: string; [key: string]: unknown };
  [key: string]: unknown;
}

export interface ProductionExecution {
  title: string;
  summary: string;
  rationale: string;
  node_results: NodeResult[];
  status: "completed";
}

export interface Production {
  id: string;
  schema_version: number;
  user_id: string;
  brief: string;
  title: string;
  status: ProductionStatus;
  plan: ProductionPlan | null;
  execution: ProductionExecution | null;
  error: string | null;
  created_at: number;
  updated_at: number;
  approved_at: number | null;
  completed_at: number | null;
}

// --- Error shape -----------------------------------------------------------

// FastAPI hand-raised errors: {"detail": "<string>"}.
// Pydantic validation failures: {"detail": [{"loc": [...], "msg": "...", "type": "..."}]}.
export interface ApiErrorBody {
  detail?: string | Array<{ loc?: unknown[]; msg?: string; type?: string }>;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}
