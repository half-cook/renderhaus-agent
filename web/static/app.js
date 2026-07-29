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
  config: null,
  filmstripToken: 0,
  filmstripSrc: null,
  scrubbing: false,
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
  if (!job?.media_url || job.media_type === "image") {
    deck.hidden = true;
    return;
  }
  deck.hidden = false;
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
  strip.innerHTML = "";
  strip.classList.add("is-empty");
  strip.classList.remove("is-loading");
  strip.dataset.note = note;
  $("#timeline-ruler").innerHTML = "";
  $("#timeline-clock").textContent = "0:00 / 0:00";
  $("#playhead").style.left = "60px";
  state.filmstripSrc = null;
}

function setScoreTrack(active, label = "Score") {
  const track = $("#track-score");
  const clip = $("#score-clip");
  const placeholder = $("#score-placeholder");
  track.classList.toggle("track--idle", !active);
  track.classList.toggle("track--music", active);
  track.setAttribute("aria-disabled", String(!active));
  clip.hidden = !active;
  placeholder.hidden = active;
  $("#score-label").textContent = label;
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

function updatePlayheadFromMedia(media) {
  const body = $("#timeline-body");
  const strip = media?.tagName === "AUDIO" ? $("#score-clip") : $("#filmstrip");
  if (!media?.duration || media.hidden || !strip || strip.hidden) return;
  const ratio = Math.min(1, Math.max(0, media.currentTime / media.duration));
  const laneLeft = strip.getBoundingClientRect().left - body.getBoundingClientRect().left;
  const laneWidth = strip.getBoundingClientRect().width;
  $("#playhead").style.left = `${laneLeft + ratio * laneWidth}px`;
  $("#timeline-clock").textContent = `${formatClock(media.currentTime)} / ${formatClock(media.duration)}`;
  strip.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
  strip.setAttribute("aria-valuemax", "100");
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

async function captureFilmstrip(mediaUrl) {
  const token = ++state.filmstripToken;
  const strip = $("#filmstrip");
  strip.innerHTML = "";
  strip.classList.remove("is-empty");
  strip.classList.add("is-loading");
  strip.dataset.note = "Pulling frames…";

  const probe = document.createElement("video");
  probe.muted = true;
  probe.playsInline = true;
  probe.preload = "auto";
  probe.src = mediaUrl;

  try {
    await new Promise((resolve, reject) => {
      probe.addEventListener("loadedmetadata", resolve, { once: true });
      probe.addEventListener("error", () => reject(new Error("Could not read video frames.")), {
        once: true,
      });
    });
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
      const time = duration <= 0 ? 0 : (index / Math.max(count - 1, 1)) * Math.max(duration - 0.05, 0);
      await new Promise((resolve, reject) => {
        const onSeeked = () => {
          probe.removeEventListener("seeked", onSeeked);
          resolve();
        };
        probe.addEventListener("seeked", onSeeked);
        probe.addEventListener(
          "error",
          () => {
            probe.removeEventListener("seeked", onSeeked);
            reject(new Error("Frame seek failed."));
          },
          { once: true }
        );
        try {
          probe.currentTime = time;
        } catch (error) {
          probe.removeEventListener("seeked", onSeeked);
          reject(error);
        }
      });
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
  } catch {
    if (token !== state.filmstripToken) return;
    clearFilmstrip("Frames unavailable for this clip");
  } finally {
    probe.removeAttribute("src");
    probe.load();
  }
}

function seekFromClientX(clientX) {
  const video = $("#result-video");
  const audio = $("#result-audio");
  const media = !video.hidden && video.duration ? video : !audio.hidden && audio.duration ? audio : null;
  const strip = media?.tagName === "AUDIO" ? $("#score-clip") : $("#filmstrip");
  if (!media || !strip || strip.hidden) return;
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

function updateMedia(job) {
  const video = $("#result-video");
  const image = $("#result-image");
  const audio = $("#result-audio");
  const stage = $("#stage");
  const mediaUrl = job.media_url;
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
    $("#edit-deck").hidden = true;
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
    $("#edit-deck").hidden = true;
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
    setScoreTrack(false);
    $("#edit-deck").hidden = false;
    if (state.filmstripSrc !== absolute) {
      captureFilmstrip(mediaUrl);
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

  $("#canvas-label").textContent = terminal
    ? job.status === "complete"
      ? "Result"
      : job.status
    : "Rendering";
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
    setPromptError(
      state.mediaType === "music"
        ? "Describe the score in at least a few words before generating."
        : "Describe the shot in at least a few words before generating."
    );
    $("#prompt").focus();
    return;
  }
  setPromptError("");

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
        : state.mediaType === "music"
          ? state.config.live_music_generation
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

  bindTimelineControls();
}

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  setMediaType("video");
  setMode("home");
  clearFilmstrip();
  await Promise.all([loadConfig(), loadHistory()]);
});
