import type {
  FieldOptions,
  ProviderCatalog,
  StudioAccount,
  StudioAsset,
  StudioStatus,
} from "./types";
import type {
  AgentProgressEvent,
  AgentResultData,
  AgentToolEvent,
  CreativeNodeKind,
} from "./canvas/types";
import { safeCopy, workLabel } from "./rh/billing";
import { studioFetch } from "./authenticated-fetch";
import { checkUploadSize, parseUploadLimits, uploadKind, uploadSizeError } from "./upload-limits";
import { directUpload, parseDirectUploadConfig, type DirectUploadConfig } from "./direct-upload";

function studioAsset(value: unknown): StudioAsset | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const assetId = record.asset_id ?? record.assetId;
  const versionId = record.version_id ?? record.versionId;
  const kind = record.kind;
  if (
    typeof assetId !== "string" ||
    typeof versionId !== "string" ||
    !["image", "video", "audio"].includes(String(kind))
  ) {
    return null;
  }
  return {
    assetId,
    versionId,
    kind: kind as StudioAsset["kind"],
    filename: String(record.filename || `${kind}-${versionId}`),
    mimeType: String(record.mime_type ?? record.mimeType ?? "application/octet-stream"),
    ...(typeof (record.size_bytes ?? record.sizeBytes) === "number"
      ? { sizeBytes: Number(record.size_bytes ?? record.sizeBytes) }
      : {}),
    ...(typeof (record.created_at ?? record.createdAt) === "number"
      ? { createdAt: Number(record.created_at ?? record.createdAt) }
      : {}),
    ...(typeof (record.training_eligible ?? record.trainingEligible) === "boolean"
      ? { trainingEligible: (record.training_eligible ?? record.trainingEligible) === true }
      : {}),
  };
}

function studioAssets(value: unknown): StudioAsset[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map(studioAsset).filter((asset): asset is StudioAsset => asset !== null);
}

// A failed request doesn't always come back as JSON (a 500 can just be a
// plain-text or HTML error page) -- parsing that blindly throws a cryptic
// "Unexpected token" from inside JSON.parse itself, before the response.ok
// check below ever runs, so that becomes the error the user sees instead
// of a real message. Fall back to {} so the existing `payload.detail ||
// fallback` logic still produces something readable.
async function readJson(response: Response): Promise<Record<string, unknown>> {
  const payload: unknown = await response.json().catch(() => null);
  return payload && typeof payload === "object" && !Array.isArray(payload) ? { ...payload } : {};
}

export async function fetchStatus(): Promise<StudioStatus> {
  const response = await studioFetch("/api/studio/status");
  if (!response.ok) {
    throw new Error(`status ${response.status}`);
  }
  return response.json();
}

export async function fetchAccount(): Promise<StudioAccount> {
  const response = await studioFetch("/api/studio/account");
  if (!response.ok) {
    throw new Error(`account ${response.status}`);
  }
  return response.json();
}

export async function fetchTools(): Promise<ProviderCatalog[]> {
  const response = await studioFetch("/api/studio/tools");
  if (!response.ok) {
    throw new Error(`tools ${response.status}`);
  }
  const payload = await response.json();
  return payload.providers;
}

export async function fetchOptions(): Promise<FieldOptions> {
  const response = await studioFetch("/api/studio/options");
  if (!response.ok) {
    throw new Error(`options ${response.status}`);
  }
  const payload = await response.json();
  return payload.providers || {};
}

export type ToolInvocationOptions = {
  projectId: string;
  assetId?: string;
  sourceVersionIds?: string[];
  approvalToken?: string;
};

export type ToolQuote = {
  estimate_cents: number;
  cap_cents: number;
  approval_token: string;
  expires_at: number;
  balance_cents?: number;
};

export async function quoteTool(
  provider: string,
  tool: string,
  arguments_: Record<string, unknown>,
  options: ToolInvocationOptions,
): Promise<ToolQuote> {
  const response = await studioFetch("/api/studio/quote", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, tool, arguments: arguments_, project_id: options.projectId,
      asset_id: options.assetId, source_version_ids: options.sourceVersionIds || [] }),
  });
  const payload = await readJson(response);
  if (!response.ok) throw new Error(String(payload.detail || `quote ${response.status}`));
  if (typeof payload.estimate_cents !== "number" || !Number.isSafeInteger(payload.estimate_cents) || payload.estimate_cents < 0
    || typeof payload.cap_cents !== "number" || !Number.isSafeInteger(payload.cap_cents) || payload.cap_cents < payload.estimate_cents
    || typeof payload.approval_token !== "string" || !payload.approval_token) {
    throw new Error("Could not price this generation. Nothing has run.");
  }
  return payload as ToolQuote;
}

export async function invokeTool(
  provider: string,
  tool: string,
  arguments_: Record<string, unknown>,
  options: ToolInvocationOptions,
): Promise<{ result: unknown; assets: StudioAsset[] }> {
  const response = await studioFetch("/api/studio/invoke", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider,
      tool,
      arguments: arguments_,
      project_id: options.projectId,
      asset_id: options.assetId,
      source_version_ids: options.sourceVersionIds || [],
      approval_token: options.approvalToken,
    }),
  });
  const payload = await readJson(response);
  if (!response.ok) {
    throw new Error(String(payload.detail || `invoke ${response.status}`));
  }
  return {
    result: payload.result,
    assets: studioAssets(payload.assets),
  };
}

export async function uploadStudioFile(
  file: File,
  projectId: string,
  options?: { onProgress?: (uploadedBytes: number, totalBytes: number) => void },
): Promise<StudioAsset> {
  const kind = uploadKind(file.name);
  if (!kind) throw new Error("Use an image, video, or audio file.");
  let limits;
  let direct: DirectUploadConfig;
  try {
    const health = await studioFetch("/api/health", { cache: "no-store" });
    if (!health.ok) throw new Error("Could not check upload limits. Please try again.");
    const payload: unknown = await health.json();
    limits = parseUploadLimits(payload);
    direct = parseDirectUploadConfig(payload);
  } catch {
    throw new Error("Could not check upload limits. Please try again.");
  }
  // Video and audio go straight to storage in resumable parts when available,
  // so a dropped connection resumes instead of starting over.
  if (direct.enabled && (kind !== "image" || file.size > limits[kind] * 1024 * 1024)) {
    checkUploadSize(file.size, direct.maxUploadMb);
    const payload = await directUpload(file, projectId, {
      api: (path, body) => studioFetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      put: (url, body) => fetch(url, { method: "PUT", body }),
      storage: typeof localStorage === "undefined" ? null : localStorage,
      onProgress: options?.onProgress,
    });
    const asset = studioAsset(payload);
    if (!asset) throw new Error("Upload was interrupted. Please try again.");
    return asset;
  }
  checkUploadSize(file.size, limits[kind]);
  const body = new FormData();
  body.append("file", file, file.name);
  let response;
  try {
    response = await studioFetch(
      `/api/studio/upload?project_id=${encodeURIComponent(projectId)}`,
      { method: "POST", body },
    );
  } catch {
    throw new Error("Upload was interrupted. Check your connection and try again.");
  }
  const payload = await readJson(response);
  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : null;
    if (response.status === 413) throw new Error(detail || uploadSizeError(limits[kind]));
    if (response.status === 415) throw new Error(detail || "Use an image, video, or audio file.");
    if (response.status === 400 || response.status === 422) {
      throw new Error(detail && !detail.includes("parsing the body") ? detail : "Upload was interrupted. Please try again.");
    }
    throw new Error(detail || "Upload failed. Please try again.");
  }
  const asset = studioAsset(payload);
  if (!asset) {
    throw new Error("Upload was interrupted. Please try again.");
  }
  return asset;
}

export type StudioProject = {
  id: string;
  name: string;
  /** Optional preview stills (up to four). Absent for projects with no media yet. */
  thumbs?: string[];
  file_count?: number;
  created_at?: number;
  updated_at?: number;
};

export type StudioCanvasDocument = {
  schemaVersion?: number;
  projectName: string;
  nodes: unknown[];
  edges: unknown[];
  viewport: { x: number; y: number; zoom: number };
};

export async function fetchStudioProjects(): Promise<StudioProject[]> {
  const response = await studioFetch("/api/studio/projects", { cache: "no-store" });
  const payload = await readJson(response);
  if (!response.ok) {
    throw new Error(String(payload.detail || `projects ${response.status}`));
  }
  return Array.isArray(payload.items) ? (payload.items as StudioProject[]) : [];
}

export async function createStudioProject(
  name = "Untitled",
  projectId?: string,
): Promise<StudioProject> {
  const response = await studioFetch("/api/studio/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, project_id: projectId }),
  });
  const payload = await readJson(response);
  if (!response.ok) {
    throw new Error(String(payload.detail || `create project ${response.status}`));
  }
  return payload as unknown as StudioProject;
}

export type StudioCanvasSnapshot = {
  revision: number;
  document: StudioCanvasDocument;
};

export async function fetchStudioCanvas(projectId: string): Promise<StudioCanvasSnapshot> {
  const response = await studioFetch(
    `/api/studio/projects/${encodeURIComponent(projectId)}/canvas`,
    { cache: "no-store" },
  );
  const payload = await readJson(response);
  if (!response.ok) {
    throw new Error(String(payload.detail || `canvas ${response.status}`));
  }
  return { revision: Number(payload.revision || 1), document: payload.document as StudioCanvasDocument };
}

export async function saveStudioCanvas(
  projectId: string,
  document: StudioCanvasDocument,
  baseRevision?: number,
): Promise<StudioCanvasSnapshot> {
  const response = await studioFetch(
    `/api/studio/projects/${encodeURIComponent(projectId)}/canvas`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document, base_revision: baseRevision }),
    },
  );
  const payload = await readJson(response);
  if (!response.ok) {
    throw new Error(String(payload.detail || `save canvas ${response.status}`));
  }
  return {
    revision: Number(payload.revision || baseRevision || 1),
    document: payload.document as StudioCanvasDocument,
  };
}

export type StudioExecution = {
  jobId: string;
  projectId?: string;
  conversationId?: string;
  turnIndex?: number;
  prompt: string;
  status: string;
  message: string;
  title?: string;
  summary?: string;
  primaryAsset?: StudioAsset;
  toolEvents: AgentToolEvent[];
  progressEvents: AgentProgressEvent[];
  assets: StudioAsset[];
  result?: AgentResultData;
  errorType?: string;
  checkpointAt?: number;
  recoveryAvailable: boolean;
  canResume: boolean;
  createdAt?: number;
  updatedAt?: number;
  autonomous: boolean;
  approvals: AgentPendingRequest[];
  /** `execution.paused_cap`: present while the run is stopped at its hard cap. Cents only. */
  pausedCap?: Record<string, unknown>;
  /** `execution.receipt`: present once the run has ended. Cents only. */
  receipt?: Record<string, unknown>;
};

export type QuestionAnswer = { kind: "choice"; option_id: string } | { kind: "text"; text: string };

export type AgentQuestionRequest = {
  kind: "question";
  callId: string;
  question: string;
  reason: "cost_difference" | "irreversible_outcome";
  options: Array<{ id: string; label: string; description: string; estimateCents?: number }>;
  allowFreeText: boolean;
  decision?: "answer";
  answer?: QuestionAnswer;
};

export type AgentPendingRequest = AgentApprovalRequest | AgentQuestionRequest;

export type AgentApprovalRequest = {
  kind: "approval";
  callId: string;
  toolName: string;
  label: string;
  provider?: string;
  arguments: Record<string, unknown>;
  /** The approval item exactly as the server sent it (price fields: estimate_cents, cap_cents, lines[], status, ...). */
  billing?: Record<string, unknown>;
  decision?: "approve" | "reject";
  message?: string;
};

function billingRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function questionAnswer(value: unknown): QuestionAnswer | undefined {
  const answer = billingRecord(value);
  if (answer?.kind === "choice" && typeof answer.option_id === "string" && answer.option_id.trim()) {
    return { kind: "choice", option_id: answer.option_id };
  }
  if (answer?.kind === "text" && typeof answer.text === "string" && answer.text.trim()) {
    return { kind: "text", text: answer.text };
  }
  return undefined;
}

function agentApprovals(value: unknown): AgentPendingRequest[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((approval): AgentPendingRequest[] => {
    const item = billingRecord(approval);
    if (!item) return [];
    const callId = item.call_id;
    if (typeof callId !== "string" || !callId) return [];
    if (item.kind === "question") {
      // An unknown reason must not hide the question: a hidden question leaves the run stuck.
      const options = Array.isArray(item.options) ? item.options.flatMap((value) => {
        const option = billingRecord(value);
        if (!option || typeof option.id !== "string" || typeof option.label !== "string") return [];
        const estimate = option.estimate_cents;
        return [{
          id: option.id, label: safeCopy(option.label, "Option"), description: safeCopy(option.description, ""),
          ...(typeof estimate === "number" && Number.isSafeInteger(estimate) && estimate >= 0 ? { estimateCents: estimate } : {}),
        }];
      }) : [];
      return [{
        kind: "question", callId, question: safeCopy(item.question, "Which outcome should I use?"),
        reason: item.reason === "irreversible_outcome" ? "irreversible_outcome" : "cost_difference", options, allowFreeText: item.allow_free_text === true,
        decision: item.decision === "answer" ? "answer" : undefined,
        answer: questionAnswer(item.answer),
      }];
    }
    return [{
      kind: "approval",
      callId,
      toolName: String(item.tool_name || "tool"),
      label: item.label === item.tool_name ? workLabel(String(item.tool_name)) : safeCopy(item.label, workLabel(String(item.tool_name))),
      provider: typeof item.provider === "string" ? item.provider : undefined,
      arguments:
        item.arguments && typeof item.arguments === "object" && !Array.isArray(item.arguments)
          ? (item.arguments as Record<string, unknown>)
          : {},
      billing: billingRecord(item),
      decision:
        item.decision === "approve" || item.decision === "reject" ? item.decision : undefined,
      message: safeCopy(item.message, "") || undefined,
    }];
  });
}

function logoArtifactNames(value: unknown): string[] {
  if (!value || typeof value !== 'object' || !('outputs' in value) || !Array.isArray(value.outputs)) return [];
  return value.outputs.flatMap((row: unknown) => {
    if (!row || typeof row !== 'object' || !('filename' in row) || typeof row.filename !== 'string') return [];
    return /^[A-Za-z0-9_.-]+\.(svg|png|html|md|json)$/.test(row.filename) ? [row.filename] : [];
  });
}

export async function downloadLogoArtifact(executionId: string, callId: string, filename: string): Promise<Blob> {
  const response = await studioFetch(`/api/studio/executions/${encodeURIComponent(executionId)}/logo-artifacts/${encodeURIComponent(callId)}/${encodeURIComponent(filename)}`);
  if (!response.ok) throw new Error('This logo file is unavailable. Prepare the logo again.');
  return response.blob();
}

function referenceArtifactNames(value: unknown): string[] {
  if (!value || typeof value !== 'object' || !('outputs' in value) || !Array.isArray(value.outputs)) return [];
  return value.outputs.flatMap((row: unknown) => {
    if (!row || typeof row !== 'object' || !('filename' in row) || typeof row.filename !== 'string') return [];
    return /^[A-Za-z0-9_.-]+\.(json|csv|html|jpg|png|mp4)$/.test(row.filename) ? [row.filename] : [];
  });
}

export async function downloadReferenceArtifact(executionId: string, callId: string, filename: string): Promise<Blob> {
  const response = await studioFetch(`/api/studio/executions/${encodeURIComponent(executionId)}/reference-artifacts/${encodeURIComponent(callId)}/${encodeURIComponent(filename)}`);
  if (!response.ok) throw new Error('This reference file is unavailable. Analyze the reference again.');
  return response.blob();
}

function agentToolEvents(value: unknown): AgentToolEvent[] {
  if (!Array.isArray(value)) return [];
  return value.map((event) => {
    const item = event as Record<string, unknown>;
    return {
      id: String(item.id || crypto.randomUUID()),
      name: String(item.name || "tool"),
      label: item.label === item.name ? workLabel(String(item.name)) : safeCopy(item.label, workLabel(String(item.name))),
      status: String(item.status || "completed"),
      summary: safeCopy(item.summary, ""),
      provider: typeof item.provider === "string" ? item.provider : undefined,
      providerJobId:
        typeof item.provider_job_id === "string" ? item.provider_job_id : undefined,
      arguments:
        item.arguments && typeof item.arguments === "object" && !Array.isArray(item.arguments)
          ? (item.arguments as Record<string, unknown>)
          : {},
      assets: studioAssets(item.assets),
      logoArtifacts: item.name === 'Logo___logo_vectorize' ? logoArtifactNames(item.result) : undefined,
      referenceArtifacts: item.name === 'Reference___shot_breakdown' ? referenceArtifactNames(item.result) : undefined,
    };
  });
}

function agentProgressEvents(value: unknown): AgentProgressEvent[] {
  if (!Array.isArray(value)) return [];
  return value.map((event) => {
    const item = event as Record<string, unknown>;
    return {
      id: String(item.id || crypto.randomUUID()),
      type: String(item.type || "STEP_STARTED"),
      title: safeCopy(item.title, "Agent update"),
      message: safeCopy(item.message, ""),
      status: String(item.status || "running"),
      toolCallId:
        typeof item.tool_call_id === "string" ? item.tool_call_id : undefined,
      toolCallName:
        typeof item.tool_call_name === "string" ? item.tool_call_name : undefined,
      createdAt: typeof item.created_at === "number" ? item.created_at : undefined,
    };
  });
}

function uniqueAssets(...groups: StudioAsset[][]): StudioAsset[] {
  const assets = new Map<string, StudioAsset>();
  for (const group of groups) {
    for (const asset of group) assets.set(asset.versionId, asset);
  }
  return [...assets.values()];
}

export async function fetchStudioExecutions(
  projectId?: string,
  conversationId?: string,
  limit = 50,
): Promise<StudioExecution[]> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (projectId) query.set("project_id", projectId);
  if (conversationId) query.set("conversation_id", conversationId);
  const response = await studioFetch(`/api/studio/agent?${query}`, { cache: "no-store" });
  const payload = await readJson(response);
  if (!response.ok) {
    throw new Error(String(payload.detail || `agent jobs ${response.status}`));
  }
  return (Array.isArray(payload.items) ? payload.items : []).map((value: unknown) => {
    const item = value as Record<string, unknown>;
    const result = (item.result || {}) as Record<string, unknown>;
    const resultToolEvents = agentToolEvents(result.tool_events);
    const toolEvents = resultToolEvents.length
      ? resultToolEvents
      : agentToolEvents(item.tool_calls);
    const resultAssets = studioAssets(result.assets);
    const assets = uniqueAssets(resultAssets, toolEvents.flatMap((event) => event.assets));
    const primaryAsset = studioAsset(result.primary_asset) || undefined;
    const agentResult = item.result
      ? {
          executionId: String(item.job_id || "") || undefined,
          title: String(result.title || "Agent result"),
          summary: String(result.summary || "The agent completed the request."),
          markdown: String(result.markdown || ""),
          filename: String(result.filename || "agent-result.md"),
          mimeType: String(result.mime_type || "text/markdown;charset=utf-8"),
          toolEvents,
          assets,
          primaryAsset,
          partial: result.partial === true,
        }
      : undefined;
    return {
      jobId: String(item.job_id || ""),
      projectId: typeof item.project_id === "string" ? item.project_id : undefined,
      conversationId:
        typeof item.conversation_id === "string" ? item.conversation_id : undefined,
      turnIndex: typeof item.turn_index === "number" ? item.turn_index : undefined,
      prompt: String(item.prompt || ""),
      status: String(item.status || "unknown"),
      message: safeCopy(item.message, ""),
      title: safeCopy(result.title, "") || undefined,
      summary: safeCopy(result.summary, "") || undefined,
      primaryAsset,
      toolEvents,
      progressEvents: agentProgressEvents(item.events),
      assets,
      result: agentResult,
      checkpointAt: typeof item.checkpoint_at === "number" ? item.checkpoint_at : undefined,
      recoveryAvailable: item.recovery_available === true,
      canResume: item.can_resume === true,
      errorType: typeof item.error_type === "string" ? item.error_type : undefined,
      createdAt: typeof item.created_at === "number" ? item.created_at : undefined,
      updatedAt: typeof item.updated_at === "number" ? item.updated_at : undefined,
      autonomous: item.autonomous === true,
      approvals: agentApprovals(item.approvals),
      pausedCap: billingRecord(item.paused_cap),
      receipt: billingRecord(item.receipt),
    };
  });
}

export type StudioConversation = {
  id: string;
  projectId: string;
  title: string;
  status: "active" | "archived";
  createdAt: number;
  updatedAt: number;
};

function studioConversation(value: unknown): StudioConversation {
  const item = value as Record<string, unknown>;
  return {
    id: String(item.id || ""),
    projectId: String(item.project_id || ""),
    title: String(item.title || "New conversation"),
    status: item.status === "archived" ? "archived" : "active",
    createdAt: Number(item.created_at || 0),
    updatedAt: Number(item.updated_at || 0),
  };
}

export async function fetchStudioConversations(
  projectId: string,
): Promise<StudioConversation[]> {
  const response = await studioFetch(
    `/api/studio/projects/${encodeURIComponent(projectId)}/agent-conversations`,
    { cache: "no-store" },
  );
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `agent conversations ${response.status}`);
  }
  return (Array.isArray(payload.items) ? payload.items : []).map(studioConversation);
}

export async function createStudioConversation(
  projectId: string,
  title = "New conversation",
): Promise<StudioConversation> {
  const response = await studioFetch(
    `/api/studio/projects/${encodeURIComponent(projectId)}/agent-conversations`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    },
  );
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || `create conversation ${response.status}`);
  return studioConversation(payload);
}

export async function updateStudioConversation(
  conversationId: string,
  patch: { title?: string; status?: "active" | "archived" },
): Promise<StudioConversation> {
  const response = await studioFetch(
    `/api/studio/agent-conversations/${encodeURIComponent(conversationId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    },
  );
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || `update conversation ${response.status}`);
  return studioConversation(payload);
}

export type AgentSubmissionResult =
  | { status: "completed"; message: string; result: AgentResultData }
  | { status: "awaiting_approval"; message: string; jobId: string }
  | { status: "error"; message: string; result?: AgentResultData; unreachable?: boolean };

export type AgentNodeContext = {
  id: string;
  title: string;
  kind: CreativeNodeKind;
  prompt: string;
  asset_id?: string;
  version_id?: string;
};

type AgentJobPayload = {
  job_id?: string;
  project_id?: string;
  conversation_id?: string;
  prompt?: string;
  status?: string;
  message?: string;
  detail?: string;
  result?: Record<string, unknown>;
  tool_calls?: unknown[];
  events?: unknown[];
  error_type?: string;
  created_at?: number;
  updated_at?: number;
  autonomous?: boolean;
  approvals?: unknown[];
  paused_cap?: unknown;
  receipt?: unknown;
};

export type AgentProgress = {
  jobId?: string;
  status: string;
  message: string;
  toolEvents: AgentToolEvent[];
  progressEvents: AgentProgressEvent[];
  result?: AgentResultData;
  autonomous: boolean;
  approvals: AgentPendingRequest[];
  pausedCap?: Record<string, unknown>;
  receipt?: Record<string, unknown>;
};

export const AGENT_PROMPT_MAX_CHARS = 64_000;
const AGENT_POLL_INTERVAL_MS = 1_000;
const AGENT_POLL_TIMEOUT_MS = 20 * 60 * 1_000;

function isAgentFailureStatus(status: unknown): boolean {
  return ["error", "failed"].includes(String(status));
}

function agentError(payload: AgentJobPayload, response: Response): AgentSubmissionResult {
  const detail = payload.detail as unknown;
  const detailMessage = detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string"
    ? (detail as { message: string }).message : null;
  const message =
    typeof payload.detail === "string"
      ? payload.detail
      : detailMessage
        ? detailMessage
      : typeof payload.message === "string"
        ? payload.message
        : `The agent request failed (${response.status}).`;
  return { status: "error", message, unreachable: response.status >= 500 };
}

function completedAgentResult(payload: AgentJobPayload): AgentSubmissionResult {
  const value = payload.result || {};
  const resultToolEvents = agentToolEvents(value.tool_events);
  const toolEvents = resultToolEvents.length
    ? resultToolEvents
    : agentToolEvents(payload.tool_calls);
  const assets = uniqueAssets(
    studioAssets(value.assets),
    toolEvents.flatMap((event) => event.assets),
  );
  return {
    status: "completed",
    message: typeof payload.message === "string" ? payload.message : "The agent completed the request.",
    result: {
      executionId: typeof payload.job_id === "string" ? payload.job_id : undefined,
      title: String(value.title || "Agent result"),
      summary: String(value.summary || "The agent completed the request."),
      markdown: String(value.markdown || ""),
      filename: String(value.filename || "agent-result.md"),
      mimeType: String(value.mime_type || "text/markdown;charset=utf-8"),
      toolEvents,
      assets,
      primaryAsset:
        value.primary_asset && typeof value.primary_asset === "object"
          ? studioAsset(value.primary_asset) || undefined
          : undefined,
      partial: value.partial === true,
    },
  };
}

function agentProgress(payload: AgentJobPayload): AgentProgress {
  const completed = payload.result ? completedAgentResult(payload) : undefined;
  const result = completed && "result" in completed ? completed.result : undefined;
  return {
    jobId: payload.job_id,
    status: String(payload.status || "running"),
    message: String(payload.message || "Agent is working."),
    toolEvents:
      result?.toolEvents.length
        ? result.toolEvents
        : agentToolEvents(payload.tool_calls),
    progressEvents: agentProgressEvents(payload.events),
    ...(result ? { result } : {}),
    autonomous: payload.autonomous === true,
    approvals: agentApprovals(payload.approvals),
    pausedCap: billingRecord(payload.paused_cap),
    receipt: billingRecord(payload.receipt),
  };
}

async function waitForAgentJob(
  jobId: string,
  onProgress?: (progress: AgentProgress) => void,
): Promise<AgentSubmissionResult> {
  const deadline = Date.now() + AGENT_POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, AGENT_POLL_INTERVAL_MS));
    const response = await studioFetch(`/api/studio/agent/${encodeURIComponent(jobId)}`, {
      cache: "no-store",
    });
    const payload = (await response.json().catch(() => ({}))) as AgentJobPayload;
    if (!response.ok) {
      return agentError(payload, response);
    }
    onProgress?.(agentProgress(payload));
    if (payload.status === "completed") {
      return completedAgentResult(payload);
    }
    if (payload.status === "awaiting_approval") {
      return {
        status: "awaiting_approval",
        message: payload.message || "Waiting for tool approval.",
        jobId,
      };
    }
    if (isAgentFailureStatus(payload.status)) {
      const partial = payload.result ? completedAgentResult(payload) : null;
      return {
        status: "error",
        message: payload.message || "The agent could not finish this request.",
        ...(partial?.status === "completed" ? { result: partial.result } : {}),
      };
    }
  }
  return {
    status: "error",
    message: "The agent is still running. Refresh the canvas and try again shortly.",
  };
}

async function streamAgentJob(
  jobId: string,
  onProgress?: (progress: AgentProgress) => void,
): Promise<AgentSubmissionResult> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), AGENT_POLL_TIMEOUT_MS);
  try {
    const response = await studioFetch(
      `/api/studio/agent/${encodeURIComponent(jobId)}/events`,
      {
        cache: "no-store",
        headers: { Accept: "text/event-stream" },
        signal: controller.signal,
      },
    );
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as AgentJobPayload;
      return agentError(payload, response);
    }
    if (!response.body) return waitForAgentJob(jobId, onProgress);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || "";
        for (const frame of frames) {
          const data = frame
            .split(/\r?\n/)
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart())
            .join("\n");
          if (!data) continue;
          let payload: AgentJobPayload;
          try {
            payload = JSON.parse(data) as AgentJobPayload;
          } catch {
            continue;
          }
          onProgress?.(agentProgress(payload));
          if (payload.status === "completed") return completedAgentResult(payload);
          if (payload.status === "awaiting_approval") {
            return {
              status: "awaiting_approval",
              message: payload.message || "Waiting for tool approval.",
              jobId,
            };
          }
          if (isAgentFailureStatus(payload.status)) {
            const partial = payload.result ? completedAgentResult(payload) : null;
            return {
              status: "error",
              message: payload.message || "The agent could not finish this request.",
              ...(partial?.status === "completed" ? { result: partial.result } : {}),
            };
          }
        }
        if (done) break;
      }
    } finally {
      await reader.cancel().catch(() => undefined);
      reader.releaseLock();
    }
  } catch {
    if (controller.signal.aborted) {
      return {
        status: "error",
        message: "The agent stream timed out. Refresh the canvas to check the saved run.",
      };
    }
    // Fall back to polling for older deployments and interrupted proxy streams.
  } finally {
    window.clearTimeout(timeoutId);
  }
  return waitForAgentJob(jobId, onProgress);
}

export async function submitAgentPrompt(
  prompt: string,
  projectId: string,
  conversationId: string,
  nodeIds: string[],
  nodes: AgentNodeContext[],
  autonomous: boolean,
  onProgress?: (progress: AgentProgress) => void,
): Promise<AgentSubmissionResult> {
  let response: Response;
  try {
    response = await studioFetch("/api/studio/agent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      project_id: projectId,
      conversation_id: conversationId,
      node_ids: nodeIds,
      nodes,
      autonomous,
    }),
  });
  } catch {
    return { status: "error", message: "Couldn't reach Renderhaus", unreachable: true };
  }
  const payload = (await response.json().catch(() => ({}))) as AgentJobPayload;
  if (!response.ok) {
    return agentError(payload, response);
  }
  if (payload.status === "completed") {
    return completedAgentResult(payload);
  }
  if (!payload.job_id) {
    return { status: "error", message: "The agent did not return a job identifier." };
  }
  onProgress?.(agentProgress(payload));
  return streamAgentJob(payload.job_id, onProgress);
}

export async function decideAgentApproval(
  jobId: string,
  callId: string,
  decision: "approve" | "reject",
  capCents?: number,
  source?: "not_now",
): Promise<AgentProgress> {
  const body: Record<string, unknown> = { decision };
  if (capCents !== undefined) body.cap_cents = capCents;
  if (source) body.message = source;
  const response = await studioFetch(
    `/api/studio/agent/${encodeURIComponent(jobId)}/approvals/${encodeURIComponent(callId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  const payload = (await response.json().catch(() => ({}))) as AgentJobPayload;
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || `approval ${response.status}`);
  }
  return agentProgress(payload);
}

export async function answerAgentQuestion(jobId: string, callId: string, answer: QuestionAnswer): Promise<AgentProgress> {
  const response = await studioFetch(
    `/api/studio/agent/${encodeURIComponent(jobId)}/questions/${encodeURIComponent(callId)}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer }) },
  );
  const payload = (await response.json().catch(() => ({}))) as AgentJobPayload;
  if (!response.ok) throw new Error(payload.detail || payload.message || "The answer could not be saved.");
  return agentProgress(payload);
}

/** Answer a "paused at cap" run: raise the cap to a new total (the run continues) or stop here. */
export async function answerAgentCap(jobId: string, action: "raise" | "stop", capCents?: number): Promise<AgentProgress> {
  const response = await studioFetch(`/api/studio/agent/${encodeURIComponent(jobId)}/cap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(action === "raise" ? { action, cap_cents: capCents } : { action }),
  });
  const payload = (await response.json().catch(() => ({}))) as AgentJobPayload;
  if (!response.ok) {
    const detail = payload.detail as unknown;
    throw new Error(typeof detail === "string" ? detail : "The cap could not be changed. Nothing more has been charged.");
  }
  return agentProgress(payload);
}

export async function resumeAgentRun(jobId: string) {
  const response = await studioFetch(`/api/studio/agent/${encodeURIComponent(jobId)}/resume`, {method: "POST"});
  const payload = await readJson(response);
  if (!response.ok) throw new Error(String(payload.detail || "Could not resume this run."));
  return payload;
}
export async function stopAgentRun(jobId: string) {
  const response = await studioFetch(`/api/studio/agent/${encodeURIComponent(jobId)}/stop`, {method: "POST"});
  const payload = await readJson(response);
  if (!response.ok) throw new Error(String(payload.detail || "Could not stop this run."));
  return payload;
}
