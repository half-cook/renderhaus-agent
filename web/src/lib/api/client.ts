import {
  ApiError,
  type ApiErrorBody,
  type Config,
  type GenerationRequest,
  type Job,
  type MeResponse,
  type Production,
  type ProductionApproveRequest,
  type ProductionCreateRequest,
  type Project,
  type ProjectCreateRequest,
  type ProjectUpdateRequest,
  type RefinementRequest,
  type TimelineItemModel,
  type UploadResponse,
} from "./types";

// Backend (server/app.py) sends no CORS headers -- requests must stay
// same-origin, satisfied by web/next.config.ts's /api/* rewrite. See
// server/auth.py: every route below except getConfig/getMe requires
// Authorization: Bearer <clerk-session-jwt> when Clerk is enabled.

function errorMessage(body: unknown, status: number, statusText: string): string {
  const payload = body as ApiErrorBody | null;
  const detail = payload?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.msg)
      .filter((msg): msg is string => typeof msg === "string")
      .join("; ") || `Request failed (${status}).`;
  }
  return statusText || `Request failed (${status}).`;
}

async function request<T>(
  path: string,
  init: RequestInit,
  getToken: () => Promise<string | null>,
): Promise<T> {
  const token = await getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, { ...init, headers });

  if (response.status === 204) return undefined as T;

  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(errorMessage(body, response.status, response.statusText), response.status);
  }
  return body as T;
}

function json(body: unknown): RequestInit {
  return { body: JSON.stringify(body) };
}

export type GetToken = () => Promise<string | null>;

// One function per endpoint. Every function takes getToken last so call
// sites read naturally: apiFn(...args, getToken). useApiClient() (below,
// in useApiClient.ts) binds getToken once per component instead of
// threading it through every call site.

export const getConfig = (getToken: GetToken) =>
  request<Config>("/api/config", { method: "GET" }, getToken);

export const getMe = (getToken: GetToken) =>
  request<MeResponse>("/api/me", { method: "GET" }, getToken);

export const uploadReferenceAsset = (file: File, getToken: GetToken) => {
  const formData = new FormData();
  formData.append("file", file);
  return request<UploadResponse>("/api/uploads", { method: "POST", body: formData }, getToken);
};

export const createGeneration = (body: GenerationRequest, getToken: GetToken) =>
  request<Job>("/api/generations", { method: "POST", ...json(body) }, getToken);

export const listGenerations = (
  params: { project_id?: string; unassigned?: boolean },
  getToken: GetToken,
) => {
  const search = new URLSearchParams();
  if (params.project_id) search.set("project_id", params.project_id);
  if (params.unassigned) search.set("unassigned", "true");
  const qs = search.toString();
  return request<{ items: Job[] }>(`/api/generations${qs ? `?${qs}` : ""}`, { method: "GET" }, getToken);
};

export const getGeneration = (jobId: string, getToken: GetToken) =>
  request<Job>(`/api/generations/${jobId}`, { method: "GET" }, getToken);

export const refineGeneration = (jobId: string, body: RefinementRequest, getToken: GetToken) =>
  request<Job>(`/api/generations/${jobId}/refine`, { method: "POST", ...json(body) }, getToken);

export const createProject = (body: ProjectCreateRequest, getToken: GetToken) =>
  request<Project>("/api/projects", { method: "POST", ...json(body) }, getToken);

export const listProjects = (getToken: GetToken) =>
  request<{ items: Project[] }>("/api/projects", { method: "GET" }, getToken);

export const getProject = (projectId: string, getToken: GetToken) =>
  request<Project>(`/api/projects/${projectId}`, { method: "GET" }, getToken);

export const updateProject = (projectId: string, body: ProjectUpdateRequest, getToken: GetToken) =>
  request<Project>(`/api/projects/${projectId}`, { method: "PATCH", ...json(body) }, getToken);

export const deleteProject = (projectId: string, getToken: GetToken) =>
  request<void>(`/api/projects/${projectId}`, { method: "DELETE" }, getToken);

export const addProjectArtifact = (projectId: string, jobId: string, getToken: GetToken) =>
  request<{ project: Project; job: Job }>(
    `/api/projects/${projectId}/artifacts`,
    { method: "POST", ...json({ job_id: jobId }) },
    getToken,
  );

export const removeProjectArtifact = (projectId: string, jobId: string, getToken: GetToken) =>
  request<{ project: Project }>(
    `/api/projects/${projectId}/artifacts/${jobId}`,
    { method: "DELETE" },
    getToken,
  );

// Kept for backend snapshot-sync (decision #1 in the plan) -- not wired to
// any visible UI yet.
export const putProjectTimeline = (
  projectId: string,
  items: TimelineItemModel[],
  getToken: GetToken,
) =>
  request<Project>(
    `/api/projects/${projectId}/timeline`,
    { method: "PUT", ...json({ items }) },
    getToken,
  );

export const mergeProject = (projectId: string, getToken: GetToken) =>
  request<{ project: Project; job: Job }>(
    `/api/projects/${projectId}/merge`,
    { method: "POST" },
    getToken,
  );

export const createProduction = (body: ProductionCreateRequest, getToken: GetToken) =>
  request<Production>("/api/productions", { method: "POST", ...json(body) }, getToken);

export const listProductions = (getToken: GetToken) =>
  request<{ items: Production[] }>("/api/productions", { method: "GET" }, getToken);

export const getProduction = (productionId: string, getToken: GetToken) =>
  request<Production>(`/api/productions/${productionId}`, { method: "GET" }, getToken);

export const deleteProduction = (productionId: string, getToken: GetToken) =>
  request<void>(`/api/productions/${productionId}`, { method: "DELETE" }, getToken);

export const planProduction = (productionId: string, getToken: GetToken) =>
  request<Production>(`/api/productions/${productionId}/commands/plan`, { method: "POST" }, getToken);

export const approveProductionPlan = (
  productionId: string,
  body: ProductionApproveRequest,
  getToken: GetToken,
) =>
  request<Production>(
    `/api/productions/${productionId}/commands/approve-plan`,
    { method: "POST", ...json(body) },
    getToken,
  );
