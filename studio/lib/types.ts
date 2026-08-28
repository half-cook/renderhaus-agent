export type JsonSchema = {
  type?: string;
  enum?: Array<string | number | boolean>;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
};

export type ToolSchema = {
  name: string;
  description: string;
  inputSchema: JsonSchema;
};

export type ProviderCatalog = {
  id: string;
  name: string;
  function_name: string;
  tools: ToolSchema[];
};

export type StudioStatus = {
  mode: string;
  agent: boolean;
  dry_run: Record<string, boolean>;
};

export type NodeStatus = "idle" | "running" | "ok" | "error";

export type StudioAsset = {
  assetId: string;
  versionId: string;
  kind: "image" | "video" | "audio";
  filename: string;
  mimeType: string;
  sizeBytes?: number;
  createdAt?: number;
};

export type ToolNode = {
  id: string;
  providerId: string;
  providerName: string;
  tool: ToolSchema;
  x: number;
  y: number;
  args: Record<string, unknown>;
  status: NodeStatus;
  result: unknown;
  assets: StudioAsset[];
  error: string | null;
};

export type FieldOptions = Record<string, Record<string, Array<string | number>>>;

export type Viewport = {
  x: number;
  y: number;
  zoom: number;
};
