const MIN_PROMPT_LENGTH = 3;
const TERMINAL_STATES = ["complete", "planned", "failed"];

const state = {
  mediaType: "video",
  currentJob: null,
  pollTimer: null,
  config: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("is-visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("is-visible"), 4000);
}

function filmName(prompt) {
  const words = String(prompt || "").trim().split(/\s+/).slice(0, 3).join(" ");
  return words ? words.toLowerCase() : "untitled";
}

function setPromptError(message) {
  const wrap = $("#prompt-error");
  if (!message) {
    wrap.hidden = true;
    $("#prompt").removeAttribute("aria-invalid");
    return;
  }
  $("#prompt-error-text").textContent = message;
  wrap.hidden = false;
  $("#prompt").setAttribute("aria-invalid", "true");
}

function setMode(mode) {
  $("#app").dataset.mode = mode;
  $("#home").hidden = mode !== "home";
  $("#workspace").hidden = mode !== "workspace";
  $("#mode-pill").textContent = mode === "workspace" ? "agent · live" : "agent";
}

function setRail(open) {
  $("#app").dataset.rail = open ? "open" : "closed";
  const toggle = $("#rail-toggle");
  toggle.setAttribute("aria-expanded", String(open));
  $("span.sr-only", toggle).textContent = open ? "Hide the agent panel" : "Show the agent panel";
}

function setMediaType(mediaType) {
  state.mediaType = mediaType;
  $$(".tab").forEach((tab) => {
    const active = tab.dataset.mediaType === mediaType;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  $("#duration-wrap").hidden = mediaType === "image";
  $("#generate-label").textContent = mediaType === "image" ? "Generate image" : "Generate video";
  updateModelHint();
}

function updateModelHint() {
  const videoModel = state.config?.video_model || "dreamina-seedance-2-0-mini-260615";
  const imageModel = state.config?.image_model || "seedream-5-0-lite-260128";
  $("#model-hint").textContent =
    state.mediaType === "image"
      ? `Image · ${prettyModel(imageModel)}`
      : `Video · ${prettyModel(videoModel)}`;
}

function prettyModel(model) {
  if (model.includes("seedance-2-0-mini")) return "Dreamina Seedance 2.0 mini";
  if (model.includes("seedream-5-0-lite") || model.includes("seedream-5-0")) return "Seedream 5.0 Lite";
  return model;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `The request failed (${response.status}).`);
  }
  return payload;
}

async function uploadReference(file) {
  if (!file) return null;
  const data = new FormData();
  data.append("file", file);
  const result = await api("/api/uploads", { method: "POST", body: data });
  return result.asset_id;
}

function clearReference() {
  $("#reference-input").value = "";
  $("#reference-name").hidden = true;
  $("#reference-name-text").textContent = "";
}

function renderTraces(traces) {
  const list = $("#trace-list");
  list.innerHTML = "";
  const items = Array.isArray(traces) ? traces : [];
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "trace-item is-running";
    const dot = document.createElement("span");
    dot.className = "trace-dot";
    dot.setAttribute("aria-hidden", "true");
    const body = document.createElement("div");
    const title = document.createElement("div");
    title.className = "trace-title";
    title.textContent = "Waiting for the agent";
    const detail = document.createElement("div");
    detail.className = "trace-detail";
    detail.textContent = "Each step appears here as the agent calls a tool.";
    body.append(title, detail);
    empty.append(dot, body);
    list.append(empty);
    return;
  }
  items.forEach((trace, index) => {
    const li = document.createElement("li");
    const status = trace.status || "done";
    li.className = `trace-item is-${status}`;
    li.style.animationDelay = `${Math.min(index, 8) * 60}ms`;
    const title = document.createElement("div");
    title.className = "trace-title";
    title.textContent = trace.title || "step";
    const detail = document.createElement("div");
    detail.className = "trace-detail";
    detail.textContent = trace.detail || status;
    const body = document.createElement("div");
    body.append(title, detail);
    const dot = document.createElement("span");
    dot.className = "trace-dot";
    dot.setAttribute("aria-hidden", "true");
    li.append(dot, body);
    list.append(li);
  });
  list.scrollTop = list.scrollHeight;
}

function updateMedia(job) {
  const video = $("#result-video");
  const image = $("#result-image");
  const stage = $("#stage");
  const mediaUrl = job.media_url;
  if (!mediaUrl) {
    video.hidden = true;
    image.hidden = true;
    video.removeAttribute("src");
    image.removeAttribute("src");
    stage.classList.remove("has-media");
    return;
  }
  if (job.media_type === "image") {
    video.hidden = true;
    video.removeAttribute("src");
    if (image.src !== new URL(mediaUrl, window.location.href).href) image.src = mediaUrl;
    image.alt = `Generated still: ${job.prompt}`;
    image.hidden = false;
  } else {
    image.hidden = true;
    image.removeAttribute("src");
    if (video.src !== new URL(mediaUrl, window.location.href).href) video.src = mediaUrl;
    video.hidden = false;
  }
  stage.classList.add("has-media");
}

function updateStageState(job) {
  const stage = $("#stage");
  if (job.media_url) {
    stage.dataset.stage = "media";
    return;
  }
  if (job.status === "planned") {
    stage.dataset.stage = "notice";
    $("#notice-icon").firstElementChild.setAttribute("href", "#i-slate");
    $("#notice-title").textContent = "The direction is ready";
    $("#notice-body").textContent =
      "Live rendering is off, so the agent stopped after planning the shot. Set SEEDANCE_DRY_RUN to false and run it again to get the file.";
    $("#notice-action").textContent = "Write another prompt";
    return;
  }
  if (job.status === "failed") {
    stage.dataset.stage = "notice";
    $("#notice-icon").firstElementChild.setAttribute("href", "#i-warning");
    $("#notice-title").textContent = "The render stopped early";
    $("#notice-body").textContent =
      job.error?.message || "The provider ended the job before it produced a file.";
    $("#notice-action").textContent = "Try a different prompt";
    return;
  }
  stage.dataset.stage = "loading";
}

function updateJobUI(job) {
  state.currentJob = job;
  const running = ["queued", "planning", "generating", "running"].includes(job.status);
  const terminal = TERMINAL_STATES.includes(job.status);
  const bar = $("#progress-bar");
  const progress = running
    ? Math.min(92, Math.max(job.progress || 8, Number(bar.dataset.progress || 0) + 3))
    : job.progress || (terminal ? 100 : 8);

  $("#job-title").textContent = filmName(job.prompt);
  $("#job-prompt").textContent = job.prompt;
  $("#job-media-type").textContent = job.media_type || "video";
  $("#job-ratio").textContent = job.aspect_ratio;
  $("#job-duration").hidden = job.media_type === "image";
  $("#job-duration").textContent = job.duration_seconds ? `${job.duration_seconds}s` : "";
  $("#job-status").textContent = job.status;
  $("#job-status").className = `badge is-${job.status}`;
  $("#stage-message").textContent = job.message || "The agent is working on it.";

  bar.style.scale = `${Math.max(progress, 4) / 100} 1`;
  bar.dataset.progress = progress;
  $("#progress").setAttribute("aria-valuenow", String(progress));

  $("#canvas-label").textContent = terminal
    ? job.status === "complete"
      ? "Result"
      : job.status
    : "Rendering";
  $("#download-button").disabled = !job.media_url;
  $("#download-label").textContent =
    job.media_type === "image" ? "Download image" : "Download video";

  renderTraces(job.traces);
  updateMedia(job);
  updateStageState(job);
}

async function pollJob(jobId) {
  window.clearInterval(state.pollTimer);
  const check = async () => {
    try {
      const job = await api(`/api/generations/${jobId}`);
      updateJobUI(job);
      if (TERMINAL_STATES.includes(job.status)) {
        window.clearInterval(state.pollTimer);
        await loadHistory();
        if (job.status === "complete") {
          showToast(job.media_type === "image" ? "Your image is ready." : "Your film is ready.");
        } else if (job.status === "planned") {
          showToast("The direction is ready. Live rendering is off.");
        } else if (job.status === "failed") {
          showToast(job.error?.message || "The render stopped before it finished.");
        }
      }
    } catch (error) {
      window.clearInterval(state.pollTimer);
      showToast(error.message);
    }
  };
  await check();
  state.pollTimer = window.setInterval(check, 1500);
}

async function submitGeneration(event) {
  event.preventDefault();
  const prompt = $("#prompt").value.trim();
  if (prompt.length < MIN_PROMPT_LENGTH) {
    setPromptError("Describe the shot in at least a few words before generating.");
    $("#prompt").focus();
    return;
  }
  setPromptError("");

  const submit = $("#generate-button");
  submit.disabled = true;
  try {
    const reference = $("#reference-input").files[0];
    const referencePath = await uploadReference(reference);
    const payload = {
      prompt,
      media_type: state.mediaType,
      vibe: "quiet luxury",
      aspect_ratio: $("#aspect-ratio").value,
      duration_seconds: Number($("#duration").value),
      reference_asset_id: referencePath,
    };
    const job = await api("/api/generations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setMode("workspace");
    updateJobUI(job);
    await pollJob(job.id);
  } catch (error) {
    setPromptError(error.message);
  } finally {
    submit.disabled = false;
  }
}

async function refine(event) {
  event.preventDefault();
  if (!state.currentJob) return;
  const instruction = $("#refine").value.trim();
  if (instruction.length < MIN_PROMPT_LENGTH) return;
  const submit = $("#refine-button");
  submit.disabled = true;
  try {
    const job = await api(`/api/generations/${state.currentJob.id}/refine`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction }),
    });
    $("#refine").value = "";
    setMode("workspace");
    updateJobUI(job);
    showToast("Refinement started.");
    await pollJob(job.id);
  } catch (error) {
    showToast(error.message);
  } finally {
    submit.disabled = $("#refine").value.trim().length < MIN_PROMPT_LENGTH;
  }
}

function makeHistoryItem(job) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "history-item";
  const title = document.createElement("strong");
  title.textContent = filmName(job.prompt);
  const meta = document.createElement("span");
  meta.textContent = `${job.media_type || "video"} · ${job.status}`;
  button.append(title, meta);
  button.addEventListener("click", () => {
    state.currentJob = job;
    setMode("workspace");
    updateJobUI(job);
    if (!TERMINAL_STATES.includes(job.status)) pollJob(job.id);
  });
  return button;
}

async function loadHistory() {
  try {
    const { items } = await api("/api/generations");
    const list = $("#history-list");
    list.innerHTML = "";
    if (!items.length) {
      $("#history").hidden = true;
      return;
    }
    $("#history").hidden = false;
    items.slice(0, 6).forEach((job) => list.append(makeHistoryItem(job)));
  } catch {
    $("#history").hidden = true;
  }
}

async function loadConfig() {
  try {
    state.config = await api("/api/config");
    const live =
      state.mediaType === "image"
        ? state.config.live_image_generation
        : state.config.live_generation;
    const tracing = state.config.langfuse_ready ? " · langfuse" : "";
    $("#config-status").textContent = `${live ? "live" : "preview"}${tracing}`;
    updateModelHint();
  } catch {
    $("#config-status").textContent = "offline";
  }
}

function startNewRender() {
  window.clearInterval(state.pollTimer);
  state.currentJob = null;
  setPromptError("");
  setMode("home");
  $("#prompt").focus();
}

function bindEvents() {
  $("#generation-form").addEventListener("submit", submitGeneration);
  $("#refine-form").addEventListener("submit", refine);

  $("#prompt").addEventListener("input", () => setPromptError(""));

  const refineInput = $("#refine");
  const syncRefineButton = () => {
    $("#refine-button").disabled = refineInput.value.trim().length < MIN_PROMPT_LENGTH;
  };
  refineInput.addEventListener("input", syncRefineButton);
  syncRefineButton();

  $$(".tab").forEach((tab) =>
    tab.addEventListener("click", () => {
      setMediaType(tab.dataset.mediaType);
      loadConfig();
    })
  );

  $("#reference-input").addEventListener("change", (event) => {
    const file = event.target.files[0];
    $("#reference-name").hidden = !file;
    $("#reference-name-text").textContent = file ? file.name : "";
  });
  $("#reference-clear").addEventListener("click", clearReference);

  $("#home-button").addEventListener("click", () => setMode("home"));
  $("#new-button").addEventListener("click", startNewRender);
  $("#notice-action").addEventListener("click", startNewRender);

  $("#rail-toggle").addEventListener("click", () => {
    setRail($("#app").dataset.rail !== "open");
  });

  $("#download-button").addEventListener("click", () => {
    if (state.currentJob?.media_url) {
      window.open(state.currentJob.media_url, "_blank", "noopener");
    }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  setMediaType("video");
  setMode("home");
  await Promise.all([loadConfig(), loadHistory()]);
});
