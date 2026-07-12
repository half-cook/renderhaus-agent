const state = {
  screen: "start",
  vibe: "quiet luxury",
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
  showToast.timer = window.setTimeout(() => toast.classList.remove("is-visible"), 3200);
}

function setScreen(name) {
  state.screen = name;
  $$('[data-screen]').forEach((screen) => {
    const active = screen.dataset.screen === name;
    screen.hidden = !active;
    screen.classList.toggle("is-active", active);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function filmName(prompt) {
  const words = prompt.trim().split(/\s+/).slice(0, 3).join(" ");
  return words ? words.toLowerCase() : "untitled film";
}

function setCreativeCopy(job) {
  const name = filmName(job.prompt);
  $("#create-title").textContent = name;
  $("#review-title").textContent = name;
  $("#film-label").textContent = name;
  $("#idea-copy").textContent = job.prompt;
  $("#duration-copy").textContent = `${job.duration_seconds} seconds`;
  $("#ratio-copy").textContent = job.aspect_ratio;
  $("#vibe-copy").textContent = job.vibe;
  $("#stage-time").textContent = `00:00 / 00:${String(job.duration_seconds).padStart(2, "0")}`;
  $("#timeline-progress").textContent = `00:00 / 00:${String(job.duration_seconds).padStart(2, "0")}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `Request failed (${response.status})`);
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

async function createGeneration(payload) {
  return api("/api/generations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function updateMedia(job) {
  const mediaUrl = job.media_url;
  const pairs = [
    [$("#create-video"), $("#create-placeholder")],
    [$("#review-video"), $("#review-placeholder")],
  ];
  pairs.forEach(([video, placeholder]) => {
    if (mediaUrl) {
      if (video.src !== new URL(mediaUrl, window.location.href).href) video.src = mediaUrl;
      video.hidden = false;
      placeholder.hidden = true;
    } else {
      video.hidden = true;
      placeholder.hidden = false;
    }
  });
}

function updateJobUI(job) {
  state.currentJob = job;
  const running = ["queued", "planning", "generating", "running"].includes(job.status);
  const terminal = ["complete", "planned"].includes(job.status);
  const shownProgress = running ? Math.min(88, Math.max(job.progress || 8, Number($("#progress-bar").dataset.progress || 0) + 4)) : job.progress;
  $("#progress-bar").style.width = `${shownProgress || 4}%`;
  $("#progress-bar").dataset.progress = shownProgress || 4;
  $("#render-message").textContent = job.message || "Shaping the shots, motion, and sound.";
  $("#save-status").textContent = job.status;
  $("#review-button").disabled = !terminal;
  $("#review-button").textContent = terminal ? "review" : `${Math.round(shownProgress || 4)}%`;
  $("#agent-note").textContent = job.status === "planned" ? "Live video rendering is off. This is the generated direction preview." : "";
  updateMedia(job);
  if (job.status === "failed") {
    $("#review-button").textContent = "retry";
    showToast(job.error?.message || "The render stopped before it finished.");
  }
}

async function pollJob(jobId) {
  window.clearInterval(state.pollTimer);
  const check = async () => {
    try {
      const job = await api(`/api/generations/${jobId}`);
      updateJobUI(job);
      if (["complete", "planned", "failed"].includes(job.status)) {
        window.clearInterval(state.pollTimer);
        await loadHistory();
        if (job.status === "complete") showToast("Your film is ready.");
        if (job.status === "planned") showToast("Direction ready. Live rendering is currently off.");
      }
    } catch (error) {
      window.clearInterval(state.pollTimer);
      showToast(error.message);
    }
  };
  await check();
  state.pollTimer = window.setInterval(check, 1800);
}

async function submitGeneration(event) {
  event.preventDefault();
  const prompt = $("#prompt").value.trim();
  if (prompt.length < 3) return;
  const submit = $("#generation-form .square-action");
  submit.disabled = true;
  try {
    const reference = $("#reference-input").files[0];
    const referencePath = await uploadReference(reference);
    const payload = {
      prompt,
      vibe: state.vibe,
      aspect_ratio: $("#aspect-ratio").value,
      duration_seconds: Number($("#duration").value),
      reference_asset_id: referencePath,
    };
    const job = await createGeneration(payload);
    setCreativeCopy(job);
    updateJobUI(job);
    setScreen("create");
    await pollJob(job.id);
  } catch (error) {
    showToast(error.message);
  } finally {
    submit.disabled = false;
  }
}

async function refine(instruction) {
  if (!state.currentJob || instruction.trim().length < 3) return;
  try {
    const job = await api(`/api/generations/${state.currentJob.id}/refine`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction: instruction.trim() }),
    });
    setCreativeCopy(job);
    updateJobUI(job);
    setScreen("create");
    showToast("Refinement started.");
    await pollJob(job.id);
  } catch (error) {
    showToast(error.message);
  }
}

function makeHistoryCard(job) {
  const button = document.createElement("button");
  button.className = "video-card video-card--black";
  button.type = "button";
  const orb = document.createElement("span");
  orb.className = "metal-orb";
  const label = document.createElement("span");
  label.textContent = `${filmName(job.prompt)} · 00:${String(job.duration_seconds).padStart(2, "0")}`;
  button.append(orb, label);
  button.addEventListener("click", () => {
    state.currentJob = job;
    setCreativeCopy(job);
    updateJobUI(job);
    setScreen(["complete", "planned"].includes(job.status) ? "review" : "create");
    if (!["complete", "planned", "failed"].includes(job.status)) pollJob(job.id);
  });
  return button;
}

async function loadHistory() {
  try {
    const { items } = await api("/api/generations");
    if (!items.length) return;
    const grid = $("#recent-grid");
    grid.innerHTML = "";
    items.slice(0, 3).forEach((job) => grid.append(makeHistoryCard(job)));
    const create = document.createElement("button");
    create.className = "video-card video-card--new";
    create.type = "button";
    create.textContent = "＋ start a new video";
    create.addEventListener("click", () => $("#prompt").focus());
    grid.append(create);
  } catch {
    // The hand-crafted cards remain visible if the local API is temporarily unavailable.
  }
}

async function loadConfig() {
  try {
    state.config = await api("/api/config");
    $("#generation-mode").textContent = state.config.live_generation ? "live rendering" : "preview mode";
  } catch {
    $("#generation-mode").textContent = "agent offline";
  }
}

function playVideo(video, placeholder, button) {
  if (!video.hidden && video.src) {
    if (video.paused) {
      video.play();
      button.textContent = "Ⅱ";
    } else {
      video.pause();
      button.textContent = "▶";
    }
  } else {
    placeholder.animate([{ transform: "scale(1)" }, { transform: "scale(1.012)" }, { transform: "scale(1)" }], { duration: 900, easing: "ease-in-out" });
    showToast("This direction preview becomes playable when a live MP4 is available.");
  }
}

function bindEvents() {
  $("#generation-form").addEventListener("submit", submitGeneration);
  $("#reference-input").addEventListener("change", (event) => {
    $("#reference-name").textContent = event.target.files[0] ? `reference / ${event.target.files[0].name}` : "";
  });
  $$(".vibe-chip").forEach((button) => button.addEventListener("click", () => {
    state.vibe = button.dataset.vibe;
    $$(".vibe-chip").forEach((item) => item.classList.toggle("is-selected", item === button));
  }));
  $$('[data-go]').forEach((button) => button.addEventListener("click", () => setScreen(button.dataset.go)));
  $$('[data-focus-prompt]').forEach((button) => button.addEventListener("click", () => $("#prompt").focus()));
  $("[data-scroll-history]").addEventListener("click", () => $("#recent-section").scrollIntoView({ behavior: "smooth" }));
  $("#review-button").addEventListener("click", () => {
    if (state.currentJob?.status === "failed") {
      refine("Retry the render with the same creative direction.");
      return;
    }
    setScreen("review");
  });
  $("#create-refine-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = $("#create-refine");
    refine(input.value);
    input.value = "";
  });
  $("#review-refine-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = $("#review-refine");
    refine(input.value);
    input.value = "";
  });
  $$('[data-quick]').forEach((button) => button.addEventListener("click", () => refine(button.dataset.quick)));
  $("#create-play").addEventListener("click", () => playVideo($("#create-video"), $("#create-placeholder"), $("#create-play")));
  $("#review-play").addEventListener("click", () => playVideo($("#review-video"), $("#review-placeholder"), $("#review-play")));
  $("#download-button").addEventListener("click", () => {
    if (state.currentJob?.media_url) window.open(state.currentJob.media_url, "_blank", "noopener");
    else showToast("Live rendering is off, so there is no MP4 to download yet.");
  });
  $("#share-button").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      showToast("Link copied.");
    } catch {
      showToast("Open this app from localhost to copy its link.");
    }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  await Promise.all([loadConfig(), loadHistory()]);
});
