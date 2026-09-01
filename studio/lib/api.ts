import type { FieldOptions, ProviderCatalog, StudioAsset, StudioStatus } from "./types";
import type {
  AgentProgressEvent,
  AgentResultData,
  AgentToolEvent,
  CreativeNodeKind,
} from "./canvas/types";
import { studioFetch } from "./authenticated-fetch";

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
  };
}

function studioAssets(value: unknown): StudioAsset[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map(studioAsset).filter((asset): asset is StudioAsset => asset !== null);
}

export async function fetchStatus(): Promise<StudioStatus> {
  const response = await studioFetch("/api/studio/status");
  if (!response.ok) {
    throw new Error(`status ${response.status}`);
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

export async function invokeTool(
  provider: string,
  tool: string,
  arguments_: Record<string, unknown>,
  options: {
    projectId: string;
    assetId?: string;
    sourceVersionIds?: string[];
  },
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
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `invoke ${response.status}`);
  }
  return {
    result: payload.result,
    assets: studioAssets(payload.assets),
  };
}

export async function uploadStudioFile(
  file: File,
  projectId: string,
): Promise<StudioAsset> {
  const body = new FormData();
  body.append("file", file);
  const response = await studioFetch(
    `/api/studio/upload?project_id=${encodeURIComponent(projectId)}`,
    { method: "POST", body },
  );
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `upload ${response.status}`);
  }
  const asset = studioAsset(payload);
  if (!asset) {
    throw new Error("The upload did not return an asset version.");
  }
  return asset;
}

export type StudioProject = { id: string; name: string };

export type StudioCanvasDocument = {
  schemaVersion?: number;
  projectName: string;
  nodes: unknown[];
  edges: unknown[];
  viewport: { x: number; y: number; zoom: number };
};

export async function fetchStudioProjects(): Promise<StudioProject[]> {
  const response = await studioFetch("/api/studio/projects", { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `projects ${response.status}`);
  }
  return Array.isArray(payload.items) ? payload.items : [];
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
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `create project ${response.status}`);
  }
  return payload;
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
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `canvas ${response.status}`);
  }
  return { revision: Number(payload.revision || 1), document: payload.document };
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
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `save canvas ${response.status}`);
  }
  return { revision: Number(payload.revision || baseRevision || 1), document: payload.document };
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
  createdAt?: number;
  updatedAt?: number;
  autonomous: boolean;
  approvals: AgentApprovalRequest[];
};

export type AgentApprovalRequest = {
  callId: string;
  toolName: string;
  label: string;
  provider?: string;
  arguments: Record<string, unknown>;
  decision?: "approve" | "reject";
  message?: string;
};

function agentApprovals(value: unknown): AgentApprovalRequest[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((approval) => {
    const item = approval as Record<string, unknown>;
    const callId = item.call_id;
    if (typeof callId !== "string" || !callId) return [];
    return [{
      callId,
      toolName: String(item.tool_name || "tool"),
      label: String(item.label || item.tool_name || "Tool"),
      provider: typeof item.provider === "string" ? item.provider : undefined,
      arguments:
        item.arguments && typeof item.arguments === "object" && !Array.isArray(item.arguments)
          ? (item.arguments as Record<string, unknown>)
          : {},
      decision:
        item.decision === "approve" || item.decision === "reject" ? item.decision : undefined,
      message: typeof item.message === "string" ? item.message : undefined,
    }];
  });
}

function agentToolEvents(value: unknown): AgentToolEvent[] {
  if (!Array.isArray(value)) return [];
  return value.map((event) => {
    const item = event as Record<string, unknown>;
    return {
      id: String(item.id || crypto.randomUUID()),
      name: String(item.name || "tool"),
      label: String(item.label || "Tool"),
      status: String(item.status || "completed"),
      summary: String(item.summary || ""),
      provider: typeof item.provider === "string" ? item.provider : undefined,
      providerJobId:
        typeof item.provider_job_id === "string" ? item.provider_job_id : undefined,
      arguments:
        item.arguments && typeof item.arguments === "object" && !Array.isArray(item.arguments)
          ? (item.arguments as Record<string, unknown>)
          : {},
      assets: studioAssets(item.assets),
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
      title: String(item.title || "Agent update"),
      message: String(item.message || ""),
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
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `agent jobs ${response.status}`);
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
      message: String(item.message || ""),
      title: typeof result.title === "string" ? result.title : undefined,
      summary: typeof result.summary === "string" ? result.summary : undefined,
      primaryAsset,
      toolEvents,
      progressEvents: agentProgressEvents(item.events),
      assets,
      result: agentResult,
      errorType: typeof item.error_type === "string" ? item.error_type : undefined,
      createdAt: typeof item.created_at === "number" ? item.created_at : undefined,
      updatedAt: typeof item.updated_at === "number" ? item.updated_at : undefined,
      autonomous: item.autonomous === true,
      approvals: agentApprovals(item.approvals),
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
  | { status: "error"; message: string; result?: AgentResultData };

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
};

export type AgentProgress = {
  jobId?: string;
  status: string;
  message: string;
  toolEvents: AgentToolEvent[];
  progressEvents: AgentProgressEvent[];
  result?: AgentResultData;
  autonomous: boolean;
  approvals: AgentApprovalRequest[];
};

export const AGENT_PROMPT_MAX_CHARS = 64_000;
const AGENT_POLL_INTERVAL_MS = 1_000;
const AGENT_POLL_TIMEOUT_MS = 20 * 60 * 1_000;

function isAgentFailureStatus(status: unknown): boolean {
  return ["error", "failed"].includes(String(status));
}

function agentError(payload: AgentJobPayload, response: Response): AgentSubmissionResult {
  const message =
    typeof payload.detail === "string"
      ? payload.detail
      : typeof payload.message === "string"
        ? payload.message
        : `The agent request failed (${response.status}).`;
  return { status: "error", message };
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
  };
}

export async function fetchStudioAgentResult(jobId: string): Promise<AgentResultData | null> {
  const response = await studioFetch(`/api/studio/agent/${encodeURIComponent(jobId)}`, {
    cache: "no-store",
  });
  const payload = (await response.json().catch(() => ({}))) as AgentJobPayload;
  if (!response.ok || !payload.result) {
    return null;
  }
  const completed = completedAgentResult(payload);
  return completed.status === "completed" ? completed.result : null;
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
  const response = await studioFetch("/api/studio/agent", {
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
): Promise<AgentProgress> {
  const response = await studioFetch(
    `/api/studio/agent/${encodeURIComponent(jobId)}/approvals/${encodeURIComponent(callId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    },
  );
  const payload = (await response.json().catch(() => ({}))) as AgentJobPayload;
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || `approval ${response.status}`);
  }
  return agentProgress(payload);
}
