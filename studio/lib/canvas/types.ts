import type { ProviderCatalog, StudioAsset, ToolSchema } from "@/lib/types";

export type CreativeNodeKind =
  | "text"
  | "image"
  | "video"
  | "audio"
  | "generator"
  | "storyboard"
  | "agentResult";

export type PortDataType = "text" | "image" | "video" | "audio";

export type JobStatus = "idle" | "queued" | "running" | "completed" | "failed";

export type RailTool =
  | "select"
  | "hand"
  | "upload"
  | "text"
  | "image"
  | "video"
  | "audio"
  | "voice"
  | "storyboard"
  | "agent";

export type PortDefinition = {
  id: string;
  label: string;
  dataType: PortDataType;
  targetField?: string;
  required?: boolean;
};

export type ToolDefinition = {
  id: string;
  displayName: string;
  description?: string;
  category: CreativeNodeKind;
  providerId: string;
  toolName: string;
  inputPorts: PortDefinition[];
  outputPorts: PortDefinition[];
  primaryFields: string[];
  pollTool?: string;
};

export type AgentToolEvent = {
  name: string;
  label: string;
  status: string;
  summary: string;
};

export type AgentResultData = {
  title: string;
  summary: string;
  markdown: string;
  filename: string;
  mimeType: string;
  toolEvents: AgentToolEvent[];
  assets: StudioAsset[];
};

export type CanvasNodeData = {
  kind: CreativeNodeKind;
  title: string;
  toolId?: string;
  providerId?: string;
  toolName?: string;
  config: Record<string, unknown>;
  output?: StudioAsset;
  variants?: StudioAsset[];
  result?: unknown;
  status: JobStatus;
  error?: string;
  jobId?: string;
  approved?: boolean;
  storyOrder?: number;
  agentResult?: AgentResultData;
};

export type CanvasEdgeData = {
  dataType: PortDataType;
  targetField: string;
};

export type ProjectRecord = {
  id: string;
  name: string;
};

export function schemaFor(
  providers: ProviderCatalog[],
  providerId: string | undefined,
  toolName: string | undefined,
): ToolSchema | undefined {
  if (!providerId || !toolName) {
    return undefined;
  }
  const provider = providers.find((item) => item.id === providerId);
  return provider?.tools.find((tool) => tool.name === toolName);
}
