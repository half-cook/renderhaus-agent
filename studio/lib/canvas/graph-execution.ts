import { invokeTool } from "@/lib/api";
import { studioAssetHandle } from "@/lib/assets";
import type { StudioAsset } from "@/lib/types";
import type { CanvasEdge } from "./connection-validation";
import type { CanvasNode } from "./connection-validation";
import { toolById } from "./tool-registry";
import type { CanvasNodeData, PortDataType } from "./types";

const TERMINAL = new Set([
  "succeeded",
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

export function outputValue(node: CanvasNode, dataType: PortDataType): unknown {
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

export function resolveConfig(node: CanvasNode, nodes: CanvasNode[], edges: CanvasEdge[]): Record<string, unknown> {
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

export async function runCreativeNode(
  node: CanvasNode,
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  projectId: string,
  invoke: typeof invokeTool = invokeTool,
): Promise<Partial<CanvasNodeData>> {
  const tool = toolById(node.data.toolId);
  if (!tool) {
    throw new Error("This node has no generation tool.");
  }
  const arguments_ = resolveConfig(node, nodes, edges);
  const sourceVersionIds = edges
    .filter((edge) => edge.target === node.id)
    .map((edge) => nodes.find((candidate) => candidate.id === edge.source)?.data.output?.versionId)
    .filter((value): value is string => Boolean(value));
  const payload = await invoke(tool.providerId, tool.toolName, arguments_, {
    projectId,
    assetId: node.data.output?.assetId,
    sourceVersionIds,
  });
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
  if (providerStatus && FAILED.has(providerStatus)) {
    return {
      status: "failed",
      result: payload.result,
      jobId,
      output: undefined,
      variants: assets,
      error: "Generation failed.",
    };
  }
  if (jobId && tool.pollTool && providerStatus !== "dry_run") {
    return {
      status: "queued",
      result: payload.result,
      jobId,
      error: undefined,
    };
  }
  return {
    status: "completed",
    result: payload.result,
    jobId,
    output: undefined,
    variants: assets,
    error: undefined,
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
    { projectId, assetId: node.data.output?.assetId },
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
  if (FAILED.has(providerStatus)) {
    return { status: "failed", result: payload.result, error: "Generation failed." };
  }
  if (TERMINAL.has(providerStatus)) {
    return { status: "completed", result: payload.result };
  }
  return { status: "running", result: payload.result };
}
