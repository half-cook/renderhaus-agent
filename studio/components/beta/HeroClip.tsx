"use client";

import { Play, Sparkles } from "lucide-react";
import { useRef, useState } from "react";

/** The P1 film: poster until the viewer presses play. Never autoplays with sound. */
export function HeroClip() {
  const video = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(10);
  const fmt = (seconds: number) => `0:${String(Math.floor(seconds)).padStart(2, "0")}`;
  return (
    <div className="rh-ticks rh-hero-clip">
      <div className="rh-hero-frame">
        <video
          ref={video} className="rh-hero-video" src="/beta/p1-film.mp4" poster="/beta/p1-poster.jpg" preload="metadata" playsInline
          aria-label="Example film: one product photo becomes a 10 second film with voiceover"
          controls={playing}
          onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)}
          onTimeUpdate={(event) => setTime(event.currentTarget.currentTime)}
          onLoadedMetadata={(event) => setDuration(event.currentTarget.duration || 10)}
        />
        <span className="rh-ai-label"><Sparkles size={12} aria-hidden="true" />AI-generated</span>
        {!playing ? (
          <button type="button" className="rh-hero-play" aria-label="Play the example film" onClick={() => void video.current?.play()}>
            <Play size={26} aria-hidden="true" />
          </button>
        ) : null}
        {!playing ? (
          <div className="rh-hero-meta">
            <div className="rh-hero-scrub"><div style={{ width: `${Math.min(100, (time / duration) * 100)}%` }} /></div>
            <div className="rh-hero-times rh-mono"><span>{fmt(time)} / {fmt(duration)}</span><span>One photo → a 10 s film with voiceover</span></div>
          </div>
        ) : null}
      </div>
      <span className="rh-tk" />
    </div>
  );
}
