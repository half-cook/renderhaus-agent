"use client";

import { useClerk, useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { useApiClient } from "@/lib/api/useApiClient";
import { ApiError } from "@/lib/api/types";
import { useGenerationStore } from "@/lib/generation/store";

const MIN_BRIEF_LENGTH = 1;
const MAX_BRIEF_LENGTH = 8000;

// Brief -> POST /api/productions{plan_now: true}. The Director plans
// asynchronously; ProductionPlanView (rendered once activeProductionId is
// set) takes over from there.
export function ProductionComposer() {
  const { isLoaded, isSignedIn } = useAuth();
  const { openSignIn } = useClerk();
  const api = useApiClient();
  const upsertProduction = useGenerationStore((s) => s.upsertProduction);
  const setActiveProduction = useGenerationStore((s) => s.setActiveProduction);

  const [brief, setBrief] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    const trimmed = brief.trim();
    if (trimmed.length < MIN_BRIEF_LENGTH) {
      setError("Write a brief first.");
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
      const production = await api.createProduction({ brief: trimmed, plan_now: true });
      upsertProduction(production);
      setActiveProduction(production.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The request failed. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 p-4">
      <p className="text-xs text-neutral-500">
        The Director drafts a typed multi-shot plan first. Approve it to run the workers.
      </p>
      <textarea
        value={brief}
        onChange={(event) => setBrief(event.target.value)}
        rows={5}
        maxLength={MAX_BRIEF_LENGTH}
        placeholder="30s product teaser: chrome bottle on concrete, soft daylight, calm piano underscore…"
        className="resize-none rounded-md border border-neutral-800 bg-neutral-900 p-3 text-sm text-neutral-200 placeholder:text-neutral-600 focus:border-neutral-600 focus:outline-none"
      />
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
        {submitting ? "Planning…" : "Plan production"}
      </button>
    </form>
  );
}
