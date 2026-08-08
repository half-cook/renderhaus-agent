"use client";

import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { useApiClient } from "@/lib/api/useApiClient";
import { usePoll } from "@/lib/api/usePolling";
import {
  ApiError,
  TERMINAL_PLAN_STATES,
  TERMINAL_RUN_STATES,
  type NodeResult,
  type PlanNode,
} from "@/lib/api/types";
import { useGenerationStore, selectActiveProduction } from "@/lib/generation/store";
import { computePlanLayers } from "./planLayers";

const POLL_INTERVAL_MS = 1500;
const PLANNING_STATUSES = new Set(["draft", "planning"]);
const RUNNING_STATUSES = new Set(["approved", "running"]);

function NodeCard({ node, result }: { node: PlanNode; result?: NodeResult }) {
  const status = result?.status ?? (result ? "done" : undefined);
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-md border border-neutral-800 bg-neutral-900 p-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-medium text-neutral-200">{node.id}</span>
        <span className="shrink-0 text-[10px] text-neutral-500">{node.kind}</span>
      </div>
      <p className="line-clamp-2 text-[11px] text-neutral-500">{node.prompt}</p>
      {node.depends_on.length > 0 && (
        <p className="text-[10px] text-neutral-600">after {node.depends_on.join(", ")}</p>
      )}
      {status && <p className="text-[10px] text-indigo-400">{status}</p>}
    </div>
  );
}

// Polls with a phase-dependent terminal set (plan §6.9/§3): two separate
// usePoll calls, each enabled purely off the production's CURRENT status
// from the store. Simpler than one hook trying to detect "restart polling
// after a manual mutation changed status back to non-terminal" -- flipping
// `enabled` false->true on approve naturally restarts the run-phase poll's
// effect, no extra plumbing needed in the shared usePolling hook.
export function ProductionPlanView() {
  const api = useApiClient();
  const production = useGenerationStore(selectActiveProduction);
  const activeProductionId = useGenerationStore((s) => s.activeProductionId);
  const upsertProduction = useGenerationStore((s) => s.upsertProduction);
  const setActiveProduction = useGenerationStore((s) => s.setActiveProduction);

  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isPlanningPhase = production ? PLANNING_STATUSES.has(production.status) : false;
  const isRunningPhase = production ? RUNNING_STATUSES.has(production.status) : false;

  const planPoll = usePoll(
    () => api.getProduction(activeProductionId as string),
    {
      intervalMs: POLL_INTERVAL_MS,
      isTerminal: (p) => TERMINAL_PLAN_STATES.has(p.status),
      enabled: isPlanningPhase,
    },
  );
  const runPoll = usePoll(
    () => api.getProduction(activeProductionId as string),
    {
      intervalMs: POLL_INTERVAL_MS,
      isTerminal: (p) => TERMINAL_RUN_STATES.has(p.status),
      enabled: isRunningPhase,
    },
  );

  useEffect(() => {
    if (planPoll.data) upsertProduction(planPoll.data);
  }, [planPoll.data, upsertProduction]);
  useEffect(() => {
    if (runPoll.data) upsertProduction(runPoll.data);
  }, [runPoll.data, upsertProduction]);

  if (!production) return null;

  async function handleApprove() {
    if (!production) return;
    setApproving(true);
    setError(null);
    try {
      const updated = await api.approveProductionPlan(production.id, { execute: true });
      upsertProduction(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not approve the plan.");
    } finally {
      setApproving(false);
    }
  }

  const nodes = production.plan?.nodes ?? [];
  const layers = computePlanLayers(nodes);
  const resultsByNodeId = new Map((production.execution?.node_results ?? []).map((r) => [r.node_id, r]));

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
      <button
        onClick={() => setActiveProduction(null)}
        className="flex items-center gap-1.5 text-xs text-neutral-500 hover:text-neutral-200"
      >
        <ArrowLeft size={13} />
        New brief
      </button>

      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-neutral-100">{production.title || "Untitled production"}</p>
        <span className="rounded-full bg-neutral-900 px-2 py-0.5 text-[10px] text-neutral-400">
          {production.status}
        </span>
      </div>

      <p className="text-xs text-neutral-500">
        {production.plan?.summary ??
          (production.error ? production.error : "Planning… the Director is drafting a plan.")}
      </p>

      {layers.length > 0 && (
        <div className="flex flex-col gap-2">
          {layers.map((layer, index) => (
            <div key={index} className="flex flex-col gap-1.5">
              {layer.map((node) => (
                <NodeCard key={node.id} node={node} result={resultsByNodeId.get(node.id)} />
              ))}
            </div>
          ))}
        </div>
      )}

      {error && <p className="text-xs text-red-400">{error}</p>}

      {production.status === "plan_ready" && (
        <button
          onClick={handleApprove}
          disabled={approving}
          className="rounded-md bg-indigo-500 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50"
        >
          {approving ? "Starting…" : "Approve & run"}
        </button>
      )}
    </div>
  );
}
