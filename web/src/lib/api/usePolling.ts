"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "./types";

interface UsePollOptions<T> {
  intervalMs: number;
  isTerminal: (item: T) => boolean;
  enabled: boolean;
}

interface UsePollResult<T> {
  data: T | null;
  error: Error | null;
}

// Generalizes the old static frontend's poll-token pattern: a ref-counter
// incremented on every new poll start, each in-flight tick checks its
// captured token against the live counter before applying results, so a
// stale poll (e.g. the user navigated to a different job mid-poll) becomes
// a no-op instead of clobbering newer state. Used by both job polling
// (server/app.py's TERMINAL_JOB_STATES) and production polling, where the
// terminal set is phase-dependent -- pass isTerminal as a function
// recomputed from current status, not a fixed Set, so it can change mid-flow.
//
// Uses recursive setTimeout (schedule the next tick only after the current
// fetch resolves) rather than a flat setInterval, so a slow response can't
// overlap with the next tick.
export function usePoll<T>(
  fetchFn: () => Promise<T>,
  { intervalMs, isTerminal, enabled }: UsePollOptions<T>,
): UsePollResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const tokenRef = useRef(0);
  const fetchFnRef = useRef(fetchFn);
  const isTerminalRef = useRef(isTerminal);

  // Keep the latest closures without them being effect dependencies --
  // ref writes must happen in an effect, not during render (react-hooks/refs).
  useEffect(() => {
    fetchFnRef.current = fetchFn;
    isTerminalRef.current = isTerminal;
  });

  useEffect(() => {
    if (!enabled) return;

    const token = ++tokenRef.current;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    async function tick() {
      try {
        const result = await fetchFnRef.current();
        if (cancelled || token !== tokenRef.current) return;
        setData(result);
        setError(null);
        if (!isTerminalRef.current(result)) {
          timer = setTimeout(tick, intervalMs);
        }
      } catch (err) {
        if (cancelled || token !== tokenRef.current) return;
        setError(err instanceof ApiError ? err : new Error(String(err)));
      }
    }

    void tick();

    return () => {
      cancelled = true;
      tokenRef.current += 1; // invalidate any in-flight tick from this run
      if (timer) clearTimeout(timer);
    };
    // fetchFn/isTerminal intentionally read via refs (kept fresh above), not deps
  }, [enabled, intervalMs]);

  return { data, error };
}
