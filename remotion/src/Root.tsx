import {AbsoluteFill, Audio, Composition, Img, OffthreadVideo, Sequence, useCurrentFrame, useVideoConfig} from 'remotion';
import type {CSSProperties} from 'react';

type Asset = {id: string; kind: 'image' | 'video' | 'audio'; url: string};
type Item = {
  id: string; type: 'clip' | 'text'; assetId?: string; start: number; duration: number;
  sourceIn?: number; sourceOut?: number; playbackRate?: number; volume?: number;
  fadeIn?: number; fadeOut?: number; fit?: 'cover' | 'contain'; opacity?: number;
  positionX?: number; positionY?: number; scale?: number; rotation?: number;
  motion?: string; text?: string; position?: 'top' | 'center' | 'bottom';
  fontSize?: number; fontWeight?: number; color?: string; backgroundColor?: string;
};
type Track = {id: string; kind: string; items: Item[]};
export type Props = {
  document: {id: string; name: string; assets: Asset[]; tracks: Track[]};
  renderConfig?: {fps?: number; width?: number; height?: number; durationInFrames?: number};
} & Record<string, unknown>;
const clamp = (value: number) => Math.max(0, Math.min(1, value));
const gain = (frame: number, item: Item, fps: number) => {
  const frames = Math.max(1, Math.round(item.duration * fps));
  const fadeIn = (item.fadeIn ?? 0) * fps;
  const fadeOut = (item.fadeOut ?? 0) * fps;
  return Math.min(fadeIn ? clamp(frame / fadeIn) : 1, fadeOut ? clamp((frames - 1 - frame) / fadeOut) : 1);
};

function Layer({item, asset}: {item: Item; asset?: Asset}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const progress = clamp(frame / Math.max(1, Math.round(item.duration * fps) - 1));
  const opacity = gain(frame, item, fps) * (item.opacity ?? 1);
  if (item.type === 'text') {
    return <AbsoluteFill style={{justifyContent: item.position === 'top' ? 'flex-start' : item.position === 'bottom' ? 'flex-end' : 'center', alignItems: 'center', padding: '6%', opacity}}>
      <div style={{fontFamily: 'Arial, sans-serif', fontSize: item.fontSize ?? 64, fontWeight: item.fontWeight ?? 700, color: item.color ?? 'white', background: item.backgroundColor ?? 'transparent', textAlign: 'center', whiteSpace: 'pre-wrap', padding: '12px 24px'}}>{item.text}</div>
    </AbsoluteFill>;
  }
  if (!asset) throw new Error(`Missing source asset for clip ${item.id}`);
  if (!asset.url) throw new Error(`Missing media URL for ${asset.id}`);
  const trimBefore = Math.round((item.sourceIn ?? 0) * fps);
  const trimAfter = Math.round((item.sourceOut ?? (item.sourceIn ?? 0) + item.duration * (item.playbackRate ?? 1)) * fps);
  if (asset.kind === 'audio') {
    return <Audio src={asset.url} trimBefore={trimBefore} trimAfter={trimAfter} volume={(f) => (item.volume ?? 1) * gain(f, item, fps)} />;
  }
  const zoom = item.motion === 'zoom_in' ? 1 + progress * 0.08 : item.motion === 'zoom_out' ? 1.08 - progress * 0.08 : item.motion?.startsWith('pan_') ? 1.08 : 1;
  const pan = item.motion === 'pan_left' ? 4 - progress * 8 : item.motion === 'pan_right' ? -4 + progress * 8 : 0;
  const style: CSSProperties = {width: '100%', height: '100%', objectFit: item.fit ?? 'cover', objectPosition: `${(item.positionX ?? 0.5) * 100}% ${(item.positionY ?? 0.5) * 100}%`, transform: `translateX(${pan}%) scale(${(item.scale ?? 1) * zoom}) rotate(${item.rotation ?? 0}deg)`};
  return <AbsoluteFill style={{opacity, overflow: 'hidden'}}>
    {asset.kind === 'image' ? <Img src={asset.url} style={style}/> : <OffthreadVideo src={asset.url} trimBefore={trimBefore} trimAfter={trimAfter} playbackRate={item.playbackRate ?? 1} style={style} volume={(f) => (item.volume ?? 1) * gain(f, item, fps)}/>}
  </AbsoluteFill>;
}

function Timeline({document}: Props) {
  const {fps, durationInFrames} = useVideoConfig();
  return <AbsoluteFill style={{background: 'black'}}>{document.tracks.flatMap((track) => track.items.map((item) => {
    const from = Math.round(item.start * fps);
    const frames = Math.min(durationInFrames - from, Math.max(1, Math.round((item.start + item.duration) * fps) - from));
    if (frames <= 0) return null;
    return <Sequence key={`${track.id}-${item.id}`} from={from} durationInFrames={frames} name={item.text || item.id}>
      <Layer item={item} asset={document.assets.find((asset) => asset.id === item.assetId)}/>
    </Sequence>;
  }))}</AbsoluteFill>;
}

const metadata = ({document, renderConfig}: Props) => {
  const fps = renderConfig?.fps ?? 30;
  const end = Math.max(0, ...document.tracks.filter((track) => ['video', 'overlay'].includes(track.kind)).flatMap((track) => track.items.map((item) => item.start + item.duration)));
  if (!Number.isFinite(end) || end <= 0) throw new Error('A render needs a non-empty visual sequence.');
  return {fps, width: renderConfig?.width ?? 1920, height: renderConfig?.height ?? 1080,
    durationInFrames: Math.max(1, Math.ceil(end * fps))};
};
const empty: Props = {document: {id: 'empty', name: 'Timeline', assets: [], tracks: []}};
export function Root() {
  return <Composition id="RenderhausTimeline" component={Timeline} defaultProps={empty} durationInFrames={1} fps={30} width={1920} height={1080} calculateMetadata={({props}) => metadata(props)}/>;
}
