"use client";

import { useCanvasStore } from "@/lib/canvas/store";
import { clipLength, secondsLabel, totalSeconds } from "@/lib/rh/timeline";
import { useTimelineModel } from "./Timeline";

/** Read-only list of the shots on the track, for the agent's side panel. Editing happens in the Timeline view. */
export function TimelineMini() {
  const model = useTimelineModel();
  const setView = useCanvasStore((state) => state.setWorkspaceView);
  return (
    <div className="rh-tlmini">
      <div className="rh-tlmini-head"><h2 className="rh-h3">Timeline</h2><span className="rh-fg3 rh-small">{model.clips.length ? `${model.clips.length} shots · ${secondsLabel(totalSeconds(model.clips))}` : "No shots yet"}</span></div>
      {model.clips.length === 0 ? <p className="rh-fg3 rh-small">Approved shots appear here, in order. Trim and reorder them in the Timeline view.</p> : (
        <ol>
          {model.clips.map((clip) => (
            <li key={clip.id}>
              <span className="rh-thumb rh-tlmini-thumb" style={clip.thumbUrl ? { backgroundImage: `url(${clip.thumbUrl})` } : undefined} />
              <span><b>{String(clip.order).padStart(2, "0")} · {clip.title}</b><i className="rh-mono">{secondsLabel(clipLength(clip))}</i></span>
            </li>
          ))}
        </ol>
      )}
      <button type="button" className="rh-btn rh-btn-block" onClick={() => setView("timeline")}>Open timeline</button>
    </div>
  );
}
