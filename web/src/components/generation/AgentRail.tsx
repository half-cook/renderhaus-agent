"use client";

import { useGenerationStore, selectActiveJob } from "@/lib/generation/store";
import { RefineComposer } from "./RefineComposer";

const STATUS_STYLES: Record<string, string> = {
  running: "text-indigo-400",
  done: "text-emerald-400",
  error: "text-red-400",
};

function prettyTitle(title: string): string {
  return title.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Job title/status/prompt/meta + the live trace log + refine composer.
// Traces update in place by trace.id -- React's keyed reconciliation
// already gives this for free (job objects from polling are the full
// current state, not deltas), no manual merge needed.
export function AgentRail() {
  const job = useGenerationStore(selectActiveJob);

  if (!job) return null;

  const title = job.prompt.split(/\s+/).slice(0, 3).join(" ") || job.id;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto border-t border-neutral-800 p-4">
      <div>
        <p className="text-sm font-medium text-neutral-100">{title}</p>
        <p className="text-xs text-neutral-500">{job.status}</p>
      </div>

      <p className="text-xs text-neutral-400">{job.prompt}</p>

      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-neutral-500">
        <span>{job.media_type}</span>
        {job.media_type !== "music" && <span>{job.aspect_ratio}</span>}
        {job.media_type === "video" && job.duration_seconds != null && (
          <span>{job.duration_seconds}s</span>
        )}
      </div>

      <div className="flex flex-col gap-2">
        {job.traces.length === 0 && (
          <div className="animate-pulse text-xs text-neutral-500">Waiting for the agent</div>
        )}
        {job.traces.map((trace) => (
          <div key={trace.id} className="rounded-md bg-neutral-900 p-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-200">{prettyTitle(trace.title)}</span>
              <span className={`text-[10px] ${STATUS_STYLES[trace.status] ?? "text-neutral-500"}`}>
                {trace.status}
              </span>
            </div>
            {trace.detail && <p className="mt-1 text-[11px] text-neutral-500">{trace.detail}</p>}
          </div>
        ))}
      </div>

      <RefineComposer job={job} />
    </div>
  );
}
