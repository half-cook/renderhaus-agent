export type { AgentToolEvent } from "./canvas/types";
import type { FieldOptions, ProviderCatalog, StudioAsset, StudioStatus } from "./types";
import type { AgentResultData, AgentToolEvent, CreativeNodeKind } from "./canvas/types";
import { parseAGUIEventStream } from "./ag-ui";
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
  status: string;
  message: string;
  title?: string;
  summary?: string;
  primaryAsset?: StudioAsset;
  updatedAt?: number;
};

export async function fetchStudioExecutions(limit = 20): Promise<StudioExecution[]> {
  const response = await studioFetch(`/api/studio/agent?limit=${limit}`, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `agent jobs ${response.status}`);
  }
  return (Array.isArray(payload.items) ? payload.items : []).map((value: unknown) => {
    const item = value as Record<string, unknown>;
    const result = (item.result || {}) as Record<string, unknown>;
    return {
      jobId: String(item.job_id || ""),
      projectId: typeof item.project_id === "string" ? item.project_id : undefined,
      status: String(item.status || "unknown"),
      message: String(item.message || ""),
      title: typeof result.title === "string" ? result.title : undefined,
      summary: typeof result.summary === "string" ? result.summary : undefined,
      primaryAsset: studioAsset(result.primary_asset) || undefined,
      updatedAt: typeof item.updated_at === "number" ? item.updated_at : undefined,
    };
  });
}

export type AgentComposerResult =
  | { status: "completed"; message: string; result: AgentResultData }
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
  status?: string;
  message?: string;
  detail?: string;
  result?: Record<string, unknown>;
};

const AGENT_POLL_INTERVAL_MS = 1_000;
const AGENT_POLL_TIMEOUT_MS = 20 * 60 * 1_000;

function agentError(payload: AgentJobPayload, response: Response): AgentComposerResult {
  const message =
    typeof payload.detail === "string"
      ? payload.detail
      : typeof payload.message === "string"
        ? payload.message
        : `The agent request failed (${response.status}).`;
  return { status: "error", message };
}

function completedAgentResult(payload: AgentJobPayload): AgentComposerResult {
  const value = payload.result || {};
  return {
    status: "completed",
    message: typeof payload.message === "string" ? payload.message : "Added the result to the canvas.",
    result: {
      executionId: typeof payload.job_id === "string" ? payload.job_id : undefined,
      title: String(value.title || "Agent result"),
      summary: String(value.summary || "The agent completed the request."),
      markdown: String(value.markdown || ""),
      filename: String(value.filename || "agent-result.md"),
      mimeType: String(value.mime_type || "text/markdown;charset=utf-8"),
      toolEvents: Array.isArray(value.tool_events)
        ? value.tool_events.map((event) => {
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
              assets: studioAssets(item.assets),
            };
          })
        : [],
      assets: studioAssets(value.assets),
      primaryAsset:
        value.primary_asset && typeof value.primary_asset === "object"
          ? studioAsset(value.primary_asset) || undefined
          : undefined,
      partial: value.partial === true,
    },
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
  onProgress?: (message: string) => void,
): Promise<AgentComposerResult> {
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
    if (typeof payload.message === "string") {
      onProgress?.(payload.message);
    }
    if (payload.status === "completed") {
      return completedAgentResult(payload);
    }
    if (payload.status === "error") {
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

export type StreamAgentCallbacks = {
  onProgress?: (message: string) => void;
  onTextDelta?: (delta: string, fullText: string) => void;
  onToolEvent?: (event: AgentToolEvent) => void;
  onAsset?: (asset: StudioAsset) => void;
  onStateSnapshot?: (snapshot: Record<string, unknown>) => void;
  onRunStarted?: (runId: string, threadId: string) => void;
  onRunFinished?: (runId: string, threadId: string) => void;
  onRunError?: (message: string) => void;
};

function readableToolLabel(name: string): string {
  const label = name.replace("___", " ").replaceAll("_", " ").trim();
  return label ? label[0].toUpperCase() + label.slice(1) : "Tool";
}

function upsertToolEvent(events: AgentToolEvent[], next: AgentToolEvent): void {
  const index = events.findIndex((event) => event.id === next.id);
  if (index >= 0) {
    events[index] = next;
  } else {
    events.push(next);
  }
}

export async function streamAgentPrompt(
  prompt: string,
  projectId: string,
  nodeIds: string[],
  nodes: AgentNodeContext[],
  callbacks?: StreamAgentCallbacks,
): Promise<AgentComposerResult> {
  const response = await studioFetch("/api/studio/agent/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, project_id: projectId, node_ids: nodeIds, nodes }),
  });

  if (!response.ok) {
    const errorPayload = (await response.json().catch(() => ({}))) as AgentJobPayload;
    if ([404, 405, 501].includes(response.status)) {
      throw new Error(
        errorPayload.detail || errorPayload.message || "The AG-UI endpoint is unavailable.",
      );
    }
    return {
      status: "error",
      message: errorPayload.detail || errorPayload.message || `Agent stream request failed (${response.status}).`,
    };
  }

  let accumulatedText = "";
  let finalResult: AgentResultData | null = null;
  const toolEvents: AgentToolEvent[] = [];
  const assets: StudioAsset[] = [];
  let executionId: string | undefined;
  let title = "Agent result";
  let summary = "";
  let filename = "agent-result.md";
  let errorMessage: string | null = null;
  let receivedTerminalEvent = false;

  await parseAGUIEventStream(response, (event) => {
    switch (event.type) {
      case "RUN_STARTED":
        executionId = event.runId;
        callbacks?.onRunStarted?.(event.runId, event.threadId);
        callbacks?.onProgress?.("Agent started run...");
        break;
      case "STEP_STARTED":
        {
          const stepEvent: AgentToolEvent = {
            id: `step:${event.stepName}`,
            name: event.stepName,
            label: event.stepName,
            status: "running",
            summary: event.stepName,
            assets: [],
          };
          upsertToolEvent(toolEvents, stepEvent);
          callbacks?.onToolEvent?.(stepEvent);
        }
        callbacks?.onProgress?.(event.stepName);
        break;
      case "STEP_FINISHED":
        {
          const current = toolEvents.find((item) => item.id === `step:${event.stepName}`);
          const stepEvent: AgentToolEvent = {
            id: `step:${event.stepName}`,
            name: event.stepName,
            label: event.stepName,
            status: "completed",
            summary: current?.summary || event.stepName,
            assets: [],
          };
          upsertToolEvent(toolEvents, stepEvent);
          callbacks?.onToolEvent?.(stepEvent);
        }
        break;
      case "TEXT_MESSAGE_CONTENT":
        accumulatedText += event.delta;
        callbacks?.onTextDelta?.(event.delta, accumulatedText);
        break;
      case "TOOL_CALL_START":
        {
          const current = toolEvents.find((item) => item.id === event.toolCallId);
          const toolEvent: AgentToolEvent = {
            id: event.toolCallId,
            name: event.toolCallName,
            label: readableToolLabel(event.toolCallName),
            status: "running",
            summary: `Invoking ${readableToolLabel(event.toolCallName)}.`,
            assets: current?.assets || [],
          };
          upsertToolEvent(toolEvents, toolEvent);
          callbacks?.onToolEvent?.(toolEvent);
        }
        callbacks?.onProgress?.(`Invoking ${event.toolCallName.replace("___", " ")}...`);
        break;
      case "CUSTOM":
        if (event.name === "renderhaus_tool_event" && event.value && typeof event.value === "object") {
          const item = event.value as Record<string, unknown>;
          const toolEv: AgentToolEvent = {
            id: String(item.id || crypto.randomUUID()),
            name: String(item.name || "tool"),
            label: String(item.label || "Tool"),
            status: String(item.status || "completed"),
            summary: String(item.summary || ""),
            provider: typeof item.provider === "string" ? item.provider : undefined,
            providerJobId: typeof item.provider_job_id === "string" ? item.provider_job_id : undefined,
            assets: studioAssets(item.assets),
          };
          upsertToolEvent(toolEvents, toolEv);
          callbacks?.onToolEvent?.(toolEv);
          callbacks?.onProgress?.(toolEv.summary || `${toolEv.label} completed`);
        } else if (event.name === "renderhaus_asset" && event.value && typeof event.value === "object") {
          const ast = studioAsset(event.value);
          if (ast) {
            if (!assets.some((asset) => asset.versionId === ast.versionId)) {
              assets.push(ast);
              callbacks?.onAsset?.(ast);
            }
          }
        }
        break;
      case "STATE_SNAPSHOT":
        receivedTerminalEvent = true;
        if (event.snapshot) {
          const snap = event.snapshot;
          title = String(snap.title || title);
          summary = String(snap.summary || summary);
          filename = String(snap.filename || filename);
          if (typeof snap.markdown === "string" && snap.markdown) {
            accumulatedText = snap.markdown;
          }
          if (Array.isArray(snap.assets)) {
            const parsedAssets = studioAssets(snap.assets);
            for (const ast of parsedAssets) {
              if (!assets.some((a) => a.versionId === ast.versionId)) {
                assets.push(ast);
                callbacks?.onAsset?.(ast);
              }
            }
          }
          if (Array.isArray(snap.tool_events)) {
            const protocolSteps = toolEvents.filter((item) => item.id.startsWith("step:"));
            toolEvents.length = 0;
            toolEvents.push(...protocolSteps);
            for (const item of snap.tool_events) {
              const rec = item as Record<string, unknown>;
              const toolEvent: AgentToolEvent = {
                id: String(rec.id || crypto.randomUUID()),
                name: String(rec.name || "tool"),
                label: String(rec.label || "Tool"),
                status: String(rec.status || "completed"),
                summary: String(rec.summary || ""),
                provider: typeof rec.provider === "string" ? rec.provider : undefined,
                providerJobId: typeof rec.provider_job_id === "string" ? rec.provider_job_id : undefined,
                assets: studioAssets(rec.assets),
              };
              toolEvents.push(toolEvent);
              callbacks?.onToolEvent?.(toolEvent);
            }
          }
          callbacks?.onStateSnapshot?.(snap);
        }
        break;
      case "RUN_ERROR":
        errorMessage = event.message || "Agent execution encountered an error.";
        callbacks?.onRunError?.(errorMessage);
        break;
      case "TEXT_MESSAGE_START":
      case "TEXT_MESSAGE_END":
      case "TOOL_CALL_ARGS":
      case "TOOL_CALL_END":
      case "TOOL_CALL_RESULT":
      case "STATE_DELTA":
        break;
      case "RUN_FINISHED":
        receivedTerminalEvent = true;
        callbacks?.onRunFinished?.(event.runId, event.threadId);
        break;
      default: {
        const _exhaustiveCheck: never = event;
        void _exhaustiveCheck;
        break;
      }
    }
  });

  if (errorMessage) {
    return {
      status: "error",
      message: errorMessage,
    };
  }

  if (!receivedTerminalEvent) {
    if (executionId) {
      callbacks?.onProgress?.("Live events ended early; continuing with job status updates...");
      return waitForAgentJob(executionId, callbacks?.onProgress);
    }
    return {
      status: "error",
      message: "The agent stream ended before reporting a terminal state.",
    };
  }

  finalResult = {
    executionId,
    title,
    summary: summary || accumulatedText.slice(0, 200),
    markdown: accumulatedText,
    filename,
    mimeType: "text/markdown;charset=utf-8",
    toolEvents,
    assets,
    primaryAsset: assets.at(-1),
  };

  return {
    status: "completed",
    message: `Completed: ${title}`,
    result: finalResult,
  };
}

export async function submitAgentPrompt(
  prompt: string,
  projectId: string,
  nodeIds: string[],
  nodes: AgentNodeContext[],
  onProgress?: (message: string) => void,
  onTextDelta?: (delta: string, fullText: string) => void,
  callbacks?: StreamAgentCallbacks,
): Promise<AgentComposerResult> {
  let streamStarted = false;
  try {
    return await streamAgentPrompt(prompt, projectId, nodeIds, nodes, {
      ...callbacks,
      onProgress,
      onTextDelta,
      onRunStarted: (runId, threadId) => {
        streamStarted = true;
        callbacks?.onRunStarted?.(runId, threadId);
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "The AG-UI stream disconnected.";
    if (streamStarted) {
      callbacks?.onRunError?.(message);
      return { status: "error", message };
    }
    onProgress?.("Live events unavailable; continuing with job status updates...");
  }

  const response = await studioFetch("/api/studio/agent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, project_id: projectId, node_ids: nodeIds, nodes }),
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
  callbacks?.onRunStarted?.(payload.job_id, projectId);
  onProgress?.(payload.message || "Agent job queued.");
  const result = await waitForAgentJob(payload.job_id, onProgress);
  if (result.status === "completed") {
    callbacks?.onRunFinished?.(payload.job_id, projectId);
  } else {
    callbacks?.onRunError?.(result.message);
  }
  return result;
}
