import {useEffect, useState} from 'react';
import type {CSSProperties} from 'react';
import {AbsoluteFill, cancelRender, continueRender, delayRender, staticFile, useCurrentFrame} from 'remotion';

type Rectangle = {x: number; y: number; width: number; height: number};
type TimedWord = {text: string; start: number; end: number};
type Caption = {text: string; start: number; end: number; words: TimedWord[]};
export type TemplatePlan = {
  name: 'podcast-audiogram' | 'youtube-intro-sting' | 'youtube-end-screen';
  duration_seconds: number; fps: number; width: number; height: number;
  layout: Record<'safe' | 'art' | 'waveform' | 'captions' | 'identity' | 'progress', Rectangle>;
  captions: Caption[]; amplitudes: number[]; waveform: 'bars' | 'line'; bars: number;
  smoothing: number; speaker_name: string; show_name: string;
  background_color: string; accent_color: string; text_color: string;
  reserved_zones: Rectangle[];
};
const clamp = (value: number) => Math.max(0, Math.min(1, value));
let fontLoad: Promise<FontFace> | undefined;

const boxStyle = (box: Rectangle, plan: TemplatePlan): CSSProperties => ({
  position: 'absolute', left: Math.round(box.x * plan.width), top: Math.round(box.y * plan.height),
  width: Math.round(box.width * plan.width), height: Math.round(box.height * plan.height), overflow: 'hidden',
});

const fontSize = (box: Rectangle, plan: TemplatePlan, texts: string[], size: number) => {
  const length = Math.max(1, ...texts.map((text) => text.length));
  return Math.max(1, Math.floor(Math.min(size, Math.round(box.width * plan.width) / length * 1.6,
    Math.round(box.height * plan.height) / Math.max(1, texts.length) / 1.35)));
};

function Waveform({plan, frame}: {plan: TemplatePlan; frame: number}) {
  const box = plan.layout.waveform;
  const width = Math.round(box.width * plan.width);
  const height = Math.round(box.height * plan.height);
  const values = Array.from({length: plan.bars}, (_, index) =>
    plan.amplitudes[Math.max(0, Math.min(plan.amplitudes.length - 1, frame + index - Math.floor(plan.bars / 2)))] ?? 0);
  if (plan.waveform === 'bars') {
    const step = width / plan.bars;
    return <svg style={boxStyle(box, plan)} viewBox={`0 0 ${width} ${height}`}>
      {values.map((amplitude, index) => {
        const barHeight = Math.max(1, amplitude * height);
        return <rect key={index} x={index * step + step * 0.15} y={(height - barHeight) / 2}
          width={step * 0.7} height={barHeight} fill={plan.accent_color}/>;
      })}
    </svg>;
  }
  const points = values.map((amplitude, index) =>
    `${index * (width - 1) / (plan.bars - 1)},${height / 2 + (index % 2 ? -1 : 1) * amplitude * (height - 2) / 2}`).join(' ');
  return <svg style={boxStyle(box, plan)} viewBox={`0 0 ${width} ${height}`}>
    <polyline points={points} fill="none" stroke={plan.accent_color}
      strokeWidth={Math.max(1, Math.round(Math.min(plan.width, plan.height) * 0.003))}/>
  </svg>;
}

export function TemplateBackdrop({plan}: {plan: TemplatePlan}) {
  const frame = useCurrentFrame();
  const [handle] = useState(() => delayRender('Loading template font'));
  useEffect(() => {
    fontLoad ??= new FontFace('renderhaus-template', `url("${staticFile('fonts/DejaVuSans-Bold.ttf')}")`).load();
    let active = true;
    fontLoad.then((font) => {
      globalThis.document.fonts.add(font);
      if (active) continueRender(handle);
    }).catch((error: unknown) => {
      if (active) cancelRender(error instanceof Error ? error : new Error('Template font unavailable'));
    });
    return () => { active = false; };
  }, [handle]);
  const seconds = frame / plan.fps;
  const introOpacity = plan.name === 'youtube-intro-sting' ? clamp(seconds / 0.35) : 1;
  const introScale = plan.name === 'youtube-intro-sting' ? 0.92 + 0.08 * introOpacity : 1;
  const identity = [plan.show_name, plan.speaker_name].filter((text) => text.length > 0);
  const identitySize = fontSize(plan.layout.identity, plan, identity, Math.min(plan.width, plan.height) * 0.052 * introScale);
  const caption = plan.captions.find((item) => item.start <= seconds && seconds < item.end);
  const captionSize = caption ? fontSize(plan.layout.captions, plan,
    [caption.words.map((word) => word.text).join(' ')], Math.min(plan.width, plan.height) * 0.07) : 1;
  const frames = Math.ceil(plan.duration_seconds * plan.fps - 1e-9);
  const progress = clamp(frame / Math.max(1, frames - 1));
  const panel: CSSProperties = {display: 'flex', flexDirection: 'column', justifyContent: 'center',
    alignItems: 'center', color: plan.text_color, fontFamily: 'renderhaus-template', fontWeight: 700,
    textAlign: 'center', whiteSpace: 'pre'};
  return <AbsoluteFill style={{backgroundColor: plan.background_color}}>
    {identity.length > 0 ? <div style={{...boxStyle(plan.layout.identity, plan), ...panel,
      fontSize: identitySize, lineHeight: `${identitySize * 1.35}px`, opacity: introOpacity}}>
      {identity.map((text, index) => <div key={index}>{text}</div>)}
    </div> : null}
    {plan.name === 'podcast-audiogram' ? <>
      <Waveform plan={plan} frame={frame}/>
      {caption ? <div style={{...boxStyle(plan.layout.captions, plan), ...panel,
        fontSize: captionSize, lineHeight: `${captionSize * 1.35}px`}}>
        <div>{caption.words.map((word, index) => <span key={index}
          style={{color: word.start <= seconds && seconds < word.end ? plan.accent_color : plan.text_color}}>
          {index ? ' ' : ''}{word.text}
        </span>)}</div>
      </div> : null}
      <div style={{...boxStyle(plan.layout.progress, plan), width: Math.round(plan.layout.progress.width * plan.width * progress),
        backgroundColor: plan.accent_color}}/>
    </> : null}
  </AbsoluteFill>;
}
