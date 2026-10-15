"use client";

import { cutClips, withChangesCut, type ChangesDocument, type Cut } from "@/lib/rh/changes";
import { clipLength, totalSeconds, type TimelineClip } from "@/lib/rh/timeline";

type RibbonClip = { clip: TimelineClip; start: number; end: number; takeId: string | undefined };

function ribbonClips(document: ChangesDocument, cut: Cut): RibbonClip[] {
  let cursor = 0;
  return cutClips(document, cut).map((clip) => {
    const start = cursor;
    cursor += clipLength(clip);
    return { clip, start, end: cursor, takeId: cut.slots.find((slot) => slot.slotId === clip.id)?.takeId };
  });
}

export function CutRibbon({ document, beforeCut = document.checkpointCut, afterCut, compact = false, onSelectShot }: {
  document: ChangesDocument;
  beforeCut?: Cut;
  afterCut?: Cut;
  compact?: boolean;
  onSelectShot?: (slotId: string) => void;
}) {
  const proposedCut = afterCut ?? withChangesCut(document);
  const before = ribbonClips(document, beforeCut);
  const after = ribbonClips(document, proposedCut);
  const beforeSeconds = totalSeconds(before.map((entry) => entry.clip));
  const afterSeconds = totalSeconds(after.map((entry) => entry.clip));
  const extent = Math.max(beforeSeconds, afterSeconds, 1);
  const width = (seconds: number) => (seconds / extent) * 100;
  const changed = (entry: RibbonClip) => {
    const old = before.find((item) => item.clip.id === entry.clip.id);
    return !old || old.takeId !== entry.takeId || old.clip.trimIn !== entry.clip.trimIn || old.clip.trimOut !== entry.clip.trimOut || old.clip.order !== entry.clip.order;
  };
  const summary = after.map((entry) => {
    const old = before.find((item) => item.clip.id === entry.clip.id);
    if (!old || !changed(entry)) return `${entry.clip.title} unchanged`;
    const take = document.takes.find((item) => item.id === entry.takeId);
    const delta = clipLength(entry.clip) - clipLength(old.clip);
    return `${entry.clip.title}${old.takeId !== entry.takeId && take ? ` take ${take.n}` : ""}${delta ? `, ${Math.abs(delta).toFixed(1)} s ${delta < 0 ? "shorter" : "longer"}` : ""}`;
  }).join(" · ");

  return (
    <section className="rh-cut-ribbon" data-compact={compact || undefined} aria-label="Cut alignment">
      {!compact ? <div className="rh-cut-ribbon-heading"><h3>Cut alignment</h3><p>Compare follows the shot, so a trim keeps both sides in step.</p><span className="rh-mono">{summary}</span></div> : null}
      <div className="rh-cut-ribbon-body">
        <div className="rh-cut-ribbon-tracks">
          <span className="rh-cut-ribbon-label rh-cut-ribbon-before rh-mono">Before · {beforeSeconds.toFixed(1)} s</span>
          <svg className="rh-cut-ribbon-links" viewBox="0 0 1000 150" preserveAspectRatio="none" aria-hidden="true">
            {before.map((entry) => {
              const proposed = after.find((item) => item.clip.id === entry.clip.id);
              if (!proposed) return null;
              return <polygon key={entry.clip.id} data-changed={changed(proposed) || undefined} points={`${width(entry.start) * 10},66 ${width(entry.end) * 10},66 ${width(proposed.end) * 10},84 ${width(proposed.start) * 10},84`} />;
            })}
          </svg>
          {before.map((entry) => <RibbonBar key={entry.clip.id} entry={entry} takeN={document.takes.find((take) => take.id === entry.takeId)?.n} left={width(entry.start)} width={width(entry.end - entry.start)} row="before" onSelect={onSelectShot} />)}
          {after.map((entry) => {
            const old = before.find((item) => item.clip.id === entry.clip.id);
            const removed = old ? clipLength(old.clip) - clipLength(entry.clip) : 0;
            return <div key={entry.clip.id}>
              <RibbonBar entry={entry} takeN={document.takes.find((take) => take.id === entry.takeId)?.n} left={width(entry.start)} width={width(entry.end - entry.start)} row="after" changed={changed(entry)} onSelect={onSelectShot} />
              {removed > 0 ? <span className="rh-cut-ribbon-trim rh-mono" style={{ left: `${width(entry.end)}%`, width: `${width(removed)}%` }}><span>−{removed.toFixed(1)} s</span></span> : null}
            </div>;
          })}
          <span className="rh-cut-ribbon-label rh-cut-ribbon-after rh-mono">After · {afterSeconds.toFixed(1)} s</span>
          {!before.length && !after.length ? <p className="rh-cut-ribbon-empty">Add a shot to see the cut alignment.</p> : null}
        </div>
        {!compact ? <ul className="rh-cut-ribbon-legend"><li><i />Unchanged shot</li><li><i data-kind="proposed" />New take, proposed</li><li><i data-kind="trimmed" />Trimmed away</li></ul> : null}
      </div>
    </section>
  );
}

function RibbonBar({ entry, takeN, left, width, row, changed, onSelect }: {
  entry: RibbonClip;
  takeN: number | undefined;
  left: number;
  width: number;
  row: "before" | "after";
  changed?: boolean;
  onSelect?: (slotId: string) => void;
}) {
  const label = `${String(entry.clip.order).padStart(2, "0")} · ${entry.clip.title}${takeN ? ` · take ${takeN}` : ""}`;
  const style = { left: `${left}%`, width: `${width}%`, backgroundImage: entry.clip.thumbUrl ? `url("${entry.clip.thumbUrl}")` : undefined };
  return onSelect
    ? <button type="button" className="rh-cut-ribbon-clip" data-row={row} data-changed={changed || undefined} style={style} aria-label={`${row === "before" ? "Before" : "After"}, ${label}, ${(entry.end - entry.start).toFixed(1)} seconds`} onClick={() => onSelect(entry.clip.id)}><span className="rh-mono">{label}</span></button>
    : <div className="rh-cut-ribbon-clip" data-row={row} data-changed={changed || undefined} style={style}><span className="rh-mono">{label}</span></div>;
}
