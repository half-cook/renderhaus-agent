const MIN_PROMPT_LENGTH = 3;
const TERMINAL_STATES = ["complete", "planned", "failed"];
const FILMSTRIP_FRAMES = 16;

const EDIT_IDEAS = [
  { label: "Slow the push in", instruction: "Slow the camera push in and let the motion breathe." },
  { label: "Hold on the hero", instruction: "Hold longer on the hero subject before any camera move." },
  { label: "Warmer grade", instruction: "Warm the grade with golden key light and softer contrast." },
  { label: "Tighter framing", instruction: "Tighten the framing so the subject fills more of the frame." },
  { label: "Add a reverse", instruction: "End with a subtle reverse move that reveals the space." },
  { label: "Softer motion", instruction: "Soften the motion so every move feels more deliberate." },
  { label: "More atmosphere", instruction: "Add more atmosphere: dust, haze, and light falloff in the air." },
  { label: "Cleaner product", instruction: "Keep the product cleaner and more centered with less distraction." },
];

const MUSIC_EDIT_IDEAS = [
  { label: "Slower tempo", instruction: "Slow the tempo and leave more space between phrases." },
  { label: "Warmer pads", instruction: "Warm the arrangement with softer pads and less sharp percussion." },
  { label: "More tension", instruction: "Build more tension with rising harmony and restrained drums." },
  { label: "Strip it back", instruction: "Strip the arrangement back to a sparse, intimate instrumental." },
  { label: "Cinematic swell", instruction: "Add a cinematic swell in the second half with richer strings." },
  { label: "Pulse under it", instruction: "Add a subtle low pulse that keeps the track moving without crowding the melody." },
];

const state = {
  mediaType: "video",
  currentJob: null,
  pollTimer: null,
  pollToken: 0,
  pollJobId: null,
  mediaRefreshToken: 0,
  config: null,
  filmstripToken: 0,
  filmstripSrc: null,
  scrubbing: false,
  clerk: null,
  signedIn: false,
  projects: [],
  currentProject: null,
  projectJobs: [],
  unassignedJobs: [],
  dragJobId: null,
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
  syncProjectChrome();
}

function syncProjectChrome() {
  const chip = $("#project-chip");
  const project = state.currentProject;
  const projectLibrary = $("#project-library");
  if (chip) {
    if (project) {
      chip.hidden = false;
      $("#project-chip-label").textContent = project.title;
    } else {
      chip.hidden = true;
    }
  }
  if (projectLibrary) projectLibrary.hidden = !project;
  $("#home-kicker").textContent = project ? project.title : "Renderhaus agent";
  $("#home-lede").textContent = project
    ? "Generate into this project, or keep working standalone. Use \u201cAdd to V1/M1\u201d on any clip to arrange the timeline."
    : "Describe the shot or score the way you would brief a collaborator. The agent picks the model, writes the technical prompt, and hands back the finished file.";
  $("#history-label").textContent = project ? "Recent in project" : "Recent";
  $$(".project-card").forEach((card) => {
    card.classList.toggle("is-active", Boolean(project && card.dataset.projectId === project.id));
  });
  const standaloneNav = $("#clear-project-button");
  if (standaloneNav) standaloneNav.hidden = !project;
  const canvasLabel = $("#canvas-label");
  if (canvasLabel && canvasLabel.dataset.base) {
    canvasLabel.textContent = project ? `${project.title} \u00b7 ${canvasLabel.dataset.base}` : canvasLabel.dataset.base;
  }
}

function setRail(open) {
  $("#app").dataset.rail = open ? "open" : "closed";
  const toggle = $("#rail-toggle");
  toggle.setAttribute("aria-expanded", String(open));
  $("span.sr-only", toggle).textContent = open ? "Hide the agent panel" : "Show the agent panel";
}

function setLibrary(open) {
  $("#app").dataset.library = open ? "open" : "closed";
  const toggle = $("#library-toggle");
  if (toggle) toggle.setAttribute("aria-expanded", String(open));
  const label = $("#library-toggle-label");
  if (label) label.textContent = open ? "Hide projects" : "Show projects";
}

function setMediaType(mediaType) {
  state.mediaType = mediaType;
  $$(".tab").forEach((tab) => {
    const active = tab.dataset.mediaType === mediaType;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  $("#duration-wrap").hidden = mediaType !== "video";
  $("#aspect-ratio").closest("label").hidden = mediaType === "music";
  const referenceButton = $('label.file-button[for="reference-input"]');
  if (referenceButton) referenceButton.hidden = mediaType === "music";
  if (mediaType === "music") clearReference();
  $("#generate-label").textContent =
    mediaType === "image" ? "Generate image" : mediaType === "music" ? "Generate music" : "Generate video";
  const prompt = $("#prompt");
  prompt.placeholder =
    mediaType === "music"
      ? "A quiet luxury product score: soft analog pads, restrained percussion, warm low end, slow bloom…"
      : "A chrome perfume bottle drifting through a sunlit concrete gallery, slow dolly in, dust in the light…";
  updateModelHint();
}

function updateModelHint() {
  const videoModel = state.config?.video_model || "seedance-1-5-pro-251215";
  const imageModel = state.config?.image_model || "seedream-5-0-lite-260128";
  const musicModel = state.config?.music_model || "auto";
  if (state.mediaType === "image") {
    $("#model-hint").textContent = `Image · ${prettyModel(imageModel)}`;
  } else if (state.mediaType === "music") {
    $("#model-hint").textContent = `Music · ${prettyModel(musicModel)}`;
  } else {
    $("#model-hint").textContent = `Video · ${prettyModel(videoModel)}`;
  }
}

function prettyModel(model) {
  if (model.includes("seedance-1-5-pro")) return "Seedance 1.5 Pro";
  if (model.includes("seedance-2-0-mini")) return "Dreamina Seedance 2.0 mini";
  if (model.includes("seedream-5-0-lite") || model.includes("seedream-5-0")) return "Seedream 5.0 Lite";
  if (model === "auto" || model.includes("mureka")) return "Mureka";
  return model;
}

function clerkFrontendHost(publishableKey) {
  try {
    return atob(publishableKey.split("_")[2]).slice(0, -1);
  } catch {
    return "";
  }
}

function loadScript(src, attributes = {}) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      if (existing.dataset.loaded === "true") {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error(`Failed to load ${src}`)), {
        once: true,
      });
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.crossOrigin = "anonymous";
    Object.entries(attributes).forEach(([key, value]) => script.setAttribute(key, value));
    script.onload = () => {
      script.dataset.loaded = "true";
      resolve();
    };
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
}

function renderAuthControls() {
  const slot = $("#auth-slot");
  const signInButton = $("#sign-in-button");
  const userButton = $("#user-button");
  if (!slot || !signInButton || !userButton) return;
  if (!state.config?.clerk_enabled) {
    slot.hidden = true;
    return;
  }
  slot.hidden = false;
  if (state.signedIn && state.clerk) {
    signInButton.hidden = true;
    userButton.hidden = false;
    if (!userButton.dataset.mounted) {
      state.clerk.mountUserButton(userButton);
      userButton.dataset.mounted = "true";
    }
  } else {
    userButton.hidden = true;
    signInButton.hidden = false;
  }
}

async function ensureSignedIn() {
  if (!state.config?.clerk_enabled) return true;
  if (state.signedIn && state.clerk?.session) return true;
  if (!state.clerk) {
    showToast("Sign in is still loading. Try again in a moment.");
    return false;
  }
  state.clerk.openSignIn();
  showToast("Sign in to generate.");
  return false;
}

async function initClerk(publishableKey) {
  if (!publishableKey || state.clerk) return state.clerk;
  const host = clerkFrontendHost(publishableKey);
  if (!host) throw new Error("Invalid Clerk publishable key.");

  await loadScript(`https://${host}/npm/@clerk/ui@1/dist/ui.browser.js`);
  await loadScript(`https://${host}/npm/@clerk/clerk-js@6/dist/clerk.browser.js`, {
    "data-clerk-publishable-key": publishableKey,
  });

  // clerk-js may attach window.Clerk slightly after the script load event.
  let clerk = window.Clerk;
  for (let i = 0; i < 20 && !clerk; i += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 50));
    clerk = window.Clerk;
  }
  if (!clerk) throw new Error("Clerk failed to initialize.");
  await clerk.load({
    ui: { ClerkUI: window.__internal_ClerkUICtor },
  });
  state.clerk = clerk;
  state.signedIn = Boolean(clerk.isSignedIn);
  clerk.addListener(({ user }) => {
    state.signedIn = Boolean(user);
    renderAuthControls();
    if (state.signedIn) {
      refreshLibrary();
      loadHistory();
    }
  });
  renderAuthControls();
  return clerk;
}

async function authHeaders() {
  const headers = {};
  if (state.clerk?.session) {
    const token = await state.clerk.session.getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const auth = await authHeaders();
  Object.entries(auth).forEach(([key, value]) => headers.set(key, value));
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && state.config?.clerk_enabled) {
    if (!state.signedIn) state.clerk?.openSignIn?.();
    throw new Error("Sign in to continue.");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload.error;
    throw new Error(
      typeof detail === "string" ? detail : `The request failed (${response.status}).`
    );
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

function formatClock(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const whole = Math.floor(value);
  const m = Math.floor(whole / 60);
  const s = whole % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatTraceTime(epochSeconds) {
  if (!epochSeconds) return "";
  const date = new Date(Number(epochSeconds) * 1000);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function prettyKind(kind) {
  const value = String(kind || "status").toLowerCase();
  if (value === "tool") return "tool";
  if (value === "agent") return "agent";
  return "status";
}

function prettyToolTitle(title) {
  const words = String(title || "step").replace(/_/g, " ").split(/\s+/).filter(Boolean);
  return words
    .map((word, index) =>
      index === 0 ? word.charAt(0).toUpperCase() + word.slice(1).toLowerCase() : word.toLowerCase()
    )
    .join(" ");
}

function summarizeTraceDetail(trace) {
  const raw = String(trace?.detail || "").trim();
  if (!raw) return trace?.status || "";
  if (!raw.startsWith("[") && !raw.startsWith("{")) return raw;

  try {
    const parsed = JSON.parse(raw);
    const payload = Array.isArray(parsed)
      ? parsed.find((item) => item && typeof item.text === "string")
      : parsed;
    const nested =
      payload && typeof payload.text === "string"
        ? JSON.parse(payload.text)
        : payload;
    if (nested && typeof nested === "object") {
      if (nested.note) return String(nested.note);
      if (nested.status && nested.job_id) {
        return `Task ${nested.status}${nested.mode ? ` · ${String(nested.mode).replace(/_/g, " ")}` : ""}.`;
      }
      if (nested.status) return `Provider status: ${nested.status}`;
    }
  } catch {
    /* fall through */
  }
  return "Tool finished.";
}

function makeTraceItem(trace, index, { empty = false } = {}) {
  const status = empty ? "running" : trace.status || "done";
  const li = document.createElement("li");
  li.className = `trace-item is-${status}`;
  li.style.animationDelay = `${Math.min(index, 8) * 60}ms`;

  const node = document.createElement("span");
  node.className = "trace-node";
  node.setAttribute("aria-hidden", "true");

  const body = document.createElement("div");
  body.className = "trace-body";

  const meta = document.createElement("div");
  meta.className = "trace-meta";
  const kind = document.createElement("span");
  kind.className = "trace-kind";
  kind.textContent = empty ? "live" : prettyKind(trace.kind);
  meta.append(kind);
  const time = formatTraceTime(trace?.at);
  if (time) {
    const stamp = document.createElement("span");
    stamp.className = "trace-time";
    stamp.textContent = time;
    meta.append(stamp);
  }

  const title = document.createElement("div");
  title.className = "trace-title";
  title.textContent = empty
    ? "Waiting for the agent"
    : String(trace.title || "").includes("_")
      ? prettyToolTitle(trace.title)
      : trace.title || "step";

  const detail = document.createElement("div");
  detail.className = "trace-detail";
  detail.textContent = empty
    ? "Each step appears here as the agent plans and calls tools."
    : summarizeTraceDetail(trace) || status;

  body.append(meta, title, detail);
  li.append(node, body);
  return li;
}

function renderTraces(traces) {
  const list = $("#trace-list");
  list.innerHTML = "";
  const items = Array.isArray(traces) ? traces : [];
  $("#trace-count").textContent = String(items.length);
  if (!items.length) {
    list.append(makeTraceItem(null, 0, { empty: true }));
    return;
  }
  items.forEach((trace, index) => list.append(makeTraceItem(trace, index)));
  list.scrollTop = list.scrollHeight;
}

function renderEditIdeas(job) {
  const deck = $("#edit-deck");
  const chips = $("#idea-chips");
  chips.innerHTML = "";
  const showDeck =
    Boolean(state.currentProject) ||
    Boolean(job?.media_url && job.media_type !== "image");
  deck.hidden = !showDeck;
  if (!job?.media_url || job.media_type === "image") {
    return;
  }
  const ideas = job.media_type === "music" ? MUSIC_EDIT_IDEAS : EDIT_IDEAS;
  ideas.forEach((idea) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "idea-chip";
    button.textContent = idea.label;
    button.setAttribute("role", "listitem");
    button.addEventListener("click", () => {
      const refineInput = $("#refine");
      refineInput.value = idea.instruction;
      refineInput.dispatchEvent(new Event("input", { bubbles: true }));
      refineInput.focus();
      setRail(true);
      showToast("Edit idea loaded into refine.");
    });
    chips.append(button);
  });
}

function clearFilmstrip(note = "Frames appear when the clip is ready") {
  const strip = $("#filmstrip");
  if (!strip) return;
  strip.innerHTML = "";
  strip.classList.add("is-empty");
  strip.classList.remove("is-loading");
  strip.dataset.note = note;
  strip.hidden = true;
  $("#timeline-ruler").innerHTML = "";
  $("#timeline-clock").textContent = "0:00 / 0:00";
  $("#playhead").style.left = "60px";
  state.filmstripSrc = null;
}

function timelineItems(mediaType = null) {
  const items = state.currentProject?.timeline?.items || [];
  if (!mediaType) return items;
  return items.filter((item) => item.media_type === mediaType);
}

function setScoreTrack(active, label = "Score") {
  const clip = $("#score-clip");
  if (!clip) return;
  // Preview scrubber only when the music track has no arranged clips yet.
  const hasMusicClips = timelineItems("music").length > 0;
  clip.hidden = !active || hasMusicClips;
  if (active) $("#score-label").textContent = label;
}

function renderRuler(duration) {
  const ruler = $("#timeline-ruler");
  ruler.innerHTML = "";
  const spacer = document.createElement("div");
  spacer.className = "timeline-ruler-spacer";
  const marks = document.createElement("div");
  marks.className = "timeline-ruler-marks";
  const safeDuration = Math.max(duration || 0, 0.001);
  const step = safeDuration <= 6 ? 1 : safeDuration <= 12 ? 2 : safeDuration <= 60 ? 5 : 15;
  for (let t = 0; t <= safeDuration + 0.001; t += step) {
    const mark = document.createElement("span");
    mark.className = "ruler-mark";
    mark.style.left = `${(t / safeDuration) * 100}%`;
    const tick = document.createElement("i");
    const label = document.createElement("span");
    label.textContent = formatClock(t);
    mark.append(tick, label);
    marks.append(mark);
  }
  ruler.append(spacer, marks);
}

function activeScrubSurface(media) {
  if (!media) return null;
  if (media.tagName === "AUDIO") {
    const clips = $("#music-clips");
    if (clips && clips.childElementCount > 0) return clips;
    const score = $("#score-clip");
    return score && !score.hidden ? score : null;
  }
  const clips = $("#video-clips");
  if (clips && clips.childElementCount > 0) return clips;
  const strip = $("#filmstrip");
  return strip && !strip.hidden ? strip : null;
}

function updatePlayheadFromMedia(media) {
  const body = $("#timeline-body");
  const strip = activeScrubSurface(media);
  if (!media?.duration || media.hidden || !strip) return;
  const ratio = Math.min(1, Math.max(0, media.currentTime / media.duration));
  const laneLeft = strip.getBoundingClientRect().left - body.getBoundingClientRect().left;
  const laneWidth = strip.getBoundingClientRect().width;
  $("#playhead").style.left = `${laneLeft + ratio * laneWidth}px`;
  $("#timeline-clock").textContent = `${formatClock(media.currentTime)} / ${formatClock(media.duration)}`;
}

function updatePlayhead() {
  const video = $("#result-video");
  const audio = $("#result-audio");
  if (!video.hidden && video.duration) {
    updatePlayheadFromMedia(video);
    return;
  }
  if (!audio.hidden && audio.duration) {
    updatePlayheadFromMedia(audio);
  }
}

function waitForVideoEvent(video, eventName, { timeoutMs = 8000 } = {}) {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      cleanup();
      reject(new Error(`Timed out waiting for ${eventName}.`));
    }, timeoutMs);
    const onEvent = () => {
      cleanup();
      resolve();
    };
    const onError = () => {
      cleanup();
      reject(new Error("Could not read video frames."));
    };
    const cleanup = () => {
      window.clearTimeout(timer);
      video.removeEventListener(eventName, onEvent);
      video.removeEventListener("error", onError);
    };
    video.addEventListener(eventName, onEvent, { once: true });
    video.addEventListener("error", onError, { once: true });
  });
}

async function seekVideo(video, time) {
  if (!Number.isFinite(time)) return;
  if (Math.abs((video.currentTime || 0) - time) < 0.01) return;
  const seeked = waitForVideoEvent(video, "seeked", { timeoutMs: 5000 });
  try {
    video.currentTime = time;
  } catch (error) {
    throw error;
  }
  await seeked;
}

async function captureFilmstrip(mediaUrl) {
  const token = ++state.filmstripToken;
  const strip = $("#filmstrip");
  // Filmstrip is only for previewing a single clip when V1 has no arranged clips.
  if (timelineItems("video").length > 0) {
    strip.hidden = true;
    return;
  }
  strip.hidden = false;
  strip.innerHTML = "";
  strip.classList.remove("is-empty");
  strip.classList.add("is-loading");
  strip.dataset.note = "Pulling frames…";

  // Prefer a same-origin blob so canvas frame export is never CORS-tainted.
  let objectUrl = null;
  const probe = document.createElement("video");
  probe.muted = true;
  probe.playsInline = true;
  probe.preload = "auto";

  try {
    // Proxy through our origin so canvas exports are never CORS-tainted by S3.
    const proxyUrl = new URL(mediaUrl, window.location.href);
    proxyUrl.searchParams.set("proxy", "1");
    const response = await fetch(proxyUrl.toString(), { credentials: "same-origin" });
    if (!response.ok) throw new Error(`Could not fetch video (${response.status}).`);
    const blob = await response.blob();
    if (token !== state.filmstripToken) return;
    objectUrl = URL.createObjectURL(blob);
    probe.src = objectUrl;

    await waitForVideoEvent(probe, "loadeddata");
    if (token !== state.filmstripToken) return;

    const duration = probe.duration || 0;
    renderRuler(duration);
    const count = Math.max(8, Math.min(FILMSTRIP_FRAMES, Math.round(duration * 2) || 8));
    const canvas = document.createElement("canvas");
    const width = 160;
    const height = 90;
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d", { alpha: false });

    for (let index = 0; index < count; index += 1) {
      if (token !== state.filmstripToken) return;
      const time =
        duration <= 0 ? 0 : (index / Math.max(count - 1, 1)) * Math.max(duration - 0.05, 0);
      await seekVideo(probe, time);
      ctx.drawImage(probe, 0, 0, width, height);
      const img = document.createElement("img");
      img.className = "film-frame";
      img.alt = "";
      img.draggable = false;
      img.src = canvas.toDataURL("image/jpeg", 0.72);
      strip.append(img);
    }

    strip.classList.remove("is-loading");
    state.filmstripSrc = mediaUrl;
    updatePlayhead();
  } catch (error) {
    if (token !== state.filmstripToken) return;
    console.warn("Filmstrip capture failed:", error);
    clearFilmstrip("Frames unavailable for this clip");
  } finally {
    probe.removeAttribute("src");
    probe.load();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }
}

function seekFromClientX(clientX) {
  const video = $("#result-video");
  const audio = $("#result-audio");
  const media = !video.hidden && video.duration ? video : !audio.hidden && audio.duration ? audio : null;
  const strip = activeScrubSurface(media);
  if (!media || !strip) return;
  const rect = strip.getBoundingClientRect();
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  media.currentTime = ratio * media.duration;
  updatePlayhead();
}

function bindTimelineControls() {
  const video = $("#result-video");
  const audio = $("#result-audio");
  const strip = $("#filmstrip");
  const score = $("#score-clip");
  const body = $("#timeline-body");

  [video, audio].forEach((media) => {
    media.addEventListener("timeupdate", updatePlayhead);
    media.addEventListener("loadedmetadata", () => {
      renderRuler(media.duration || 0);
      updatePlayhead();
    });
    media.addEventListener("seeked", updatePlayhead);
  });

  const startScrub = (event) => {
    if (event.button != null && event.button !== 0) return;
    state.scrubbing = true;
    body.classList.add("is-scrubbing");
    seekFromClientX(event.clientX);
    event.preventDefault();
  };
  const moveScrub = (event) => {
    if (!state.scrubbing) return;
    seekFromClientX(event.clientX);
  };
  const endScrub = () => {
    state.scrubbing = false;
    body.classList.remove("is-scrubbing");
  };

  [strip, score].forEach((target) => {
    target.addEventListener("pointerdown", startScrub);
    target.addEventListener("keydown", (event) => {
      const media =
        !video.hidden && video.duration ? video : !audio.hidden && audio.duration ? audio : null;
      if (!media) return;
      const step = event.shiftKey ? 1 : 0.25;
      if (event.key === "ArrowRight") {
        media.currentTime = Math.min(media.duration, media.currentTime + step);
        event.preventDefault();
      } else if (event.key === "ArrowLeft") {
        media.currentTime = Math.max(0, media.currentTime - step);
        event.preventDefault();
      }
    });
  });
  window.addEventListener("pointermove", moveScrub);
  window.addEventListener("pointerup", endScrub);
  window.addEventListener("pointercancel", endScrub);
  window.addEventListener("resize", updatePlayhead);
}

async function refreshMediaUrl() {
  if (!state.currentJob?.id || !state.currentJob.media_url) return;
  const jobId = state.currentJob.id;
  const token = ++state.mediaRefreshToken;
  try {
    const job = await api(`/api/generations/${jobId}`);
    // A newer open/poll/refresh won; drop this stale media recovery.
    if (token !== state.mediaRefreshToken || state.currentJob?.id !== jobId) return;
    state.currentJob = job;
    updateJobUI(job);
  } catch {
    /* keep the existing URL; download/playback may still fail visibly */
  }
}

function bindMediaAuthRecovery() {
  ["#result-video", "#result-image", "#result-audio"].forEach((selector) => {
    const el = $(selector);
    if (!el || el.dataset.authRecovery === "1") return;
    el.dataset.authRecovery = "1";
    el.addEventListener("error", () => {
      // Hidden leftover nodes (e.g. previous image) must not steal the current job.
      if (el.hidden) return;
      if (!state.currentJob?.media_url) return;
      if (el.dataset.refreshing === "1") return;
      el.dataset.refreshing = "1";
      refreshMediaUrl().finally(() => {
        el.dataset.refreshing = "0";
      });
    });
  });
}

function stopPolling() {
  window.clearInterval(state.pollTimer);
  state.pollTimer = null;
  state.pollJobId = null;
  state.pollToken += 1;
}

function openJob(job, { poll = true } = {}) {
  if (!job?.id) return;
  stopPolling();
  state.mediaRefreshToken += 1;
  state.currentJob = job;
  setMode("workspace");
  updateJobUI(job);
  if (poll && !TERMINAL_STATES.includes(job.status)) {
    pollJob(job.id);
  }
}

function updateMedia(job) {
  const video = $("#result-video");
  const image = $("#result-image");
  const audio = $("#result-audio");
  const stage = $("#stage");
  const mediaUrl = job.media_url;
  bindMediaAuthRecovery();
  if (!mediaUrl) {
    video.hidden = true;
    image.hidden = true;
    audio.hidden = true;
    video.removeAttribute("src");
    image.removeAttribute("src");
    audio.removeAttribute("src");
    stage.classList.remove("has-media");
    clearFilmstrip();
    setScoreTrack(false);
    // Keep the project sequence visible even while a render is in flight.
    $("#edit-deck").hidden = !state.currentProject;
    return;
  }
  if (job.media_type === "image") {
    video.hidden = true;
    audio.hidden = true;
    video.removeAttribute("src");
    audio.removeAttribute("src");
    if (image.src !== new URL(mediaUrl, window.location.href).href) image.src = mediaUrl;
    image.alt = `Generated still: ${job.prompt}`;
    image.hidden = false;
    clearFilmstrip();
    setScoreTrack(false);
    $("#edit-deck").hidden = !state.currentProject;
  } else if (job.media_type === "music") {
    video.hidden = true;
    image.hidden = true;
    video.removeAttribute("src");
    image.removeAttribute("src");
    const absolute = new URL(mediaUrl, window.location.href).href;
    if (audio.src !== absolute) {
      audio.src = mediaUrl;
      state.filmstripSrc = null;
    }
    audio.hidden = false;
    clearFilmstrip("Score only · no picture track");
    setScoreTrack(true, filmName(job.prompt));
    $("#edit-deck").hidden = false;
    if (state.filmstripSrc !== absolute) {
      state.filmstripSrc = absolute;
      audio.addEventListener(
        "loadedmetadata",
        () => {
          renderRuler(audio.duration || 0);
          updatePlayhead();
          renderTimeline();
        },
        { once: true }
      );
    }
  } else {
    image.hidden = true;
    audio.hidden = true;
    image.removeAttribute("src");
    audio.removeAttribute("src");
    const absolute = new URL(mediaUrl, window.location.href).href;
    if (video.src !== absolute) {
      video.src = mediaUrl;
      state.filmstripSrc = null;
    }
    video.hidden = false;
    // Keep M1 preview scrubber off while watching picture; arranged music clips stay on the track.
    setScoreTrack(false);
    $("#edit-deck").hidden = false;
    if (timelineItems("video").length === 0 && state.filmstripSrc !== absolute) {
      captureFilmstrip(mediaUrl);
    } else if (timelineItems("video").length > 0) {
      $("#filmstrip").hidden = true;
      const duration = Number(job.duration_seconds) || video.duration || 0;
      if (duration) renderRuler(duration);
    }
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
    const dryEnv =
      job.media_type === "music"
        ? "MUREKA_DRY_RUN"
        : job.media_type === "image"
          ? "SEEDREAM_DRY_RUN"
          : "SEEDANCE_DRY_RUN";
    $("#notice-body").textContent =
      `Live rendering is off, so the agent stopped after planning. Set ${dryEnv} to false and run it again to get the file.`;
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
  $("#job-ratio").hidden = job.media_type === "music";
  $("#job-ratio").textContent = job.aspect_ratio;
  $("#job-duration").hidden = job.media_type !== "video";
  $("#job-duration").textContent = job.duration_seconds ? `${job.duration_seconds}s` : "";
  $("#job-status").textContent = job.status;
  $("#job-status").className = `badge is-${job.status}`;
  $("#stage-message").textContent = job.message || "The agent is working on it.";

  bar.style.scale = `${Math.max(progress, 4) / 100} 1`;
  bar.dataset.progress = progress;
  $("#progress").setAttribute("aria-valuenow", String(progress));

  const canvasLabelBase = terminal ? (job.status === "complete" ? "Result" : job.status) : "Rendering";
  const canvasLabel = $("#canvas-label");
  canvasLabel.dataset.base = canvasLabelBase;
  canvasLabel.textContent = state.currentProject
    ? `${state.currentProject.title} \u00b7 ${canvasLabelBase}`
    : canvasLabelBase;
  $("#download-button").disabled = !job.media_url;
  $("#download-label").textContent =
    job.media_type === "image"
      ? "Download image"
      : job.media_type === "music"
        ? "Download music"
        : "Download video";

  renderTraces(job.traces);
  updateMedia(job);
  renderEditIdeas(job);
  updateStageState(job);
  renderTimeline();
}

function upsertLibraryJob(job) {
  if (!job?.id) return;
  const inProject = Boolean(job.project_id);
  if (inProject) {
    const others = state.projectJobs.filter((item) => item.id !== job.id);
    state.projectJobs = [job, ...others];
    if (state.currentProject?.id === job.project_id) {
      renderJobList($("#project-artifact-list"), $("#project-library-empty"), state.projectJobs, {
        removable: true,
      });
    }
  } else {
    const others = state.unassignedJobs.filter((item) => item.id !== job.id);
    state.unassignedJobs = [job, ...others];
    renderJobList($("#unassigned-list"), $("#unassigned-empty"), state.unassignedJobs, {
      assignable: true,
    });
  }
}

function renderJobList(list, empty, jobs, { removable = false, assignable = false } = {}) {
  if (!list || !empty) return;
  list.innerHTML = "";
  const visible = jobs.filter(
    (job) => job.status === "complete" || !TERMINAL_STATES.includes(job.status)
  );
  empty.hidden = visible.length > 0;
  visible.slice(0, 24).forEach((job) => list.append(makeArtifactCard(job, { removable, assignable })));
}

async function revealJobInLibrary(job) {
  upsertLibraryJob(job);
  setLibrary(true);
  if (job.project_id && state.currentProject?.id !== job.project_id) {
    // Keep current selection; the card still lands under Standalone/project on next refresh.
  }
  await Promise.all([loadHistory(), refreshLibrary()]);
  upsertLibraryJob(job);
}

async function pollJob(jobId) {
  stopPolling();
  const token = ++state.pollToken;
  state.pollJobId = jobId;
  let sawRunning = false;

  const check = async () => {
    if (token !== state.pollToken || state.pollJobId !== jobId) return null;
    try {
      const job = await api(`/api/generations/${jobId}`);
      if (token !== state.pollToken || state.pollJobId !== jobId) return null;
      // Never let a stale poll clobber a job the user just opened.
      if (state.currentJob?.id && state.currentJob.id !== jobId) return null;

      if (!TERMINAL_STATES.includes(job.status)) sawRunning = true;
      updateJobUI(job);
      upsertLibraryJob(job);

      if (TERMINAL_STATES.includes(job.status)) {
        window.clearInterval(state.pollTimer);
        state.pollTimer = null;
        state.pollJobId = null;
        await loadHistory();
        await refreshLibrary();
        if (token !== state.pollToken) return job;
        upsertLibraryJob(job);
        // Only toast when this poll watched the job finish (not when opening a completed one).
        if (sawRunning) {
          if (job.status === "complete") {
            showToast(
              job.media_type === "image"
                ? "Your image is ready."
                : job.media_type === "music"
                  ? "Your score is ready."
                  : "Your film is ready."
            );
          } else if (job.status === "planned") {
            showToast("The direction is ready. Live rendering is off.");
          } else if (job.status === "failed") {
            showToast(job.error?.message || "The render stopped before it finished.");
          }
        }
      }
      return job;
    } catch (error) {
      if (token !== state.pollToken) return null;
      window.clearInterval(state.pollTimer);
      state.pollTimer = null;
      state.pollJobId = null;
      showToast(error.message);
      return null;
    }
  };

  const first = await check();
  if (token !== state.pollToken) return;
  if (first && !TERMINAL_STATES.includes(first.status)) {
    state.pollTimer = window.setInterval(check, 1500);
  }
}

async function submitGeneration(event) {
  event.preventDefault();
  const prompt = $("#prompt").value.trim();
  if (prompt.length < MIN_PROMPT_LENGTH) {
    setPromptError(
      state.mediaType === "music"
        ? "Describe the score in at least a few words before generating."
        : "Describe the shot in at least a few words before generating."
    );
    $("#prompt").focus();
    return;
  }
  setPromptError("");
  if (!(await ensureSignedIn())) return;

  const submit = $("#generate-button");
  submit.disabled = true;
  try {
    const reference = state.mediaType === "music" ? null : $("#reference-input").files[0];
    const referencePath = await uploadReference(reference);
    const payload = {
      prompt,
      media_type: state.mediaType,
      vibe: "quiet luxury",
      aspect_ratio: $("#aspect-ratio").value,
      duration_seconds: Number($("#duration").value),
      reference_asset_id: referencePath,
    };
    if (state.currentProject) payload.project_id = state.currentProject.id;
    const job = await api("/api/generations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    openJob(job, { poll: false });
    await revealJobInLibrary(job);
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
    showToast("Refinement started.");
    openJob(job, { poll: false });
    await revealJobInLibrary(job);
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
  button.draggable = job.status === "complete" && Boolean(job.media_url);
  button.dataset.jobId = job.id;
  const title = document.createElement("strong");
  title.textContent = filmName(job.prompt);
  const meta = document.createElement("span");
  meta.textContent = `${job.media_type || "video"} · ${job.status}`;
  button.append(title, meta);
  button.addEventListener("dragstart", (event) => {
    state.dragJobId = job.id;
    event.dataTransfer.setData("text/plain", job.id);
    event.dataTransfer.effectAllowed = "copyMove";
    button.classList.add("is-dragging");
  });
  button.addEventListener("dragend", () => {
    state.dragJobId = null;
    button.classList.remove("is-dragging");
    clearDropTargets();
  });
  button.addEventListener("click", () => openJob(job));
  return button;
}

async function addJobToProject(jobId) {
  if (!state.currentProject) return;
  try {
    const result = await api(`/api/projects/${state.currentProject.id}/artifacts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId }),
    });
    state.currentProject = result.project;
    await loadProjectJobs();
    await loadUnassigned();
    showToast("Added to project.");
  } catch (error) {
    showToast(error.message);
  }
}

function makeArtifactCard(job, { removable = false, assignable = false } = {}) {
  const card = document.createElement("div");
  const running = !TERMINAL_STATES.includes(job.status);
  card.className = `artifact-card artifact-card--${job.media_type || "video"}${
    running ? " is-running" : ""
  }`;
  const ready = job.status === "complete" && Boolean(job.output_asset_id || job.media_url);
  card.draggable = ready;
  card.dataset.jobId = job.id;
  card.tabIndex = 0;
  card.setAttribute("role", "button");

  const main = document.createElement("div");
  main.className = "artifact-card-main";
  const kind = document.createElement("span");
  kind.className = "artifact-kind";
  kind.textContent = job.media_type || "video";
  const title = document.createElement("strong");
  title.textContent = filmName(job.prompt);
  const meta = document.createElement("span");
  meta.className = "artifact-meta";
  meta.textContent =
    job.status === "complete" ? "Ready" : job.status === "failed" ? "Failed" : job.status;
  main.append(kind, title, meta);
  card.append(main);

  const openCard = () => openJob(job);
  main.addEventListener("click", openCard);
  card.addEventListener("keydown", (event) => {
    if (event.target !== card) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openCard();
    }
  });

  const actions = document.createElement("div");
  actions.className = "artifact-actions";
  let hasActions = false;

  if (ready && state.currentProject) {
    const mediaType = job.media_type || "video";
    if (mediaType === "video" || mediaType === "music") {
      const addToTrack = document.createElement("button");
      addToTrack.type = "button";
      addToTrack.className = "artifact-action";
      addToTrack.textContent = mediaType === "music" ? "Add to M1" : "Add to V1";
      addToTrack.addEventListener("click", async (event) => {
        event.stopPropagation();
        await addJobToTimeline(job.id, mediaType);
      });
      actions.append(addToTrack);
      hasActions = true;
    } else if (assignable) {
      const addToProject = document.createElement("button");
      addToProject.type = "button";
      addToProject.className = "artifact-action";
      addToProject.textContent = "Add to project";
      addToProject.addEventListener("click", async (event) => {
        event.stopPropagation();
        await addJobToProject(job.id);
      });
      actions.append(addToProject);
      hasActions = true;
    }
  }

  if (removable) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "artifact-action artifact-action--remove";
    remove.textContent = "Remove";
    remove.addEventListener("click", async (event) => {
      event.stopPropagation();
      await removeArtifactFromProject(job.id);
    });
    actions.append(remove);
    hasActions = true;
  }

  if (hasActions) card.append(actions);

  card.addEventListener("dragstart", (event) => {
    state.dragJobId = job.id;
    event.dataTransfer.setData("text/plain", job.id);
    event.dataTransfer.effectAllowed = "copyMove";
    card.classList.add("is-dragging");
  });
  card.addEventListener("dragend", () => {
    state.dragJobId = null;
    card.classList.remove("is-dragging");
    clearDropTargets();
  });
  return card;
}

function makeProjectCard(project) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "project-card";
  if (state.currentProject?.id === project.id) card.classList.add("is-active");
  card.dataset.projectId = project.id;
  card.dataset.drop = "project";
  const title = document.createElement("strong");
  title.textContent = project.title;
  const meta = document.createElement("span");
  const artifacts = project.artifact_count ?? (project.artifact_ids || []).length;
  const clips = project.timeline_count ?? (project.timeline?.items || []).length;
  meta.textContent = `${artifacts} · ${clips} on timeline`;
  card.append(title, meta);
  card.addEventListener("click", () => openProject(project));
  bindProjectDropTarget(card, project.id);
  return card;
}

function clearDropTargets() {
  $$(".is-drop-target").forEach((el) => el.classList.remove("is-drop-target"));
}

function bindProjectDropTarget(element, projectId) {
  element.addEventListener("dragover", (event) => {
    if (!state.dragJobId) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    element.classList.add("is-drop-target");
  });
  element.addEventListener("dragleave", () => element.classList.remove("is-drop-target"));
  element.addEventListener("drop", async (event) => {
    event.preventDefault();
    element.classList.remove("is-drop-target");
    const jobId = event.dataTransfer.getData("text/plain") || state.dragJobId;
    if (!jobId) return;
    try {
      await api(`/api/projects/${projectId}/artifacts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId }),
      });
      showToast("Added to project.");
      await loadProjects();
      await loadUnassigned();
      if (state.currentProject?.id === projectId) await loadProjectJobs();
    } catch (error) {
      showToast(error.message);
    }
  });
}

function bindTimelineDropTarget() {
  ["video-lane", "music-lane"].forEach((id) => {
    const lane = document.getElementById(id);
    if (!lane || lane.dataset.bound === "true") return;
    lane.dataset.bound = "true";
    const accept = lane.dataset.drop;
    lane.addEventListener("dragover", (event) => {
      if (!state.dragJobId || !state.currentProject) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      lane.classList.add("is-drop-target");
    });
    lane.addEventListener("dragleave", () => lane.classList.remove("is-drop-target"));
    lane.addEventListener("drop", async (event) => {
      event.preventDefault();
      lane.classList.remove("is-drop-target");
      const jobId = event.dataTransfer.getData("text/plain") || state.dragJobId;
      if (!jobId || !state.currentProject) return;
      await addJobToTimeline(jobId, accept);
    });
  });
}

async function resolveJob(jobId) {
  let job =
    state.projectJobs.find((item) => item.id === jobId) ||
    state.unassignedJobs.find((item) => item.id === jobId) ||
    state.currentJob;
  if (!job || job.id !== jobId) {
    job = await api(`/api/generations/${jobId}`);
  }
  return job;
}

async function addJobToTimeline(jobId, trackHint = null) {
  if (!state.currentProject) return;
  let job;
  try {
    job = await resolveJob(jobId);
  } catch (error) {
    showToast(error.message);
    return;
  }
  if (job.status !== "complete" || !(job.output_asset_id || job.media_url)) {
    showToast("Only finished artifacts can go on the timeline.");
    return;
  }
  const mediaType = job.media_type || "video";
  if (mediaType !== "video" && mediaType !== "music") {
    showToast("Only video and music can go on the timeline.");
    return;
  }
  if (trackHint && trackHint !== mediaType) {
    showToast(
      mediaType === "music"
        ? "Drop music on the M1 track."
        : "Drop video on the V1 track."
    );
    return;
  }
  const items = [...(state.currentProject.timeline?.items || [])];
  if (items.some((item) => item.job_id === jobId)) {
    showToast("That clip is already on the timeline.");
    return;
  }
  items.push({
    job_id: job.id,
    asset_id: job.output_asset_id,
    media_type: mediaType,
    label: filmName(job.prompt),
    duration_seconds: job.duration_seconds,
  });
  try {
    const project = await api(`/api/projects/${state.currentProject.id}/timeline`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });
    state.currentProject = project;
    renderTimeline();
    await loadProjectJobs();
    await loadUnassigned();
    showToast(mediaType === "music" ? "Music added to M1." : "Clip added to V1.");
  } catch (error) {
    showToast(error.message);
  }
}

async function removeTimelineItem(itemId) {
  if (!state.currentProject) return;
  const items = (state.currentProject.timeline?.items || []).filter((item) => item.id !== itemId);
  try {
    const project = await api(`/api/projects/${state.currentProject.id}/timeline`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });
    state.currentProject = project;
    renderTimeline();
  } catch (error) {
    showToast(error.message);
  }
}

async function reorderTimelineItem(draggedId, targetId) {
  if (!state.currentProject || !draggedId || draggedId === targetId) return;
  const current = [...(state.currentProject.timeline?.items || [])];
  const from = current.findIndex((entry) => entry.id === draggedId);
  const to = current.findIndex((entry) => entry.id === targetId);
  if (from < 0 || to < 0) return;
  // Keep video and music tracks independent — only reorder within the same kind.
  if (current[from].media_type !== current[to].media_type) {
    showToast("Clips stay on their own track.");
    return;
  }
  const [moved] = current.splice(from, 1);
  current.splice(to, 0, moved);
  try {
    const project = await api(`/api/projects/${state.currentProject.id}/timeline`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: current }),
    });
    state.currentProject = project;
    renderTimeline();
  } catch (error) {
    showToast(error.message);
  }
}

function clipDuration(item) {
  const value = Number(item.duration_seconds);
  return Number.isFinite(value) && value > 0 ? value : 10;
}

function makeTimelineClip(item, index, totalDuration) {
  const clip = document.createElement("div");
  clip.className = `timeline-clip timeline-clip--${item.media_type || "video"}`;
  clip.draggable = true;
  clip.dataset.itemId = item.id;
  clip.dataset.jobId = item.job_id;
  const widthPct = Math.max(12, (clipDuration(item) / Math.max(totalDuration, 0.001)) * 100);
  clip.style.flex = `${widthPct} 1 0`;
  if (state.currentJob?.id === item.job_id) clip.classList.add("is-active");

  const label = document.createElement("strong");
  label.textContent = item.label || `Clip ${index + 1}`;
  const meta = document.createElement("span");
  meta.textContent =
    item.media_type === "music"
      ? "music"
      : `${Math.round(clipDuration(item))}s`;
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "timeline-clip-remove";
  remove.setAttribute("aria-label", "Remove from timeline");
  remove.textContent = "×";
  remove.addEventListener("click", (event) => {
    event.stopPropagation();
    removeTimelineItem(item.id);
  });
  clip.append(label, meta, remove);

  clip.addEventListener("dragstart", (event) => {
    event.dataTransfer.setData("application/x-timeline-item", item.id);
    event.dataTransfer.effectAllowed = "move";
    clip.classList.add("is-dragging");
  });
  clip.addEventListener("dragend", () => clip.classList.remove("is-dragging"));
  clip.addEventListener("dragover", (event) => {
    if (![...event.dataTransfer.types].includes("application/x-timeline-item")) return;
    event.preventDefault();
    clip.classList.add("is-drop-target");
  });
  clip.addEventListener("dragleave", () => clip.classList.remove("is-drop-target"));
  clip.addEventListener("drop", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    clip.classList.remove("is-drop-target");
    const draggedId = event.dataTransfer.getData("application/x-timeline-item");
    await reorderTimelineItem(draggedId, item.id);
  });
  clip.addEventListener("click", async () => {
    try {
      const job = await api(`/api/generations/${item.job_id}`);
      openJob(job);
    } catch (error) {
      showToast(error.message);
    }
  });
  return clip;
}

function renderTimeline() {
  const videoClips = $("#video-clips");
  const musicClips = $("#music-clips");
  const videoPlaceholder = $("#video-placeholder");
  const musicPlaceholder = $("#score-placeholder");
  const mergeButton = $("#merge-button");
  if (!videoClips || !musicClips) return;

  const videos = timelineItems("video");
  const music = timelineItems("music");
  const videoTotal = videos.reduce((sum, item) => sum + clipDuration(item), 0) || 1;
  const musicTotal = music.reduce((sum, item) => sum + clipDuration(item), 0) || videoTotal;

  videoClips.innerHTML = "";
  musicClips.innerHTML = "";
  videos.forEach((item, index) => videoClips.append(makeTimelineClip(item, index, videoTotal)));
  music.forEach((item, index) => musicClips.append(makeTimelineClip(item, index, musicTotal)));

  if (videoPlaceholder) videoPlaceholder.hidden = videos.length > 0;
  if (musicPlaceholder) musicPlaceholder.hidden = music.length > 0;
  $("#filmstrip").hidden = videos.length > 0 || !$("#result-video")?.src || $("#result-video").hidden;
  $("#score-clip").hidden = music.length > 0 || $("#result-audio")?.hidden !== false;

  const trackVideo = $("#track-video");
  const trackScore = $("#track-score");
  if (trackVideo) trackVideo.classList.toggle("track--idle", videos.length === 0 && $("#filmstrip").hidden);
  if (trackScore) {
    trackScore.classList.toggle("track--idle", music.length === 0 && $("#score-clip").hidden);
    trackScore.classList.toggle("track--music", music.length > 0 || !$("#score-clip").hidden);
  }

  if (videos.length > 0) renderRuler(videoTotal);
  else if (music.length > 0) renderRuler(musicTotal);

  if (mergeButton) {
    mergeButton.disabled = videos.length < 2;
    mergeButton.title =
      videos.length < 2
        ? "Add at least two videos on V1 to merge into a new clip"
        : "Merge V1 clips into a new independent video";
  }
}

async function mergeTimeline() {
  if (!state.currentProject) return;
  const button = $("#merge-button");
  button.disabled = true;
  try {
    const result = await api(`/api/projects/${state.currentProject.id}/merge`, {
      method: "POST",
    });
    state.currentProject = result.project;
    state.currentJob = result.job;
    renderTimeline();
    updateJobUI(result.job);
    await loadProjectJobs();
    showToast("Created a new merged video. Sources stay in the library.");
  } catch (error) {
    showToast(error.message);
  } finally {
    renderTimeline();
  }
}

async function removeArtifactFromProject(jobId) {
  if (!state.currentProject) return;
  try {
    const result = await api(
      `/api/projects/${state.currentProject.id}/artifacts/${jobId}`,
      { method: "DELETE" }
    );
    state.currentProject = result.project;
    renderTimeline();
    await loadProjectJobs();
    await loadUnassigned();
    await loadHistory();
  } catch (error) {
    showToast(error.message);
  }
}

async function refreshLibrary() {
  await Promise.all([loadProjects(), loadUnassigned(), loadProjectJobs()]);
}

async function loadProjects() {
  try {
    const { items } = await api("/api/projects");
    state.projects = items;
    const grid = $("#project-grid");
    const empty = $("#projects-empty");
    grid.innerHTML = "";
    empty.hidden = items.length > 0;
    items.forEach((project) => grid.append(makeProjectCard(project)));
    syncProjectChrome();
  } catch {
    $("#projects-empty").hidden = false;
  }
}

async function loadUnassigned() {
  try {
    const { items } = await api("/api/generations?unassigned=true");
    state.unassignedJobs = items;
    renderJobList($("#unassigned-list"), $("#unassigned-empty"), items, { assignable: true });
  } catch {
    $("#unassigned-empty").hidden = false;
  }
}

async function loadProjectJobs() {
  const list = $("#project-artifact-list");
  const empty = $("#project-library-empty");
  if (!list || !empty) return;
  if (!state.currentProject) {
    state.projectJobs = [];
    list.innerHTML = "";
    empty.hidden = false;
    return;
  }
  try {
    const { items } = await api(`/api/generations?project_id=${state.currentProject.id}`);
    state.projectJobs = items;
    renderJobList(list, empty, items, { removable: true });
  } catch {
    empty.hidden = false;
  }
}

async function openProject(project) {
  try {
    state.currentProject = await api(`/api/projects/${project.id}`);
  } catch {
    state.currentProject = project;
  }
  setLibrary(true);
  syncProjectChrome();
  $("#edit-deck").hidden = false;
  renderTimeline();
  await loadProjectJobs();
  await loadHistory();
  if ($("#app").dataset.mode !== "workspace") setMode("home");
}

async function clearProject() {
  state.currentProject = null;
  syncProjectChrome();
  renderTimeline();
  await loadProjectJobs();
  await loadHistory();
  if ($("#app").dataset.mode !== "workspace") setMode("home");
}

async function createProject(event) {
  event.preventDefault();
  if (!(await ensureSignedIn())) return;
  const title = $("#project-title").value.trim();
  if (!title) {
    showToast("Give the project a name.");
    $("#project-title").focus();
    return;
  }
  const button = $("#project-create-button");
  button.disabled = true;
  try {
    const project = await api("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    $("#project-title").value = "";
    await loadProjects();
    await openProject(project);
    showToast("Project created.");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function loadHistory() {
  try {
    const path = state.currentProject
      ? `/api/generations?project_id=${state.currentProject.id}`
      : "/api/generations";
    const { items } = await api(path);
    const list = $("#history-list");
    list.innerHTML = "";
    if (!items.length) {
      $("#history").hidden = true;
      return;
    }
    $("#history").hidden = false;
    items.slice(0, 8).forEach((job) => list.append(makeHistoryItem(job)));
  } catch {
    $("#history").hidden = true;
  }
}

async function loadConfig() {
  try {
    const response = await fetch("/api/config");
    state.config = await response.json();
    if (!response.ok) throw new Error("config unavailable");
    const live =
      state.mediaType === "image"
        ? state.config.live_image_generation
        : state.mediaType === "music"
          ? state.config.live_music_generation
          : state.config.live_generation;
    const tracing = state.config.langfuse_ready ? " · langfuse" : "";
    const authLabel = state.config.clerk_enabled ? " · clerk" : "";
    $("#config-status").textContent = `${live ? "live" : "preview"}${tracing}${authLabel}`;
    updateModelHint();
    renderAuthControls();
    if (state.config.clerk_enabled && state.config.clerk_publishable_key) {
      try {
        await initClerk(state.config.clerk_publishable_key);
      } catch (error) {
        console.error(error);
        showToast("Clerk failed to load. Check your publishable key.");
        renderAuthControls();
      }
    }
  } catch {
    $("#config-status").textContent = "offline";
  }
}

function startNewRender() {
  stopPolling();
  state.mediaRefreshToken += 1;
  state.currentJob = null;
  setPromptError("");
  setMode("home");
  $("#prompt").focus();
}

function bindEvents() {
  $("#generation-form").addEventListener("submit", submitGeneration);
  $("#refine-form").addEventListener("submit", refine);
  $("#project-create-form").addEventListener("submit", createProject);

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

  $("#home-button").addEventListener("click", startNewRender);
  $("#crumb-home").addEventListener("click", startNewRender);
  $("#project-chip").addEventListener("click", () => {
    setLibrary(true);
    if (state.currentProject) setMode("home");
  });
  $("#clear-project-button").addEventListener("click", clearProject);
  $("#new-button").addEventListener("click", startNewRender);
  $("#notice-action").addEventListener("click", startNewRender);
  $("#merge-button").addEventListener("click", mergeTimeline);
  $("#library-toggle").addEventListener("click", () => {
    setLibrary($("#app").dataset.library !== "open");
  });

  $("#rail-toggle").addEventListener("click", () => {
    setRail($("#app").dataset.rail !== "open");
  });

  $("#download-button").addEventListener("click", async () => {
    if (!state.currentJob?.id) return;
    try {
      // Refresh the short-lived signed media URL before opening it.
      const job = await api(`/api/generations/${state.currentJob.id}`);
      state.currentJob = job;
      updateJobUI(job);
      if (job.media_url) window.open(job.media_url, "_blank", "noopener");
    } catch (error) {
      showToast(error.message);
    }
  });

  $("#sign-in-button").addEventListener("click", () => {
    state.clerk?.openSignIn?.();
  });

  bindTimelineControls();
  bindTimelineDropTarget();
}

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  setMediaType("video");
  setMode("home");
  // Persistent sidebar on desktop; overlay, closed by default, on narrow screens.
  setLibrary(window.innerWidth > 1100);
  clearFilmstrip();
  await loadConfig();
  await refreshLibrary();
  await loadHistory();
});
