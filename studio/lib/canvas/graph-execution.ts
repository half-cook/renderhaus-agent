import { invokeTool, type ToolInvocationOptions } from "@/lib/api";
import { studioAssetHandle } from "@/lib/assets";
import type { StudioAsset } from "@/lib/types";
import type { CanvasEdge } from "./connection-validation";
import type { CanvasNode } from "./connection-validation";
import { toolById } from "./tool-registry";
import type { CanvasNodeData, PortDataType } from "./types";

const TERMINAL = new Set([
  "succeeded",
  "completed",
  "success",
  "failed",
  "cancelled",
  "canceled",
  "deleted",
  "expired",
  "timeout",
  "timed_out",
  "timeouted",
  "dry_run",
]);

const FAILED = new Set([
  "failed",
  "error",
  "blocked",
  "not_run",
  "cancelled",
  "canceled",
  "deleted",
  "expired",
  "timeout",
  "timed_out",
  "timeouted",
]);

function mergeVariants(existing: StudioAsset[] | undefined, incoming: StudioAsset[]): StudioAsset[] {
  const merged = [...(existing || [])];
  for (const asset of incoming) {
    if (!merged.some((item) => item.versionId === asset.versionId)) {
      merged.push(asset);
    }
  }
  return merged;
}

function outputValue(node: CanvasNode, dataType: PortDataType): unknown {
  switch (dataType) {
    case "text": {
      const prompt =
        node.data.agentResult?.markdown ??
        node.data.config.prompt ??
        node.data.config.text ??
        node.data.config.script;
      return typeof prompt === "string" && prompt.trim() ? prompt : node.data.title;
    }
    case "image":
    case "video":
    case "audio":
      return node.data.output
        ? studioAssetHandle(node.data.output)
        : node.data.variants?.[0]
          ? studioAssetHandle(node.data.variants[0])
          : undefined;
    default: {
      const exhaustive: never = dataType;
      return exhaustive;
    }
  }
}

function resolveConfig(node: CanvasNode, nodes: CanvasNode[], edges: CanvasEdge[]): Record<string, unknown> {
  const next = { ...node.data.config };
  for (const edge of edges) {
    if (edge.target !== node.id) {
      continue;
    }
    const source = nodes.find((item) => item.id === edge.source);
    const field = edge.data?.targetField;
    const dataType = edge.data?.dataType;
    if (!source || !field || !dataType) {
      continue;
    }
    const value = outputValue(source, dataType);
    if (value !== undefined && value !== null && value !== "") {
      next[field] = value;
    }
  }
  return next;
}

function jobIdFrom(result: unknown): string | undefined {
  if (!result || typeof result !== "object") {
    return undefined;
  }
  const record = result as Record<string, unknown>;
  if (typeof record.job_id === "string" && record.job_id) {
    return record.job_id;
  }
  return undefined;
}

function statusFrom(result: unknown): string | undefined {
  if (!result || typeof result !== "object") {
    return undefined;
  }
  const status = (result as Record<string, unknown>).status;
  return typeof status === "string" ? status.toLowerCase() : undefined;
}

function failureMessage(result: unknown, status?: string): string {
  if (status === "dry_run") return "Preview mode is enabled. No media was generated.";
  const record = result && typeof result === "object" ? result as Record<string, unknown> : {};
  const reason = record.error ?? record.reason;
  return typeof reason === "string" && reason.trim()
    ? reason.replace(/https?:\/\/\S+/g, "[provider link]").slice(0, 500)
    : "Generation did not produce a saved result.";
}

function hasError(result: unknown): boolean {
  return Boolean(result && typeof result === "object" && (result as Record<string, unknown>).error);
}

export type CreativeNodeRequest = {
  provider: string;
  tool: string;
  arguments: Record<string, unknown>;
  options: ToolInvocationOptions;
};

export function creativeNodeRequest(
  node: CanvasNode,
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  projectId: string,
): CreativeNodeRequest {
  const tool = toolById(node.data.toolId);
  if (!tool) {
    throw new Error("This node has no generation tool.");
  }
  const arguments_ = structuredClone(resolveConfig(node, nodes, edges));
  const sourceVersionIds = edges
    .filter((edge) => edge.target === node.id)
    .map((edge) => nodes.find((candidate) => candidate.id === edge.source)?.data.output?.versionId)
    .filter((value): value is string => Boolean(value));
  return { provider: tool.providerId, tool: tool.toolName, arguments: arguments_,
    options: { projectId, assetId: node.data.output?.assetId, sourceVersionIds } };
}

export async function runCreativeNode(
  node: CanvasNode,
  request: CreativeNodeRequest,
  invoke: typeof invokeTool = invokeTool,
): Promise<Partial<CanvasNodeData>> {
  const tool = toolById(node.data.toolId);
  if (!tool) throw new Error("This node has no generation tool.");
  const sourceVersionIds = request.options.sourceVersionIds;
  const payload = await invoke(request.provider, request.tool, request.arguments, request.options);
  const assets = payload.assets;
  const jobId = jobIdFrom(payload.result);
  const providerStatus = statusFrom(payload.result);
  if (assets.length > 0) {
    const variants = mergeVariants(node.data.variants, assets);
    return {
      status: "completed",
      output: assets[0],
      variants,
      result: payload.result,
      error: undefined,
      jobId,
    };
  }
  if (hasError(payload.result) || (providerStatus && FAILED.has(providerStatus))) {
    return {
      status: "failed",
      result: payload.result,
      jobId,
      error: failureMessage(payload.result, providerStatus),
    };
  }
  if (jobId && tool.pollTool && !TERMINAL.has(providerStatus || "")) {
    return {
      status: "queued",
      sourceVersionIds,
      result: payload.result,
      jobId,
      error: undefined,
    };
  }
  return {
    status: "failed",
    result: payload.result,
    jobId,
    error: failureMessage(payload.result, providerStatus),
  };
}

export async function pollCreativeNode(
  node: CanvasNode,
  projectId: string,
): Promise<Partial<CanvasNodeData> | null> {
  const tool = toolById(node.data.toolId);
  if (!tool?.pollTool || !node.data.jobId || !node.data.providerId) {
    return null;
  }
  const payload = await invokeTool(
    node.data.providerId,
    tool.pollTool,
    {
      job_id: node.data.jobId,
      download: true,
    },
    { projectId, assetId: node.data.output?.assetId, sourceVersionIds: node.data.sourceVersionIds },
  );
  const providerStatus = statusFrom(payload.result) || "unknown";
  if (payload.assets.length > 0) {
    return {
      status: "completed",
      output: payload.assets[0],
      variants: mergeVariants(node.data.variants, payload.assets),
      result: payload.result,
      error: undefined,
    };
  }
  if (hasError(payload.result) || FAILED.has(providerStatus)) {
    return { status: "failed", result: payload.result, error: failureMessage(payload.result, providerStatus) };
  }
  if (TERMINAL.has(providerStatus)) {
    return { status: "failed", result: payload.result, error: failureMessage(payload.result, providerStatus) };
  }
  return { status: "running", result: payload.result };
}
