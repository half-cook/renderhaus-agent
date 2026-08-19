import { invokeTool } from "@/lib/api";
import type { CanvasEdge } from "./connection-validation";
import type { CanvasNode } from "./connection-validation";
import { toolById } from "./tool-registry";
import type { CanvasNodeData, PortDataType } from "./types";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "canceled", "deleted", "dry_run"]);

export function outputValue(node: CanvasNode, dataType: PortDataType): unknown {
  switch (dataType) {
    case "text": {
      const prompt = node.data.config.prompt ?? node.data.config.text ?? node.data.config.script;
      return typeof prompt === "string" && prompt.trim() ? prompt : node.data.title;
    }
    case "image":
    case "video":
    case "audio":
      return node.data.output?.url || node.data.variants?.[0]?.url;
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
): Promise<Partial<CanvasNodeData>> {
  const tool = toolById(node.data.toolId);
  if (!tool) {
    throw new Error("This node has no generation tool.");
  }
  const arguments_ = resolveConfig(node, nodes, edges);
  const payload = await invokeTool(tool.providerId, tool.toolName, arguments_);
  const assets = payload.assets;
  const jobId = jobIdFrom(payload.result);
  const providerStatus = statusFrom(payload.result);
  if (assets.length > 0) {
    return {
      status: "completed",
      output: assets[0],
      variants: assets,
      result: payload.result,
      error: undefined,
      jobId,
    };
  }
  if (jobId && tool.pollTool && providerStatus !== "dry_run") {
    return {
      status: "queued",
      result: payload.result,
      jobId,
      error: undefined,
      output: undefined,
      variants: [],
    };
  }
  return {
    status: providerStatus === "failed" ? "failed" : "completed",
    result: payload.result,
    jobId,
    output: undefined,
    variants: assets,
    error: providerStatus === "failed" ? "Generation failed." : undefined,
  };
}

export async function pollCreativeNode(node: CanvasNode): Promise<Partial<CanvasNodeData> | null> {
  const tool = toolById(node.data.toolId);
  if (!tool?.pollTool || !node.data.jobId || !node.data.providerId) {
    return null;
  }
  const payload = await invokeTool(node.data.providerId, tool.pollTool, {
    job_id: node.data.jobId,
    download: true,
  });
  const providerStatus = statusFrom(payload.result) || "unknown";
  if (payload.assets.length > 0) {
    return {
      status: "completed",
      output: payload.assets[0],
      variants: payload.assets,
      result: payload.result,
      error: undefined,
    };
  }
  if (providerStatus === "failed" || providerStatus === "cancelled" || providerStatus === "canceled") {
    return { status: "failed", result: payload.result, error: "Generation failed." };
  }
  if (TERMINAL.has(providerStatus)) {
    return { status: "completed", result: payload.result };
  }
  return { status: "running", result: payload.result };
}
