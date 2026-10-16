/**
 * Resumable browser-direct upload for large footage.
 *
 * The app server only signs part URLs; bytes go straight from the browser to
 * storage. Progress is kept per file (name + size + lastModified) so a dropped
 * connection or a reload resumes after the last part storage already holds.
 */

export type DirectUploadConfig = { enabled: boolean; maxUploadMb: number };

export type DirectUploadDeps = {
  /** Authenticated call to the Renderhaus API (JSON bodies). */
  api: (path: string, body: unknown) => Promise<Response>;
  /** Plain fetch for the signed part URLs. Never sends app credentials. */
  put: (url: string, body: Blob) => Promise<Response>;
  storage?: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null;
  onProgress?: (uploadedBytes: number, totalBytes: number) => void;
  concurrency?: number;
  maxAttempts?: number;
  wait?: (ms: number) => Promise<void>;
};

const BASE = "/api/studio/uploads/direct";
const SIGN_BATCH = 20;

export function parseDirectUploadConfig(health: unknown): DirectUploadConfig {
  const raw = health && typeof health === "object" ? (health as Record<string, unknown>).direct_upload : null;
  if (!raw || typeof raw !== "object") return { enabled: false, maxUploadMb: 0 };
  const record = raw as Record<string, unknown>;
  const max = record.max_upload_mb;
  const valid = typeof max === "number" && Number.isSafeInteger(max) && max > 0;
  return { enabled: record.enabled === true && valid, maxUploadMb: valid ? (max as number) : 0 };
}

export function resumeKey(file: File, projectId: string): string {
  return `renderhaus.upload.${projectId}.${file.name}.${file.size}.${file.lastModified ?? 0}`;
}

class UploadError extends Error {
  constructor(message: string, readonly status = 0) {
    super(message);
  }
}

async function json(response: Response): Promise<Record<string, unknown>> {
  const payload: unknown = await response.json().catch(() => null);
  return payload && typeof payload === "object" && !Array.isArray(payload) ? (payload as Record<string, unknown>) : {};
}

function detailOf(payload: Record<string, unknown>, fallback: string): string {
  return typeof payload.detail === "string" ? payload.detail : fallback;
}

export async function directUpload(file: File, projectId: string, deps: DirectUploadDeps): Promise<Record<string, unknown>> {
  const storage = deps.storage ?? null;
  const wait = deps.wait ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const maxAttempts = deps.maxAttempts ?? 8;
  const concurrency = Math.max(1, deps.concurrency ?? 4);
  const key = resumeKey(file, projectId);

  const call = async (path: string, body: unknown): Promise<Record<string, unknown>> => {
    let response: Response;
    try {
      response = await deps.api(`${BASE}/${path}`, body);
    } catch {
      throw new UploadError("Upload was interrupted. Check your connection and try again.");
    }
    const payload = await json(response);
    if (!response.ok) throw new UploadError(detailOf(payload, "Upload failed. Please try again."), response.status);
    return payload;
  };

  // 1. Resume a saved session if storage still has it, otherwise start one.
  let token = storage?.getItem(key) || "";
  let partSize = 0;
  let partCount = 0;
  const done = new Map<number, string>();
  if (token) {
    try {
      const status = await call("status", { token });
      if (status.completed_asset && typeof status.completed_asset === "object") {
        storage?.removeItem(key);
        deps.onProgress?.(file.size, file.size);
        return status.completed_asset as Record<string, unknown>;
      }
      partSize = Number(status.part_size);
      partCount = Number(status.part_count);
      for (const part of (status.completed_parts as { part_number: number; etag: string }[]) || []) {
        done.set(part.part_number, part.etag);
      }
    } catch (error) {
      if (!(error instanceof UploadError) || ![400, 404, 410].includes(error.status)) throw error;
      storage?.removeItem(key);
      token = "";
      done.clear();
    }
  }
  if (!token) {
    const created = await call("create", {
      project_id: projectId,
      filename: file.name,
      size_bytes: file.size,
      content_type: file.type || null,
    });
    token = String(created.token);
    partSize = Number(created.part_size);
    partCount = Number(created.part_count);
    storage?.setItem(key, token);
  }

  const partBytes = (n: number) => Math.min(partSize, file.size - (n - 1) * partSize);
  let uploaded = 0;
  for (const n of done.keys()) uploaded += partBytes(n);
  deps.onProgress?.(uploaded, file.size);

  // 2. Upload the remaining parts with bounded concurrency and retries.
  const pending: number[] = [];
  for (let n = 1; n <= partCount; n += 1) if (!done.has(n)) pending.push(n);
  const urls = new Map<number, string>();
  const sign = async (numbers: number[]) => {
    const signed = await call("sign-parts", { token, part_numbers: numbers });
    for (const [n, url] of Object.entries((signed.urls as Record<string, string>) || {})) urls.set(Number(n), url);
  };

  const queue = [...pending];
  const uploadPart = async (n: number) => {
    for (let attempt = 1; ; attempt += 1) {
      try {
        if (!urls.has(n)) await sign([n, ...queue.filter((p) => !urls.has(p))].slice(0, SIGN_BATCH));
        const start = (n - 1) * partSize;
        const response = await deps.put(urls.get(n) as string, file.slice(start, start + partBytes(n)));
        if (response.status === 403) {
          urls.delete(n); // signed URL expired: re-sign and retry
          throw new UploadError("expired", 403);
        }
        if (!response.ok) throw new UploadError("part failed", response.status);
        const etag = response.headers.get("ETag");
        if (!etag) throw new UploadError("Upload failed. Please try again.");
        done.set(n, etag);
        uploaded += partBytes(n);
        deps.onProgress?.(uploaded, file.size);
        return;
      } catch (error) {
        if (attempt >= maxAttempts) {
          throw new UploadError("Upload paused. Check your connection and try again; it will resume where it stopped.");
        }
        // Offline: wait for the connection to come back instead of burning retries.
        if (typeof navigator !== "undefined" && navigator.onLine === false && typeof window !== "undefined") {
          await new Promise<void>((resolve) => window.addEventListener("online", () => resolve(), { once: true }));
          attempt -= 1;
          continue;
        }
        await wait(Math.min(30_000, 500 * 2 ** (attempt - 1)));
      }
    }
  };

  await Promise.all(
    Array.from({ length: Math.min(concurrency, queue.length) }, async () => {
      while (queue.length) await uploadPart(queue.shift() as number);
    }),
  );

  // 3. Finish. The server checks storage's own part list before completing.
  const parts = [...done.entries()].sort((a, b) => a[0] - b[0]).map(([part_number, etag]) => ({ part_number, etag }));
  const result = await call("complete", { token, parts });
  storage?.removeItem(key);
  return result;
}
