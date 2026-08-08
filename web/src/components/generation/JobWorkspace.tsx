"use client";

import { useCallback, useEffect, useState } from "react";
import { useApiClient } from "@/lib/api/useApiClient";
import { usePoll } from "@/lib/api/usePolling";
import { TERMINAL_JOB_STATES, type Job } from "@/lib/api/types";
import { useGenerationStore, selectActiveJob } from "@/lib/generation/store";
import { useAddToTimeline } from "./useAddToTimeline";

const POLL_INTERVAL_MS = 1500;

function computeProgress(job: Job, previous: number): number {
  if (TERMINAL_JOB_STATES.has(job.status)) return 100;
  return Math.min(92, Math.max(job.progress || 8, previous + 3));
}

function LoadingResult({ job }: { job: Job }) {
  const progress = useSyntheticProgress(job);
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
      <div className="h-32 w-full max-w-xs animate-pulse rounded-lg bg-neutral-900" />
      <p className="text-sm text-neutral-400">{job.message || "The agent is working on it."}</p>
      <div className="h-1 w-full max-w-xs overflow-hidden rounded-full bg-neutral-900">
        <div
          className="h-full bg-indigo-500 transition-[width] duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

// Ref writes during render are disallowed under React 19's stricter
// react-hooks/refs rule, and setState-in-effect is discouraged for
// synchronous derivations (react-hooks/set-state-in-effect) -- React's own
// documented pattern for "ratchet a value across renders" is calling
// setState conditionally during render itself, not in an effect:
// https://react.dev/reference/react/useState#storing-information-from-previous-renders
function useSyntheticProgress(job: Job): number {
  const [state, setState] = useState({ jobId: job.id, progress: computeProgress(job, 8) });

  if (state.jobId !== job.id) {
    const progress = computeProgress(job, 8);
    setState({ jobId: job.id, progress });
    return progress;
  }

  const progress = computeProgress(job, state.progress);
  if (progress !== state.progress) {
    setState({ jobId: job.id, progress });
  }
  return progress;
}

function NoticeResult({ job, onRestart }: { job: Job; onRestart: () => void }) {
  const isPlanned = job.status === "planned";
  const dryRunFlag =
    job.media_type === "video" ? "SEEDANCE_DRY_RUN" : job.media_type === "image" ? "SEEDREAM_DRY_RUN" : "MUREKA_DRY_RUN";
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
      <p className="text-sm font-medium text-neutral-200">
        {isPlanned ? "The direction is ready" : "The render stopped early"}
      </p>
      <p className="max-w-xs text-xs text-neutral-500">
        {isPlanned
          ? `Live rendering is off (${dryRunFlag}=true). Turn it on to create the asset.`
          : job.error?.message || "The render stopped before it finished."}
      </p>
      <button
        onClick={onRestart}
        className="rounded-md bg-neutral-800 px-3 py-1.5 text-xs text-neutral-200 hover:bg-neutral-700"
      >
        {isPlanned ? "Write another prompt" : "Try a different prompt"}
      </button>
    </div>
  );
}

function MediaResult({ job }: { job: Job }) {
  const api = useApiClient();
  const upsertJob = useGenerationStore((s) => s.upsertJob);

  const handleError = useCallback(() => {
    // media_url is a ~15min-TTL signed URL -- if it's expired, refetch the
    // job for a fresh one rather than caching/retrying the same stale URL.
    // job re-renders reactively from the store once upsertJob lands, no
    // local state needed here.
    api.getGeneration(job.id).then(upsertJob).catch(() => {});
  }, [api, job.id, upsertJob]);

  const src = job.media_url;
  if (!src) return null;

  if (job.media_type === "video") {
    return (
      <video
        key={src}
        src={src}
        controls
        autoPlay
        className="max-h-full max-w-full rounded-lg bg-black"
        onError={handleError}
      />
    );
  }
  if (job.media_type === "image") {
    // next/image needs a known, stable remote domain -- src here is a
    // signed S3 URL that's short-lived and unpredictable per job, not a
    // good fit for its optimization pipeline.
    // eslint-disable-next-line @next/next/no-img-element
    return <img key={src} src={src} alt={job.prompt} className="max-h-full max-w-full rounded-lg" onError={handleError} />;
  }
  return (
    <div className="flex w-full max-w-sm flex-col items-center gap-3 rounded-lg bg-neutral-900 p-6">
      <audio key={src} src={src} controls autoPlay className="w-full" onError={handleError} />
    </div>
  );
}

// Post-submit view: polls the active job until terminal, renders
// loading/notice/media states.
export function JobWorkspace() {
  const api = useApiClient();
  const activeJob = useGenerationStore(selectActiveJob);
  const activeJobId = useGenerationStore((s) => s.activeJobId);
  const upsertJob = useGenerationStore((s) => s.upsertJob);
  const setActiveJob = useGenerationStore((s) => s.setActiveJob);
  const addToTimeline = useAddToTimeline();
  // "Added" flag resets when the job changes -- same render-time-adjustment
  // pattern as useSyntheticProgress (see comment there), not an effect.
  const [addedState, setAddedState] = useState({ jobId: activeJobId, added: false });
  const addedToTimeline = addedState.jobId === activeJobId && addedState.added;

  const { data, error } = usePoll(
    () => api.getGeneration(activeJobId as string),
    {
      intervalMs: POLL_INTERVAL_MS,
      isTerminal: (job) => TERMINAL_JOB_STATES.has(job.status),
      enabled: Boolean(activeJobId),
    },
  );

  useEffect(() => {
    if (data) upsertJob(data);
  }, [data, upsertJob]);

  if (!activeJob) return null;

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center text-sm text-red-400">
        {error.message}
      </div>
    );
  }

  const isLoading = !TERMINAL_JOB_STATES.has(activeJob.status);
  const canAddToTimeline =
    activeJob.status === "complete" && activeJob.media_type !== "image" && Boolean(activeJob.media_url);

  return (
    <>
      <div className="flex aspect-video shrink-0 flex-col items-center justify-center overflow-hidden bg-neutral-950 p-4">
        {isLoading && <LoadingResult job={activeJob} />}
        {!isLoading && activeJob.status !== "complete" && (
          <NoticeResult job={activeJob} onRestart={() => setActiveJob(null)} />
        )}
        {activeJob.status === "complete" && <MediaResult job={activeJob} />}
      </div>
      {canAddToTimeline && (
        <div className="px-4 pb-3">
          <button
            onClick={() => {
              addToTimeline(activeJob);
              setAddedState({ jobId: activeJobId, added: true });
            }}
            disabled={addedToTimeline}
            className="w-full rounded-md bg-neutral-800 py-1.5 text-xs text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
          >
            {addedToTimeline ? "Added to timeline" : `Add to ${activeJob.media_type === "music" ? "audio" : "video"} track`}
          </button>
        </div>
      )}
    </>
  );
}
