import type { FieldOptions, ProviderCatalog, StudioAsset, StudioStatus } from "./types";
import type { AgentResultData, CreativeNodeKind } from "./canvas/types";

export async function fetchStatus(): Promise<StudioStatus> {
  const response = await fetch("/api/studio/status");
  if (!response.ok) {
    throw new Error(`status ${response.status}`);
  }
  return response.json();
}

export async function fetchTools(): Promise<ProviderCatalog[]> {
  const response = await fetch("/api/studio/tools");
  if (!response.ok) {
    throw new Error(`tools ${response.status}`);
  }
  const payload = await response.json();
  return payload.providers;
}

export async function fetchOptions(): Promise<FieldOptions> {
  const response = await fetch("/api/studio/options");
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
): Promise<{ result: unknown; assets: StudioAsset[] }> {
  const response = await fetch("/api/studio/invoke", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, tool, arguments: arguments_ }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `invoke ${response.status}`);
  }
  return {
    result: payload.result,
    assets: Array.isArray(payload.assets) ? payload.assets : [],
  };
}

export async function uploadStudioFile(
  file: File,
): Promise<{ kind: StudioAsset["kind"]; url: string; path: string; filename: string }> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/studio/upload", { method: "POST", body });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `upload ${response.status}`);
  }
  return payload;
}

export type AgentComposerResult =
  | { status: "completed"; message: string; result: AgentResultData }
  | { status: "error"; message: string };

export type AgentNodeContext = {
  id: string;
  title: string;
  kind: CreativeNodeKind;
  prompt: string;
  output_url?: string;
  local_path?: string;
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
      title: String(value.title || "Agent result"),
      summary: String(value.summary || "The agent completed the request."),
      markdown: String(value.markdown || ""),
      filename: String(value.filename || "agent-result.md"),
      mimeType: String(value.mime_type || "text/markdown;charset=utf-8"),
      toolEvents: Array.isArray(value.tool_events) ? value.tool_events : [],
      assets: Array.isArray(value.assets) ? value.assets : [],
    },
  };
}

async function waitForAgentJob(
  jobId: string,
  onProgress?: (message: string) => void,
): Promise<AgentComposerResult> {
  const deadline = Date.now() + AGENT_POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, AGENT_POLL_INTERVAL_MS));
    const response = await fetch(`/api/studio/agent/${encodeURIComponent(jobId)}`, {
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
      return {
        status: "error",
        message: payload.message || "The agent could not finish this request.",
      };
    }
  }
  return {
    status: "error",
    message: "The agent is still running. Refresh the canvas and try again shortly.",
  };
}

export async function submitAgentPrompt(
  prompt: string,
  nodeIds: string[],
  nodes: AgentNodeContext[],
  onProgress?: (message: string) => void,
): Promise<AgentComposerResult> {
  const response = await fetch("/api/studio/agent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, node_ids: nodeIds, nodes }),
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
  onProgress?.(payload.message || "Agent job queued.");
  return waitForAgentJob(payload.job_id, onProgress);
}
