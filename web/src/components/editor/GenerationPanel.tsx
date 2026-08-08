"use client";

import { ArrowLeft } from "lucide-react";
import { AgentRail } from "@/components/generation/AgentRail";
import { ComposerForm } from "@/components/generation/ComposerForm";
import { JobWorkspace } from "@/components/generation/JobWorkspace";
import { RecentHistoryStrip } from "@/components/generation/RecentHistoryStrip";
import { useGenerationStore, selectActiveJob } from "@/lib/generation/store";

// Renders whatever IconRail's active tab calls for, in the panel slot
// between IconRail and the preview/timeline column (see EditorShell.tsx).
// Library/Production bodies land in later steps of the plan
// (inherited-wishing-flurry.md §6/§7).
export function GenerationPanel() {
  const active = useGenerationStore((s) => s.activePanel);
  const activeJob = useGenerationStore(selectActiveJob);
  const setActiveJob = useGenerationStore((s) => s.setActiveJob);

  if (active === "captions" || active === "text" || active === "settings") return null;

  return (
    <div className="flex w-96 shrink-0 flex-col border-r border-neutral-800">
      {active === "generate" &&
        (activeJob ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <button
              onClick={() => setActiveJob(null)}
              className="flex items-center gap-1.5 px-4 py-3 text-xs text-neutral-500 hover:text-neutral-200"
            >
              <ArrowLeft size={13} />
              New prompt
            </button>
            <JobWorkspace />
            <AgentRail />
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            <ComposerForm />
            <RecentHistoryStrip />
          </div>
        ))}
      {active === "library" && (
        <div className="p-4 text-sm text-neutral-500">Library panel coming soon.</div>
      )}
      {active === "production" && (
        <div className="p-4 text-sm text-neutral-500">Production panel coming soon.</div>
      )}
    </div>
  );
}
