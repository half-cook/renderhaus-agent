"use client";

import { Send } from "lucide-react";
import { useState } from "react";
import { useApiClient } from "@/lib/api/useApiClient";
import { ApiError, type Job } from "@/lib/api/types";
import { useGenerationStore } from "@/lib/generation/store";

const MIN_INSTRUCTION_LENGTH = 3;

// Pre-written refinement prompts, ported verbatim from the old static
// frontend (server/static/app.js) -- prefill (not auto-submit) the
// textarea when clicked.
const VIDEO_IDEAS = [
  "Slow the push in",
  "Hold on the hero",
  "Warmer grade",
  "Tighter framing",
  "Add a reverse",
  "Softer motion",
  "More atmosphere",
  "Cleaner product",
];

const MUSIC_IDEAS = [
  "Slower tempo",
  "Warmer pads",
  "More tension",
  "Strip it back",
  "Cinematic swell",
  "Pulse under it",
];

// Shown once a job has finished media and isn't an image (matches old UI --
// image jobs have no refine affordance). Spawns a NEW job with parent_id
// set rather than mutating the current one; swaps the workspace to it.
export function RefineComposer({ job }: { job: Job }) {
  const api = useApiClient();
  const upsertJob = useGenerationStore((s) => s.upsertJob);
  const setActiveJob = useGenerationStore((s) => s.setActiveJob);
  const [instruction, setInstruction] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (job.status !== "complete" || job.media_type === "image") return null;

  const ideas = job.media_type === "music" ? MUSIC_IDEAS : VIDEO_IDEAS;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = instruction.trim();
    if (trimmed.length < MIN_INSTRUCTION_LENGTH) return;

    setSubmitting(true);
    setError(null);
    try {
      const newJob = await api.refineGeneration(job.id, { instruction: trimmed });
      upsertJob(newJob);
      setActiveJob(newJob.id);
      setInstruction("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Refine failed. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 border-t border-neutral-800 pt-3">
      <div className="flex flex-wrap gap-1">
        {ideas.map((idea) => (
          <button
            key={idea}
            type="button"
            onClick={() => setInstruction(idea)}
            className="rounded-full border border-neutral-800 px-2 py-0.5 text-[11px] text-neutral-400 hover:border-neutral-600 hover:text-neutral-200"
          >
            {idea}
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="flex items-end gap-2">
        <textarea
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="Refine this render…"
          className="min-w-0 flex-1 resize-none rounded-md border border-neutral-800 bg-neutral-900 p-2 text-xs text-neutral-200 placeholder:text-neutral-600 focus:border-neutral-600 focus:outline-none"
        />
        <button
          type="submit"
          disabled={submitting || instruction.trim().length < MIN_INSTRUCTION_LENGTH}
          className="shrink-0 rounded-md bg-indigo-500 p-2 text-white hover:bg-indigo-400 disabled:opacity-30"
        >
          <Send size={14} />
        </button>
      </form>
      {error && <p className="text-[11px] text-red-400">{error}</p>}
    </div>
  );
}
