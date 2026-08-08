"use client";

import { ArrowLeft } from "lucide-react";
import { AgentRail } from "@/components/generation/AgentRail";
import { ComposerForm } from "@/components/generation/ComposerForm";
import { JobWorkspace } from "@/components/generation/JobWorkspace";
import { ProductionComposer } from "@/components/generation/ProductionComposer";
import { ProductionPlanView } from "@/components/generation/ProductionPlanView";
import { ProjectLibrary } from "@/components/generation/ProjectLibrary";
import { RecentHistoryStrip } from "@/components/generation/RecentHistoryStrip";
import {
  useGenerationStore,
  selectActiveJob,
  selectActiveProduction,
} from "@/lib/generation/store";

// Renders whatever IconRail's active tab calls for, in the panel slot
// between IconRail and the preview/timeline column (see EditorShell.tsx).
export function GenerationPanel() {
  const active = useGenerationStore((s) => s.activePanel);
  const activeJob = useGenerationStore(selectActiveJob);
  const setActiveJob = useGenerationStore((s) => s.setActiveJob);
  const activeProduction = useGenerationStore(selectActiveProduction);

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
      {active === "library" && <ProjectLibrary />}
      {active === "production" && (activeProduction ? <ProductionPlanView /> : <ProductionComposer />)}
    </div>
  );
}
