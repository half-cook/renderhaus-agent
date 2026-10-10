import type { WaveState } from "@/lib/beta-credits";

/** 50-tick wave meter: claimed ticks in bone, open ticks in ember. Hidden when the counter is unavailable. */
export function Meter({ wave, height = 22 }: { wave: WaveState; height?: number }) {
  const claimed = Math.min(wave.capacity, Math.max(0, wave.claimed));
  return (
    <div className="rh-meter" style={{ height }} role="img" aria-label={`${wave.remaining} of ${wave.capacity} spots left`}>
      {Array.from({ length: wave.capacity }, (_, index) => <i key={index} className={index < claimed ? "rh-on" : "rh-open"} />)}
    </div>
  );
}

export function SpotsLeft({ wave }: { wave: WaveState | "unavailable" | null }) {
  if (!wave) return <span className="rh-fg3">Checking spots…</span>;
  if (wave === "unavailable" || wave.status === "closed") return <>Limited spots</>;
  if (wave.status === "full") return <>Wave 1 is full</>;
  return <><span className="rh-mono rh-num rh-spots">{wave.remaining} of {wave.capacity}</span> spots left</>;
}
