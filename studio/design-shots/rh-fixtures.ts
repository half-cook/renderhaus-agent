/**
 * Per-screen API fixtures for the revamp screens. Everything here is example data in the exact shape the
 * backend sends (cents as integers; no provider, model or fee fields). Nothing here is a live call.
 */
export const MUG = "demo-matte-mug";
export const MUG_TASK = "task-film";
const NOW = 1791848520; // fixed clock: Mon Oct 12 2026, 7:42 PM America/Toronto

const asset = (id: string, kind: "image" | "video" | "audio", filename: string) => ({
  asset_id: id, version_id: `fx-${id}`, kind, filename, mime_type: kind === "image" ? "image/jpeg" : "video/mp4", size_bytes: 1_200_000, created_at: NOW - 600,
});
export const STILL = asset("still-mug", "image", "still-mug.jpg");
const MACRO = asset("shot-macro", "image", "shot-macro.jpg");
const LIFT = asset("shot-lift", "image", "shot-lift.jpg");

const camel = (a: ReturnType<typeof asset>) => a; // API payload keeps snake_case; the client maps it

const VIDEO_ESTIMATE = {
  estimate_cents: 105, cap_cents: 150,
  lines: [
    { kind: "media", label: "Video clip", detail: "5 s · 720p", price_cents: 65, basis: "fixed" },
    { kind: "orchestration", label: "Agent orchestration", price_cents: 40, basis: "estimate" },
  ],
};

const node = (id: string, type: string, x: number, y: number, data: Record<string, unknown>) => ({
  id, type, position: { x, y }, data: { status: "idle", inputs: [], ...data },
});

export const mugCanvas = {
  revision: 3,
  document: {
    schemaVersion: 2, projectName: "Matte travel mug", viewport: { x: 140, y: 40, zoom: 0.95 },
    nodes: [
      node("n-prompt", "text", 40, 70, { kind: "text", title: "Prompt", config: { prompt: "Create a product photo: a matte-black stainless travel mug on a pale stone counter, soft morning window light, shallow depth of field." } }),
      node("n-still", "image", 400, 40, { kind: "image", title: "Product still", status: "completed", toolId: "image.generate", providerId: "seedance", toolName: "text_to_video", output: { assetId: "still-mug", versionId: "fx-still-mug", kind: "image", filename: "still-mug.jpg", mimeType: "image/jpeg" }, chargedCents: 26, config: { aspect_ratio: "1:1", size: "2K", thumbnail_url: "/beta/still-mug.jpg" } }),
      node("n-shot1", "video", 860, 40, { kind: "video", title: "Shot 1 · push-in", toolId: "video.generate", providerId: "seedance", toolName: "text_to_video", approved: true, storyOrder: 0, estimate: VIDEO_ESTIMATE, output: { assetId: "shot-macro", versionId: "fx-shot-macro", kind: "image", filename: "shot-macro.jpg", mimeType: "image/jpeg" }, config: { prompt: "Slow push-in on the handle and the matte texture. Soft morning window light.", model: "dreamina-seedance-2-5-260628", duration_seconds: 5, aspect_ratio: "16:9", resolution: "720p", trim_in_seconds: 0, trim_out_seconds: 5, thumbnail_url: "/beta/shot-macro.jpg" } }),
      node("n-shot2", "video", 860, 360, { kind: "video", title: "Shot 2 · hand lifts mug", approved: true, storyOrder: 1, output: { assetId: "shot-lift", versionId: "fx-shot-lift", kind: "image", filename: "shot-lift.jpg", mimeType: "image/jpeg" }, config: { duration_seconds: 5, aspect_ratio: "16:9", resolution: "720p", trim_in_seconds: 0, trim_out_seconds: 5, thumbnail_url: "/beta/shot-lift.jpg" } }),
      node("n-voice", "audio", 400, 440, { kind: "audio", title: "Voiceover", chargedCents: 2, config: { voice: "library voice", duration_seconds: 9, text: "A mug made to be held." } }),
    ],
    edges: [
      { id: "e1", source: "n-prompt", target: "n-still", sourceHandle: "text", targetHandle: "prompt", data: { dataType: "text", targetField: "prompt" } },
      { id: "e2", source: "n-still", target: "n-shot1", sourceHandle: "image", targetHandle: "image", data: { dataType: "image", targetField: "image" } },
    ],
  },
};

export const mugTools = {
  providers: [{
    id: "seedance", name: "Studio Video", function_name: "studio_video",
    tools: [{
      name: "text_to_video", description: "Generate a short clip from a prompt.",
      inputSchema: { type: "object", properties: {
        prompt: { type: "string", description: "What happens in the shot." },
        model: { type: "string", enum: ["dreamina-seedance-2-5-260628"] },
        duration_seconds: { type: "integer", enum: [5] },
        aspect_ratio: { type: "string", enum: ["16:9"] },
        resolution: { type: "string", enum: ["720p"] },
      } },
    }],
  }],
};

export const mugProjects = { items: [
  { id: MUG, name: "Matte travel mug", created_at: NOW - 1700, updated_at: NOW - 120 },
  { id: "spring-launch", name: "Spring launch ads", file_count: 3, thumbs: ["/beta/shot-macro.jpg", "/beta/shot-lift.jpg", "/beta/shot-window.jpg"], created_at: NOW - 200000, updated_at: NOW - 180000 },
  { id: "untitled-1", name: "Untitled", created_at: NOW - 400, updated_at: NOW - 300 },
] };

export const mugTasks = { items: [
  { id: MUG_TASK, project_id: MUG, title: "10s product film", status: "active", created_at: NOW - 1500, updated_at: NOW - 60 },
  { id: "task-stills", project_id: MUG, title: "Hero stills", status: "active", created_at: NOW - 3000, updated_at: NOW - 2000 },
  { id: "task-captions", project_id: MUG, title: "Caption variants (9:16)", status: "active", created_at: NOW - 3500, updated_at: NOW - 2500 },
] };

const runBase = (jobId: string, patch: Record<string, unknown>) => ({
  job_id: jobId, project_id: MUG, conversation_id: MUG_TASK, turn_index: 1,
  prompt: "From this product photo make a 10 second product film with a warm voiceover. Ask me before every paid step.",
  created_at: NOW - 900, updated_at: NOW - 30, tool_calls: [], events: [], ...patch,
});

const stillEvent = {
  id: "ev-still", name: "generate_image", label: "Product still generated", status: "completed", summary: "Studio Image · 1:1 · 2K · 37 s",
  arguments: {}, assets: [STILL],
};

const midLines = [
  { label: "Product still", detail: "image", price_cents: 26, kind: "media", basis: "fixed" },
  { label: "Video clip", detail: "5 s · 720p", price_cents: 65, kind: "media", basis: "fixed" },
  { label: "Agent orchestration", price_cents: 40, kind: "orchestration", basis: "estimate" },
];
const shot1Approval = {
  call_id: "ap-shot1", label: "Shot 1 · push-in on the handle", detail: "Studio Video · Standard quality", status: "pending", decision: null,
  arguments: { prompt: "Slow push-in on the handle and the matte texture. Soft morning window light, shallow depth of field. No text.", duration_seconds: 5, resolution: "720p", aspect_ratio: "16:9" },
  step_price_cents: 65, step_index: 2, step_count: 4,
  estimate_cents: 131, cap_cents: 200, held_cents: 0, spent_so_far_cents: 26, lines: midLines,
  balance_cents: 974, balance_after_estimate_cents: 843, balance_after_cap_cents: 774,
  approve_enabled: true, insufficient_credit: null, raise_options_cents: [], estimate_incomplete: false,
};

export const midRun = { items: [runBase("run-mid", {
  status: "awaiting_approval", message: "Shot 1 is next. Here's the price card. Nothing runs until you approve.",
  result: { title: "", summary: "", markdown: "", assets: [STILL], tool_events: [stillEvent] },
  approvals: [shot1Approval],
})] };

export const receiptRun = { items: [runBase("run-done", {
  status: "completed", message: "Done.", title: "10s product film",
  result: { title: "10s product film", summary: "Done. The film is assembled, and every step came in under its estimate. Here is exactly what was charged.", markdown: "", assets: [MACRO], primary_asset: MACRO, tool_events: [] },
  approvals: [],
  receipt: {
    type: "receipt", run_id: "run-done", status: "done", estimate_cents: 258, cap_cents: 350, actual_cents: 229, under_estimate: true, balance_before_cents: 1000, balance_after_cents: 771,
    lines: [
      { kind: "media", label: "Product still", detail: "image", price_cents: 26, basis: "fixed" },
      { kind: "media", label: "Shot 1", detail: "video clip · 5 s · 720p", price_cents: 65, basis: "fixed" },
      { kind: "media", label: "Shot 2", detail: "video clip · 5 s · 720p", price_cents: 65, basis: "fixed" },
      { kind: "media", label: "Voiceover", detail: "library voice · 24 words", price_cents: 2, basis: "fixed" },
      { kind: "orchestration", label: "Agent orchestration", price_cents: 71, basis: "fixed" },
    ],
  },
})] };

export const pausedRun = { items: [runBase("run-paused", {
  status: "error", error_type: "PausedAtCap", message: "Paused at the cap.", can_resume: true, recovery_available: true,
  result: { title: "", summary: "", markdown: "", assets: [STILL], tool_events: [stillEvent] }, approvals: [],
  paused_cap: {
    type: "paused_cap", status: "paused_cap", run_id: "run-paused",
    message: "The agent needed more attempts than estimated. Nothing more has been charged, and the step is paused so you decide.",
    charged_cents: 150, cap_cents: 150, held_cents: 150, balance_cents: 824, choices: ["raise_cap", "stop"], add_credit: false, raise_options_cents: [200, 250],
    lines: [
      { kind: "media", label: "Video clip", detail: "5 s · 720p", price_cents: 65, basis: "fixed" },
      { kind: "orchestration", label: "Agent orchestration", price_cents: 85, basis: "fixed" },
    ],
  },
})] };

const insufficient = { type: "insufficient_credit", reason: "insufficient_credit", approve_enabled: false, message: "Not enough credit for this cap.", balance_cents: 150, estimate_cents: 131, cap_cents: 200, lower_cap_option_cents: 150, add_credit: true, shortfall_cents: 50, minimum_needed_cents: 0 };
export const lowRun = { items: [{ ...midRun.items[0]!, approvals: [{ ...shot1Approval, balance_cents: 150, approve_enabled: false, insufficient_credit: insufficient, balance_after_estimate_cents: null, balance_after_cap_cents: null }] }] };

export const lowAccount = { balance_cents: 150, display_name: "Satya", beta_credit: { granted_cents: 1000, remaining_cents: 150, spent_cents: 850 }, recent_ledger: [], subscription: null };

export { camel };
