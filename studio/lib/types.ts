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

type CreditLedgerEntry = {
  id: string;
  delta: number;
  reason: string;
  reference_id: string | null;
  created_at: number;
};

export type SubscriptionState = {
  plan_id: string;
  status: "active" | "past_due";
  monthly_budget_cents: number;
  daily_allowance_cents: number;
  daily_allowance_remaining_cents: number;
  current_period_end: number | null;
};

export type StudioAccount = {
  balance_cents: number;
  recent_ledger: CreditLedgerEntry[];
  // Nullable/optional: deploy-skew safety against an older backend that
  // doesn't send this field yet.
  subscription?: SubscriptionState | null;
};

export type TopUpPack = {
  id: string;
  label: string;
  price_usd_cents: number;
};

export type SubscriptionPlan = {
  id: string;
  label: string;
  price_usd_cents: number;
};

export type StudioAsset = {
  assetId: string;
  versionId: string;
  kind: "image" | "video" | "audio";
  filename: string;
  mimeType: string;
  sizeBytes?: number;
  createdAt?: number;
};

export type FieldOptions = Record<string, Record<string, Array<string | number>>>;
