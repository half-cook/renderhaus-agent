import type { ProviderCatalog, StudioAsset, ToolSchema } from "@/lib/types";

export type CreativeNodeKind =
  | "text"
  | "image"
  | "video"
  | "audio"
  | "generator"
  | "storyboard"
  | "agentResult"
  | "agentRun";

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
  | "agent"
  | "ascii";

export type DockPosition = "top" | "bottom" | "left" | "right" | "free";

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
  id: string;
  name: string;
  label: string;
  status: string;
  summary: string;
  provider?: string;
  providerJobId?: string;
  assets: StudioAsset[];
};

export type AgentResultData = {
  executionId?: string;
  title: string;
  summary: string;
  markdown: string;
  filename: string;
  mimeType: string;
  toolEvents: AgentToolEvent[];
  assets: StudioAsset[];
  primaryAsset?: StudioAsset;
  partial?: boolean;
};

export type AgentRunData = AgentResultData & {
  executionId?: string;
  artifactNodeIds: string[];
  primaryNodeId?: string;
  /** Compatibility with run ledgers created before primary results could be non-video. */
  finalNodeId?: string;
  collapsed: boolean;
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
  agentRun?: AgentRunData;
  agentRunId?: string;
  agentRole?: "artifact" | "primary" | "final";
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
