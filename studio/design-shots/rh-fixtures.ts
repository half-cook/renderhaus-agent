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
    schemaVersion: 2, projectName: "Matte travel mug", viewport: { x: 40, y: 40, zoom: 0.95 },
    nodes: [
      node("n-prompt", "text", 40, 70, { kind: "text", title: "Prompt", config: { text: "Create a product photo: a matte-black stainless travel mug on a pale stone counter, soft morning window light, shallow depth of field." } }),
      node("n-still", "image", 400, 40, { kind: "image", title: "Product still", status: "completed", toolId: "image.generate", providerId: "seedance", toolName: "text_to_video", output: { assetId: "still-mug", versionId: "fx-still-mug", kind: "image", filename: "still-mug.jpg", mimeType: "image/jpeg" }, chargedCents: 26, config: { aspect_ratio: "1:1", size: "2K" } }),
      node("n-shot1", "video", 860, 40, { kind: "video", title: "Shot 1 · push-in", toolId: "video.generate", providerId: "seedance", toolName: "text_to_video", approved: true, storyOrder: 0, estimate: VIDEO_ESTIMATE, output: { assetId: "shot-macro", versionId: "fx-shot-macro", kind: "image", filename: "shot-macro.jpg", mimeType: "image/jpeg" }, config: { prompt: "Slow push-in on the handle and the matte texture. Soft morning window light.", model: "dreamina-seedance-2-5-260628", duration_seconds: 5, aspect_ratio: "16:9", resolution: "720p", trim_in_seconds: 0, trim_out_seconds: 5, thumbnail_url: "/beta/shot-macro.jpg" } }),
      node("n-shot2", "video", 860, 360, { kind: "video", title: "Shot 2 · hand lifts mug", approved: true, storyOrder: 1, output: { assetId: "shot-lift", versionId: "fx-shot-lift", kind: "image", filename: "shot-lift.jpg", mimeType: "image/jpeg" }, config: { duration_seconds: 5, aspect_ratio: "16:9", resolution: "720p", trim_in_seconds: 0, trim_out_seconds: 5, thumbnail_url: "/beta/shot-lift.jpg" } }),
      node("n-voice", "audio", 400, 340, { kind: "audio", title: "Voiceover", chargedCents: 2, config: { voice: "library voice", duration_seconds: 9, text: "A mug made to be held." } }),
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

const planSteps = (current: number) => [
  { label: "Product still · image", price_cents: 26, basis: "fixed", state: current > 0 ? "done" : "current" },
  { label: "Shot 1 · push-in · 5 s", price_cents: 65, basis: "fixed", state: current > 1 ? "done" : current === 1 ? "current" : "todo" },
  { label: "Shot 2 · hand lifts mug · 5 s", price_cents: 65, basis: "fixed", state: current > 2 ? "done" : current === 2 ? "current" : "todo" },
  { label: "Voiceover · 24 words · library voice", price_cents: 2, basis: "fixed", state: "todo" },
  { label: "Assemble film · hard cuts", price_cents: 0, free: true, state: "todo" },
  { label: "Agent orchestration · estimate across the plan", price_cents: 100, basis: "estimate", state: "todo" },
];

const runBase = (jobId: string, patch: Record<string, unknown>) => ({
  job_id: jobId, project_id: MUG, conversation_id: MUG_TASK, turn_index: 1,
  prompt: "From this product photo make a 10 second product film with a warm voiceover. Ask me before every paid step.",
  created_at: NOW - 900, updated_at: NOW - 30, tool_calls: [], events: [], ...patch,
});

const stillEvent = {
  id: "ev-still", name: "generate_image", label: "Product still generated", status: "completed", summary: "Studio Image · 1:1 · 2K · 37 s",
  arguments: {}, assets: [STILL],
};

export const midRun = { items: [runBase("run-mid", {
  status: "awaiting_approval", message: "Shot 1 is next. Here's the price card. Nothing runs until you approve.",
  title: undefined, result: { title: "", summary: "", markdown: "", assets: [STILL], tool_events: [stillEvent] },
  approvals: [{
    call_id: "ap-shot1", tool_name: "text_to_video", label: "Shot 1 · push-in on the handle",
    arguments: { prompt: "Slow push-in on the handle and the matte texture. Soft morning window light, shallow depth of field. No text.", duration_seconds: 5, resolution: "720p", aspect_ratio: "16:9" },
    billing: { ...VIDEO_ESTIMATE, balance_cents: 974, tier: "Studio Video · Standard quality", step_index: 2, step_count: 4, thumb_url: "/beta/still-mug-wide.jpg", balance_after_estimate_cents: 869, balance_after_cap_cents: 824, wallet_total_cents: 1000 },
  }],
  billing: {
    plan: { estimate_cents: 258, cap_cents: 350, steps: planSteps(1) },
    spend: { lines: [
      { label: "Product still", amount_cents: 26, tone: "charged" },
      { label: "Awaiting approval", amount_cents: 105, tone: "awaiting" },
      { label: "Still to ask", amount_cents: 127, tone: "estimate" },
    ], total_label: "Plan · estimated total", total_cents: 258 },
  },
})] };

export const receiptRun = { items: [runBase("run-done", {
  status: "completed", message: "Done.", title: "10s product film",
  result: { title: "10s product film", summary: "Done. The film is assembled, and every step came in under its estimate. Here is exactly what was charged.", markdown: "", assets: [MACRO], primary_asset: MACRO, tool_events: [] },
  approvals: [],
  billing: {
    type: "receipt", scope: "run", title: "10s product film", finished_label: "Finished 7:52 PM · 10 s · 16:9 · voiceover",
    estimate_cents: 258, cap_cents: 350, actual_cents: 229, under_estimate: true, balance_before_cents: 1000, balance_after_cents: 771, paid_steps: 4,
    lines: [
      { kind: "media", label: "Product still", detail: "image", price_cents: 26 },
      { kind: "media", label: "Shot 1", detail: "video clip · 5 s · 720p", price_cents: 65 },
      { kind: "media", label: "Shot 2", detail: "video clip · 5 s · 720p", price_cents: 65 },
      { kind: "media", label: "Voiceover", detail: "library voice · 24 words", price_cents: 2 },
      { kind: "orchestration", label: "Agent orchestration", price_cents: 71 },
    ],
    spend: { lines: [
      { label: "Product still", amount_cents: 26, tone: "charged" }, { label: "Shots 1 and 2", amount_cents: 130, tone: "charged" },
      { label: "Voiceover", amount_cents: 2, tone: "charged" }, { label: "Agent orchestration", amount_cents: 71, tone: "charged" },
    ], total_label: "Total charged", total_cents: 229 },
  },
})] };

export const pausedRun = { items: [runBase("run-paused", {
  status: "error", error_type: "PausedAtCap", message: "Paused at the cap.", can_resume: true, recovery_available: true,
  result: { title: "", summary: "", markdown: "", assets: [STILL], tool_events: [stillEvent] }, approvals: [],
  billing: {
    type: "paused_cap", status: "paused_cap", title: "Shot 1 · push-in on the handle", tier: "Studio Video · Standard quality", step_index: 2, step_count: 4,
    charged_cents: 150, cap_cents: 150, held_cents: 150, balance_cents: 824, wallet_total_cents: 1000, raise_options_cents: [200, 250],
    lines: [
      { kind: "media", label: "Video clip", detail: "5 s · 720p", price_cents: 65 }, { kind: "orchestration", label: "Agent orchestration", price_cents: 85 },
    ],
    message: "The agent needed more attempts than estimated. Nothing more has been charged, and the step is paused so you decide.",
    held: 150,
    spend: { lines: [
      { label: "Product still", amount_cents: 26, tone: "charged" }, { label: "Shot 1 · stopped at cap", amount_cents: 150, tone: "charged" },
      { label: "Still to ask", amount_cents: 127, tone: "estimate" },
    ], total_label: "Plan · estimated total", total_cents: 303 },
  },
})] };

const lowEstimate = { ...VIDEO_ESTIMATE, balance_cents: 120, lower_cap_option_cents: 120, approve_enabled: false };
export const lowRun = { items: [{ ...midRun.items[0]!, approvals: [{ ...midRun.items[0]!.approvals[0]!, billing: { ...midRun.items[0]!.approvals[0]!.billing, ...lowEstimate, balance_after_estimate_cents: undefined, balance_after_cap_cents: undefined } }] }] };

export const lowAccount = { balance_cents: 120, display_name: "Satya", beta_credit: { granted_cents: 1000, remaining_cents: 120, spent_cents: 880 }, recent_ledger: [], subscription: null };

export { camel };
