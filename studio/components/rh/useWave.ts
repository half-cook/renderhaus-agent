"use client";

import { useEffect, useState } from "react";
import { fetchWave, type WaveState } from "@/lib/beta-credits";

export const WAVE_POLL_MS = 15_000;

/** Polls the public counter every 15 s. `null` while loading, `"unavailable"` if it cannot be read. */
export function useWave(): WaveState | "unavailable" | null {
  const [wave, setWave] = useState<WaveState | "unavailable" | null>(null);
  useEffect(() => {
    let cancelled = false;
    const load = () => void fetchWave().then((next) => { if (!cancelled) setWave(next); }).catch(() => { if (!cancelled) setWave((current) => (current && current !== "unavailable" ? current : "unavailable")); });
    load();
    const timer = window.setInterval(load, WAVE_POLL_MS);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);
  return wave;
}
