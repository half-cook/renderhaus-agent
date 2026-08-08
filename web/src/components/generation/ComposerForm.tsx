"use client";

import { useClerk, useAuth } from "@clerk/nextjs";
import { Music, Video, Image as ImageIcon, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useApiClient } from "@/lib/api/useApiClient";
import type { AspectRatio, MediaType } from "@/lib/api/types";
import { ApiError } from "@/lib/api/types";
import { useGenerationStore } from "@/lib/generation/store";

const MEDIA_TABS: { key: MediaType; label: string; icon: typeof Video }[] = [
  { key: "video", label: "Video", icon: Video },
  { key: "image", label: "Image", icon: ImageIcon },
  { key: "music", label: "Music", icon: Music },
];

const ASPECT_RATIOS: AspectRatio[] = ["16:9", "9:16", "1:1"];
const DURATIONS = [5, 10, 12];
const MIN_PROMPT_LENGTH = 3;
const MAX_PROMPT_LENGTH = 4000;

const PLACEHOLDERS: Record<MediaType, string> = {
  video:
    "A chrome perfume bottle drifting through a sunlit concrete gallery, slow dolly in, dust in the light…",
  image: "A chrome perfume bottle on raw concrete, soft daylight, quiet luxury product still.",
  music: "Soft analog pads, restrained percussion, quiet luxury.",
};

function modelFor(mediaType: MediaType, config: ReturnType<typeof useGenerationStore.getState>["config"]): string | null {
  if (!config) return null;
  if (mediaType === "video") return config.video_model;
  if (mediaType === "image") return config.image_model;
  return config.music_model;
}

// Video/Image/Music prompt composer -- mirrors the old static frontend's
// generation form (see plan §6.1), Production is deliberately not a mode
// here since it now has its own IconRail tab (ProductionComposer).
export function ComposerForm() {
  const { isLoaded, isSignedIn } = useAuth();
  const { openSignIn } = useClerk();
  const api = useApiClient();

  const mediaType = useGenerationStore((s) => (s.mediaType === "production" ? "video" : s.mediaType));
  const setMediaType = useGenerationStore((s) => s.setMediaType);
  const prompt = useGenerationStore((s) => s.prompt);
  const setPrompt = useGenerationStore((s) => s.setPrompt);
  const aspectRatio = useGenerationStore((s) => s.aspectRatio);
  const setAspectRatio = useGenerationStore((s) => s.setAspectRatio);
  const durationSeconds = useGenerationStore((s) => s.durationSeconds);
  const setDurationSeconds = useGenerationStore((s) => s.setDurationSeconds);
  const referenceAssetId = useGenerationStore((s) => s.referenceAssetId);
  const referenceFileName = useGenerationStore((s) => s.referenceFileName);
  const setReferenceAsset = useGenerationStore((s) => s.setReferenceAsset);
  const clearReference = useGenerationStore((s) => s.clearReference);
  const config = useGenerationStore((s) => s.config);
  const setConfig = useGenerationStore((s) => s.setConfig);
  const currentProjectId = useGenerationStore((s) => s.currentProjectId);
  const upsertJob = useGenerationStore((s) => s.upsertJob);
  const setActiveJob = useGenerationStore((s) => s.setActiveJob);

  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [uploadingReference, setUploadingReference] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (config) return;
    api
      .getConfig()
      .then(setConfig)
      .catch(() => {
        // Non-fatal -- the model-hint line just stays hidden if config fails to load.
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fetch config once on mount
  }, []);

  async function handleReferenceChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploadingReference(true);
    setError(null);
    try {
      const { asset_id } = await api.uploadReferenceAsset(file);
      setReferenceAsset(asset_id, file.name);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not upload the reference image.");
    } finally {
      setUploadingReference(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    const trimmed = prompt.trim();
    if (trimmed.length < MIN_PROMPT_LENGTH) {
      setError(`Write a bit more -- at least ${MIN_PROMPT_LENGTH} characters.`);
      return;
    }

    if (!isLoaded) {
      setError("Sign in is still loading. Try again in a moment.");
      return;
    }
    if (!isSignedIn) {
      openSignIn();
      return;
    }

    setSubmitting(true);
    try {
      const job = await api.createGeneration({
        prompt: trimmed,
        media_type: mediaType,
        aspect_ratio: mediaType === "music" ? undefined : aspectRatio,
        duration_seconds: mediaType === "video" ? durationSeconds : undefined,
        reference_asset_id: mediaType === "music" ? null : referenceAssetId,
        project_id: currentProjectId ?? undefined,
      });
      upsertJob(job);
      setActiveJob(job.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The request failed. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  const showAspectRatio = mediaType !== "music";
  const showDuration = mediaType === "video";
  const showReference = mediaType !== "music";
  const model = modelFor(mediaType, config);

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 p-4">
      <div role="tablist" className="flex gap-1 rounded-md bg-neutral-900 p-1">
        {MEDIA_TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={mediaType === key}
            onClick={() => setMediaType(key)}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded py-1.5 text-xs ${
              mediaType === key
                ? "bg-neutral-800 text-neutral-100"
                : "text-neutral-500 hover:text-neutral-300"
            }`}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      <textarea
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        rows={4}
        maxLength={MAX_PROMPT_LENGTH}
        placeholder={PLACEHOLDERS[mediaType]}
        className="resize-none rounded-md border border-neutral-800 bg-neutral-900 p-3 text-sm text-neutral-200 placeholder:text-neutral-600 focus:border-neutral-600 focus:outline-none"
      />

      <div className="flex flex-wrap items-center gap-2">
        {showAspectRatio && (
          <select
            value={aspectRatio}
            onChange={(event) => setAspectRatio(event.target.value as AspectRatio)}
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs text-neutral-300"
          >
            {ASPECT_RATIOS.map((ratio) => (
              <option key={ratio} value={ratio}>
                {ratio}
              </option>
            ))}
          </select>
        )}
        {showDuration && (
          <select
            value={durationSeconds}
            onChange={(event) => setDurationSeconds(Number(event.target.value))}
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs text-neutral-300"
          >
            {DURATIONS.map((seconds) => (
              <option key={seconds} value={seconds}>
                {seconds}s
              </option>
            ))}
          </select>
        )}
        {showReference && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={handleReferenceChange}
            />
            {referenceFileName ? (
              <span className="flex items-center gap-1 rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs text-neutral-300">
                {referenceFileName}
                <button type="button" onClick={clearReference} className="text-neutral-500 hover:text-neutral-200">
                  <X size={12} />
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploadingReference}
                className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs text-neutral-400 hover:text-neutral-200 disabled:opacity-50"
              >
                {uploadingReference ? "Uploading…" : "Reference"}
              </button>
            )}
          </>
        )}
      </div>

      {model && <p className="text-[11px] text-neutral-600">{MEDIA_TABS.find((t) => t.key === mediaType)?.label} · {model}</p>}

      {error && (
        <p role="alert" className="text-xs text-red-400">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="rounded-md bg-indigo-500 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50"
      >
        {submitting ? "Starting…" : `Generate ${mediaType}`}
      </button>
    </form>
  );
}
