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
