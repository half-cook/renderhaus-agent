import type { FieldOptions, ProviderCatalog, StudioAsset, StudioStatus } from "./types";

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

export type InvokeLedger = { projectId: string; nodeId: string; idempotencyKey: string };

export async function invokeTool(
  provider: string,
  tool: string,
  arguments_: Record<string, unknown>,
  // Present on a submit call, omitted on a poll call -- see server/studio.py's
  // InvokeBody docstring for why poll must NOT send an idempotency key.
  ledger?: InvokeLedger,
): Promise<{ result: unknown; assets: StudioAsset[] }> {
  const response = await fetch("/api/studio/invoke", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider,
      tool,
      arguments: arguments_,
      ...(ledger
        ? {
            project_id: ledger.projectId,
            node_id: ledger.nodeId,
            idempotency_key: ledger.idempotencyKey,
          }
        : {}),
    }),
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
  | { status: "unavailable"; message: string }
  | { status: "error"; message: string };

export async function submitAgentPrompt(prompt: string, nodeIds: string[]): Promise<AgentComposerResult> {
  const response = await fetch("/api/studio/agent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, node_ids: nodeIds }),
  });
  const payload = await response.json().catch(() => ({}));
  const detail = typeof payload.detail === "string" ? payload.detail : "The agent could not run.";
  if (response.status === 501) {
    return { status: "unavailable", message: detail };
  }
  return { status: "error", message: detail };
}
