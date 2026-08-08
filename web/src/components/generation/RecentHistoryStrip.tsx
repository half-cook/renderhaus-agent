"use client";

import { useGenerationStore } from "@/lib/generation/store";

// The old static frontend's "Recent" strip: last 8 jobs, draggable once
// complete (drag payload = job id -- ProjectLibrary's project-card drop
// targets consume this, plan §6.6/§6.7). Only rendered while composing
// (GenerationPanel hides this once a job is active/being reviewed).
export function RecentHistoryStrip() {
  const recentJobIds = useGenerationStore((s) => s.recentJobIds);
  const jobs = useGenerationStore((s) => s.jobs);
  const setActiveJob = useGenerationStore((s) => s.setActiveJob);

  if (recentJobIds.length === 0) return null;

  return (
    <div className="flex flex-col gap-2 border-t border-neutral-800 p-4">
      <p className="text-[11px] uppercase tracking-wide text-neutral-600">Recent</p>
      <div className="flex flex-col gap-1">
        {recentJobIds.map((jobId) => {
          const job = jobs[jobId];
          if (!job) return null;
          return <RecentHistoryCard key={jobId} job={job} onOpen={() => setActiveJob(jobId)} />;
        })}
      </div>
    </div>
  );
}

function RecentHistoryCard({
  job,
  onOpen,
}: {
  job: ReturnType<typeof useGenerationStore.getState>["jobs"][string];
  onOpen: () => void;
}) {
  const title = job.prompt.split(/\s+/).slice(0, 3).join(" ") || job.id;
  const draggable = job.status === "complete";

  return (
    <button
      onClick={onOpen}
      draggable={draggable}
      onDragStart={(event) => {
        if (!draggable) return;
        event.dataTransfer.setData("text/plain", job.id);
      }}
      className="flex items-center justify-between rounded-md px-2 py-1.5 text-left text-xs text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200"
    >
      <span className="truncate">{title}</span>
      <span className="ml-2 shrink-0 text-[10px] text-neutral-600">
        {job.media_type} · {job.status}
      </span>
    </button>
  );
}
